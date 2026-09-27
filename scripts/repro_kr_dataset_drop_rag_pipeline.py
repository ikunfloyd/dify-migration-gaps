#!/usr/bin/env python3
"""
S4 follow-up: docs/upstream-facts.md S4 lists the RAG-pipeline DSL path as a *separate*
implementation from api/services/app_dsl_service.py, explicitly not tested for the same drop.
This script tests it, mirroring the method of repro_kr_dataset_drop.py: one dataset, one pipeline
containing a knowledge-retrieval node bound to it, one export, two imports (same tenant, then
cross-tenant).

Source anchors this is testing live (api/services/rag_pipeline/rag_pipeline_dsl_service.py):
  - encrypt on export: _append_workflow_export_data, :681-684 (unconditional -- no
    DSL_EXPORT_ENCRYPT_DATASET_ID check in this file at all, unlike the app-DSL path)
  - decrypt on import: _create_or_update_pipeline, :547-556 (same walrus-comprehension-drops-
    silently shape as app_dsl_service.py:494-505)
  - the response model, RagPipelineImportResponse (controllers/console/datasets/rag_pipeline/
    rag_pipeline_import.py:51-57), has no `warnings` field at all -- unlike AppImportResponseModel,
    there is no channel to report into even if someone wanted to.

!! Point --base at a throwaway Dify stack, never a real one. These drivers create datasets, apps
   and workflow drafts in both tenants and leave them behind; the reproduction needs two tenants
   on one instance, which a stock install has no route to create. Nothing here deletes or
   overwrites, but nothing cleans up either.

Usage:
    python3 repro_kr_dataset_drop_rag_pipeline.py \
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from repro_kr_dataset_drop import Console, redact_body, redact_id  # noqa: E402

DSL_VERSION = "0.1.0"  # rag_pipeline_dsl_service.py:53 CURRENT_DSL_VERSION @ 5c6372d


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def index_node() -> dict[str, Any]:
    return {
        "id": "index",
        "type": "custom",
        "position": {"x": 0, "y": 0},
        "data": {
            "type": "knowledge-index",
            "title": "Knowledge Index",
            "chunk_structure": "text_model",
            "indexing_technique": "economy",
            "keyword_number": 10,
            "embedding_model": "",
            "embedding_model_provider": "",
            "retrieval_model": {
                "search_method": "keyword_search",
                "top_k": 2,
                "score_threshold": None,
                "score_threshold_enabled": False,
                "reranking_mode": "reranking_model",
                "reranking_enable": False,
                "reranking_model": None,
                "weights": None,
            },
        },
    }


def kr_node(dataset_ids: list[str]) -> dict[str, Any]:
    return {
        "id": "kr",
        "type": "custom",
        "position": {"x": 300, "y": 0},
        "data": {
            "type": "knowledge-retrieval",
            "title": "Knowledge Retrieval",
            "dataset_ids": dataset_ids,
            "retrieval_mode": "multiple",
            "query_variable_selector": ["start", "sys.query"],
            "multiple_retrieval_config": {
                "top_k": 2,
                "score_threshold": None,
                "reranking_mode": "reranking_model",
                "reranking_enable": False,
            },
        },
    }


def bootstrap_pipeline_dsl(pipeline_name: str) -> str:
    """Import-time DSL, deliberately WITHOUT a knowledge-retrieval node.

    rag_pipeline_dsl_service.decrypt_dataset_id has no plain-UUID short circuit (unlike
    app_dsl_service.decrypt_dataset_id, D2) -- it unconditionally AES-decrypts whatever string is
    in dataset_ids, on every import including the very first one. A hand-authored DSL with a
    plaintext dataset_id in a knowledge-retrieval node would therefore be dropped on its OWN
    bootstrap import, before there is anything to export. So: import a pipeline with only the
    knowledge-index node (required -- _create_or_update_pipeline raises "DSL is not valid, please
    check the Knowledge Index node." without one), then attach the knowledge-retrieval node
    afterward via the draft-sync endpoint, which writes the graph verbatim and never touches
    decrypt_dataset_id.
    """
    graph = {
        "nodes": [index_node()],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    doc = {
        "version": DSL_VERSION,
        "kind": "rag_pipeline",
        "rag_pipeline": {
            "name": pipeline_name,
            "icon": "\U0001f4d9",
            "icon_type": "emoji",
            "icon_background": "#FFEAD5",
            "description": "S4 repro: knowledge-index node only; kr node attached via draft-sync",
        },
        "workflow": {
            "graph": graph,
            "features": {},
            "environment_variables": [],
            "conversation_variables": [],
            "rag_pipeline_variables": [],
        },
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def import_pipeline(client: Console, yaml_text: str, note: str) -> dict[str, Any]:
    status, body = client.call(
        "POST", "/console/api/rag/pipelines/imports", {"mode": "yaml-content", "yaml_content": yaml_text}
    )
    print(f"  [{note}] import -> HTTP {status} status={body.get('status') if isinstance(body, dict) else body!r}")
    if status not in (200, 201) or not isinstance(body, dict):
        raise SystemExit(f"import failed ({note}): HTTP {status} {body}")
    if "warnings" in body:
        raise SystemExit(f"unexpected: RagPipelineImportResponse now has a warnings key -- re-check S4 anchors")
    return body


def get_draft(client: Console, pipeline_id: str) -> dict[str, Any]:
    status, body = client.call("GET", f"/console/api/rag/pipelines/{pipeline_id}/workflows/draft")
    if status != 200 or not isinstance(body, dict):
        raise SystemExit(f"cannot read draft pipeline workflow: HTTP {status} {body}")
    return body


def sync_draft_with_kr_node(client: Console, pipeline_id: str, retrieval_dataset_id: str) -> None:
    draft = get_draft(client, pipeline_id)
    graph = draft["graph"]
    graph["nodes"] = [n for n in graph["nodes"] if n.get("data", {}).get("type") != "knowledge-retrieval"]
    graph["nodes"].append(kr_node([retrieval_dataset_id]))
    graph.setdefault("edges", []).append(
        {"id": "e1", "source": "index", "target": "kr", "data": {"sourceType": "knowledge-index", "targetType": "knowledge-retrieval"}}
    )
    status, body = client.call(
        "POST",
        f"/console/api/rag/pipelines/{pipeline_id}/workflows/draft",
        {"graph": graph, "hash": draft["hash"], "environment_variables": [], "conversation_variables": [], "rag_pipeline_variables": []},
    )
    if status != 200:
        raise SystemExit(f"draft sync failed: HTTP {status} {body}")


def draft_kr_node(client: Console, pipeline_id: str) -> tuple[str, dict[str, Any]]:
    body = get_draft(client, pipeline_id)
    for node in body.get("graph", {}).get("nodes", []):
        if node.get("data", {}).get("type") == "knowledge-retrieval":
            return node["id"], node["data"]
    raise SystemExit("no knowledge-retrieval node in the imported draft graph")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--email-c", required=True)
    ap.add_argument("--password-c", required=True)
    ap.add_argument("--email-d", required=True)
    ap.add_argument("--password-d", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ev: dict[str, Any] = {"started_at": now(), "base": args.base, "dsl_version": DSL_VERSION, "steps": []}

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

    # --- the dataset the knowledge-retrieval node points at, in tenant C ---------------
    status, ds = c.call("POST", "/console/api/datasets", {"name": f"kbC-rp-{now()}", "indexing_technique": "economy"})
    if status not in (200, 201):
        raise SystemExit(f"dataset creation failed: HTTP {status} {ds}")
    retrieval_dataset_id = ds["id"]
    record("retrieval-dataset-created-in-C", dataset_id=redact_id(retrieval_dataset_id))

    bootstrap = bootstrap_pipeline_dsl("kr-rp-source")
    pipeline_c = import_pipeline(c, bootstrap, "C: create source pipeline (index node only)")
    sync_draft_with_kr_node(c, pipeline_c["pipeline_id"], retrieval_dataset_id)
    record("kr-node-attached-via-draft-sync", pipeline_id=redact_id(pipeline_c["pipeline_id"]))
    node_id_c, node_data_c = draft_kr_node(c, pipeline_c["pipeline_id"])
    record(
        "source-pipeline-in-C",
        pipeline_id=redact_id(pipeline_c["pipeline_id"]),
        ingestion_dataset_id=redact_id(pipeline_c.get("dataset_id", "")),
        kr_node_id=node_id_c,
        dataset_ids_bound=[redact_id(i) for i in node_data_c.get("dataset_ids", [])],
        matches_dataset=node_data_c.get("dataset_ids", []) == [retrieval_dataset_id],
    )
    if node_data_c.get("dataset_ids", []) != [retrieval_dataset_id]:
        raise SystemExit("the source pipeline did not actually bind the dataset -- nothing downstream is meaningful")

    # --- export once; reused byte-identical for control 1 and the experiment ----------
    status, exported = c.call(f"GET", f"/console/api/rag/pipelines/{pipeline_c['pipeline_id']}/exports?include_secret=false")
    if status != 200 or not isinstance(exported, dict):
        raise SystemExit(f"export failed: HTTP {status} {exported}")
    yaml_text = exported["data"]
    m = re.search(r"dataset_ids:\s*\n\s*-\s*(\S+)", yaml_text)
    ciphertext = m.group(1).strip("'\"") if m else None
    encrypted = bool(ciphertext) and ciphertext != retrieval_dataset_id
    record(
        "exported-from-C",
        yaml_sha256=sha256(yaml_text),
        yaml_bytes=len(yaml_text),
        dataset_ids_ciphertext_len=len(ciphertext) if ciphertext else None,
        dataset_ids_is_ciphertext=encrypted,
        note="ciphertext value itself deliberately not recorded: key is sha256(tenant_id)",
    )
    if not encrypted:
        raise SystemExit("exported dataset_ids is not ciphertext -- run is void")

    # --- control 1: byte-identical artifact, same tenant -------------------------------
    ctl1 = import_pipeline(c, yaml_text, "control 1: C -> C")
    _, ctl1_kr = draft_kr_node(c, ctl1["pipeline_id"])
    record(
        "control-1-same-tenant",
        artifact_sha256=sha256(yaml_text),
        import_status=ctl1.get("status"),
        response_redacted=redact_body(ctl1),
        dataset_ids=[redact_id(i) for i in ctl1_kr.get("dataset_ids", [])],
        preserved=ctl1_kr.get("dataset_ids", []) == [retrieval_dataset_id],
        shows="the exported artifact is intact and same-tenant import does not drop ids",
    )

    # --- the reproduction: byte-identical artifact, different tenant -------------------
    exp = import_pipeline(d, yaml_text, "experiment: C -> D")
    _, exp_kr = draft_kr_node(d, exp["pipeline_id"])
    record(
        "experiment-cross-tenant",
        artifact_sha256=sha256(yaml_text),
        artifact_identical_to_control_1=True,
        import_status=exp.get("status"),
        response_has_warnings_key="warnings" in exp,
        response_redacted=redact_body(exp),
        dataset_ids=exp_kr.get("dataset_ids", []),
        dropped=exp_kr.get("dataset_ids", []) == [],
        shows=(
            "RagPipelineImportResponse has no warnings field at all (confirmed by source: "
            "controllers/console/datasets/rag_pipeline/rag_pipeline_import.py:51-57), so this "
            "row also checks that the live response body genuinely carries no such key -- not "
            "just an empty list"
        ),
    )

    ev["finished_at"] = now()
    ev["verdict"] = {
        "dropped_without_report": (
            exp_kr.get("dataset_ids", []) == []
            and "warnings" not in exp
            and exp.get("status") == "completed"
        ),
        "control_1_preserved": ctl1_kr.get("dataset_ids", []) == [retrieval_dataset_id],
        "response_schema_has_no_warnings_field": "warnings" not in exp,
    }

    out = pathlib.Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"kr-dataset-drop-rag-pipeline-{ev['started_at'].replace(':', '')}.json"
    dest.write_text(json.dumps(ev, indent=2, ensure_ascii=False))
    print(f"\nverdict: {json.dumps(ev['verdict'])}\nevidence: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
