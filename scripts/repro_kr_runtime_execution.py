#!/usr/bin/env python3
"""
Follow-on to repro_kr_dataset_drop.py. That script established that cross-tenant DSL import
silently empties a knowledge-retrieval node's dataset_ids. This script answers item #12 of
docs/upstream-facts.md's do-not-claim list, which was explicitly marked unverified: what does
the node do at *execution* time once dataset_ids is empty?

Answered by source (already confirmed as an anchor, this run makes it live too):
  api/core/rag/retrieval/dataset_retrieval.py:122-123 -- `if not available_datasets_ids: return []`
  before query or attachments are even inspected.

Method: reproduce the cross-tenant import exactly as before (source tenant C -> target tenant D),
then single-step-run the knowledge-retrieval node in both tenants via
POST /console/api/apps/{app_id}/workflows/draft/nodes/{node_id}/run, and compare the
WorkflowRunNodeExecutionResponse: status, error, outputs.

Usage:
    python3 repro_kr_runtime_execution.py \
        --base http://127.0.0.1:18091 \
        --email-c c-runtime@example.invalid --password-c ... \
        --email-d d-runtime@example.invalid --password-d ... \
        --out ../evidence
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from datetime import datetime, timezone
from typing import Any

# Reuse the console client from the sibling script; the DSL builder is NOT reused (see
# source_dsl_runnable below) so the already-evidenced repro_kr_dataset_drop.py stays untouched.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from repro_kr_dataset_drop import Console, import_app, redact_body, redact_id  # noqa: E402


def source_dsl_runnable(dataset_id: str, app_name: str) -> str:
    """Same shape as repro_kr_dataset_drop.source_dsl, except reranking_mode is
    "reranking_model" with no model configured. "weighted_score" (the sibling script's choice)
    makes knowledge_retrieval_node.py:229 raise "weights is required" before dataset_ids is ever
    consulted -- irrelevant to what this script measures, and it fires identically whether
    dataset_ids is populated or empty, as confirmed by the first run of this script (both the
    control and the experiment failed with that same message). "reranking_model" with the model
    left unset takes the `else: reranking_model = None` branch (same file, :232) instead, so
    the run actually reaches _rag_retrieval.knowledge_retrieval().
    """
    graph = {
        "nodes": [
            {
                "id": "start",
                "type": "custom",
                "position": {"x": 0, "y": 0},
                "data": {"type": "start", "title": "Start", "variables": []},
            },
            {
                "id": "kr",
                "type": "custom",
                "position": {"x": 300, "y": 0},
                "data": {
                    "type": "knowledge-retrieval",
                    "title": "Knowledge Retrieval",
                    "dataset_ids": [dataset_id],
                    "retrieval_mode": "multiple",
                    "query_variable_selector": ["start", "sys.query"],
                    "multiple_retrieval_config": {
                        "top_k": 2,
                        "score_threshold": None,
                        "reranking_mode": "reranking_model",
                        "reranking_enable": False,
                    },
                },
            },
            {
                "id": "end",
                "type": "custom",
                "position": {"x": 600, "y": 0},
                "data": {"type": "end", "title": "End", "outputs": []},
            },
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "kr", "data": {"sourceType": "start", "targetType": "knowledge-retrieval"}},
            {"id": "e2", "source": "kr", "target": "end", "data": {"sourceType": "knowledge-retrieval", "targetType": "end"}},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    doc = {
        "version": "0.7.0",
        "kind": "app",
        "app": {
            "name": app_name,
            "mode": "workflow",
            "icon": "\U0001f916",
            "icon_background": "#FFEAD5",
            "description": "single knowledge-retrieval node; nothing else",
            "use_icon_as_answer_icon": False,
        },
        "workflow": {
            "graph": graph,
            "features": {},
            "environment_variables": [],
            "conversation_variables": [],
        },
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def draft_node(client: Console, app_id: str) -> tuple[str, dict[str, Any]]:
    status, body = client.call("GET", f"/console/api/apps/{app_id}/workflows/draft")
    if status != 200 or not isinstance(body, dict):
        raise SystemExit(f"cannot read draft workflow: HTTP {status} {body}")
    for node in body.get("graph", {}).get("nodes", []):
        if node.get("data", {}).get("type") == "knowledge-retrieval":
            return node["id"], node["data"]
    raise SystemExit("no knowledge-retrieval node in the imported draft graph")


def run_node(client: Console, app_id: str, node_id: str, query_input_key: str) -> tuple[int, dict[str, Any]]:
    status, body = client.call(
        "POST",
        f"/console/api/apps/{app_id}/workflows/draft/nodes/{node_id}/run",
        {"inputs": {query_input_key: "does this org have a refund policy?"}},
    )
    return status, body if isinstance(body, dict) else {"raw": body}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--email-c", required=True)
    ap.add_argument("--password-c", required=True)
    ap.add_argument("--email-d", required=True)
    ap.add_argument("--password-d", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ev: dict[str, Any] = {"started_at": now(), "base": args.base, "steps": []}

    def record(name: str, **fields: Any) -> None:
        ev["steps"].append({"step": name, "at": now(), **fields})
        print(f"[{now()}] {name}")

    c = Console(args.base, "C")
    d = Console(args.base, "D")
    c.login(args.email_c, args.password_c)
    d.login(args.email_d, args.password_d)
    tc, td = c.tenant_id(), d.tenant_id()
    if tc == td:
        raise SystemExit("tenant C and tenant D are the same tenant -- the experiment is void")
    record("logged-in", tenant_c=redact_id(tc), tenant_d=redact_id(td), tenants_differ=True)

    # --- source material in tenant C --------------------------------------------------
    status, ds = c.call("POST", "/console/api/datasets", {"name": f"kbC-{now()}", "indexing_technique": "economy"})
    if status not in (200, 201):
        raise SystemExit(f"dataset creation failed: HTTP {status} {ds}")
    dataset_id = ds["id"]
    record("dataset-created-in-C", dataset_id=redact_id(dataset_id))

    src = source_dsl_runnable(dataset_id, "kr-runtime-source")
    app_c = import_app(c, src, "C: create source app")
    node_id_c, node_data_c = draft_node(c, app_c["app_id"])
    record(
        "source-app-in-C",
        app_id=redact_id(app_c["app_id"]),
        node_id=node_id_c,
        dataset_ids_bound=[redact_id(i) for i in node_data_c.get("dataset_ids", [])],
    )

    status, exported = c.call("GET", f"/console/api/apps/{app_c['app_id']}/export")
    if status != 200:
        raise SystemExit(f"export failed: HTTP {status} {exported}")
    yaml_text = exported["data"]
    m = re.search(r"dataset_ids:\s*\n\s*-\s*(\S+)", yaml_text)
    ciphertext = m.group(1).strip("'\"") if m else None
    if not ciphertext or ciphertext == dataset_id:
        raise SystemExit("exported dataset_ids is not ciphertext -- run is void")
    record("exported-from-C", yaml_sha256=sha256(yaml_text))

    # --- cross-tenant import into D: reproduces the drop ------------------------------
    app_d = import_app(d, yaml_text, "experiment: C -> D")
    node_id_d, node_data_d = draft_node(d, app_d["app_id"])
    dropped = node_data_d.get("dataset_ids", []) == []
    record(
        "cross-tenant-import-into-D",
        app_id=redact_id(app_d["app_id"]),
        node_id=node_id_d,
        dataset_ids_after_import=node_data_d.get("dataset_ids", []),
        dropped=dropped,
    )
    if not dropped:
        raise SystemExit("dataset_ids was not dropped on import into D -- precondition for this test failed")

    # --- the question this script exists to answer: does running the node fail? -------
    # variable_mapping key is f"{node_id}.query" (knowledge_retrieval_node.py:353), independent
    # of tenant, because it is derived from the node's own id, which import preserves.
    status_c, run_c = run_node(c, app_c["app_id"], node_id_c, f"{node_id_c}.query")
    record(
        "single-step-run-in-C-control",
        http_status=status_c,
        node_status=run_c.get("status"),
        error=run_c.get("error"),
        outputs=redact_body(run_c.get("outputs")),
        shows="control: dataset_ids intact in the source tenant, same tenant as the dataset itself",
    )

    status_d, run_d = run_node(d, app_d["app_id"], node_id_d, f"{node_id_d}.query")
    record(
        "single-step-run-in-D-experiment",
        http_status=status_d,
        node_status=run_d.get("status"),
        error=run_d.get("error"),
        outputs=redact_body(run_d.get("outputs")),
        shows=(
            "the node executes with an empty dataset_ids list -- this row is the answer to "
            "do-not-claim item #12"
        ),
    )

    ev["finished_at"] = now()
    ev["verdict"] = {
        "node_run_with_empty_dataset_ids_status": run_d.get("status"),
        "node_run_with_empty_dataset_ids_error": run_d.get("error"),
        "node_run_raised_no_error": run_d.get("status") == "succeeded" and not run_d.get("error"),
        "control_node_run_status": run_c.get("status"),
    }

    out = pathlib.Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"kr-runtime-execution-{ev['started_at'].replace(':', '')}.json"
    dest.write_text(json.dumps(ev, indent=2, ensure_ascii=False))
    print(f"\nverdict: {json.dumps(ev['verdict'])}\nevidence: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
