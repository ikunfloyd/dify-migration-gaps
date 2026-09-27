#!/usr/bin/env python3
"""
Tighter control for D9: does a knowledge-retrieval node whose dataset actually HAS indexed
content take a different code path from one whose dataset_ids were dropped?

Why this script exists
----------------------
`repro_kr_runtime_execution.py` (2026-09-04) established that a node with empty `dataset_ids`
returns `status: SUCCEEDED, outputs: {"result": []}` rather than erroring. But its control used a
dataset with **zero indexed documents**, and `_get_available_datasets` filters those out with the
same `having(count > 0)` predicate that an empty `dataset_ids` list trips
(dataset_retrieval.py, D9). Control and experiment therefore ran the *same* short circuit, so the
run could not show that "reference dropped" and "real empty result" are distinguishable at all.
That limitation was recorded in docs/repro-log.md rather than glossed over; this script removes it.

Here the source tenant's dataset is given a real, indexed document first, so the control returns a
NON-EMPTY result through the full retrieval path. The cross-tenant import then returns an empty
one. Two different observed outcomes from two different paths -- which is what the earlier run
could not produce.

What this still does not claim: that an operator can *tell the two apart from the node result*.
A dropped reference and a genuine zero-hit search still both yield SUCCEEDED + result: []. This
script shows the control is capable of a non-empty result; it does not make the failure visible.

!! Point --base at a throwaway Dify stack, never a real one. These drivers create datasets, apps
   and workflow drafts in both tenants and leave them behind; the reproduction needs two tenants
   on one instance, which a stock install has no route to create. Nothing here deletes or
   overwrites, but nothing cleans up either.

Usage:
    python3 repro_kr_runtime_tighter_control.py \
        --base http://127.0.0.1:18092 \
        --email-c c@example.invalid --password-c ... \
        --email-d d@example.invalid --password-d ... \
        --out ../evidence
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from repro_kr_dataset_drop import Console, now, redact_body, sha256
from repro_kr_runtime_execution import draft_node, source_dsl_runnable

# Deterministic, self-authored corpus. Distinctive tokens so a keyword (economy) index has
# something unambiguous to match, and so a hit cannot be coincidental.
DOC_TEXT = (
    "Zarnathine Protocol Overview\n\n"
    "The zarnathine protocol is a fictitious reconciliation procedure invented solely for this\n"
    "reproduction. It has three phases: quillanth intake, morvex balancing, and final drenthal\n"
    "settlement. A quillanth intake record is considered valid when its drenthal checksum matches\n"
    "the morvex ledger entry for the same period.\n\n"
    "Operators performing a zarnathine reconciliation should verify the drenthal checksum before\n"
    "closing the period. If the morvex ledger disagrees, the quillanth intake must be replayed.\n"
)
QUERY = "What are the three phases of the zarnathine protocol?"


def upload_file(client: Console, filename: str, content: bytes) -> dict[str, Any]:
    """multipart/form-data upload -- Console.call only speaks JSON, so this is hand-rolled."""
    boundary = f"----reprobound{uuid.uuid4().hex}"
    ctype = mimetypes.guess_type(filename)[0] or "text/plain"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {ctype}\r\n\r\n".encode(),
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(
        f"{client.base}/console/api/files/upload?source=datasets", data=body, method="POST"
    )
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    token = client._csrf()
    if token:
        req.add_header("X-CSRF-Token", token)
    try:
        with client.opener.open(req, timeout=180) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"upload failed: HTTP {e.code} {e.read().decode()[:500]}")


def wait_indexed(client: Console, dataset_id: str, batch: str, timeout_s: int = 300) -> dict[str, Any]:
    """Poll until every document in the batch reaches indexing_status == completed."""
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        status, body = client.call(
            "GET", f"/console/api/datasets/{dataset_id}/batch/{batch}/indexing-status"
        )
        if status != 200:
            raise SystemExit(f"indexing-status failed: HTTP {status} {body}")
        last = body
        docs = body.get("data", []) if isinstance(body, dict) else []
        if docs and all(d.get("indexing_status") == "completed" for d in docs):
            return body
        if any(d.get("indexing_status") == "error" for d in docs):
            raise SystemExit(f"indexing errored: {json.dumps(body)[:800]}")
        time.sleep(3)
    raise SystemExit(f"indexing did not complete within {timeout_s}s; last={json.dumps(last)[:800]}")


def run_query(client: Console, app_id: str, node_id: str, query: str) -> tuple[int, dict[str, Any]]:
    """Single-step run with a caller-supplied query (the sibling script hardcodes its own)."""
    status, body = client.call(
        "POST",
        f"/console/api/apps/{app_id}/workflows/draft/nodes/{node_id}/run",
        {"inputs": {f"{node_id}.query": query}},
    )
    return status, body if isinstance(body, dict) else {"raw": body}


def import_app(client: Console, yaml_text: str, note: str) -> dict[str, Any]:
    status, body = client.call(
        "POST", "/console/api/apps/imports", {"mode": "yaml-content", "yaml_content": yaml_text}
    )
    print(f"  [{note}] import -> HTTP {status} status={body.get('status')!r}")
    if status not in (200, 201) or body.get("status") not in ("completed", "completed-with-warnings"):
        raise SystemExit(f"[{note}] import failed: HTTP {status} {body}")
    return body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--email-c", required=True)
    ap.add_argument("--password-c", required=True)
    ap.add_argument("--email-d", required=True)
    ap.add_argument("--password-d", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    steps: list[dict[str, Any]] = []

    def record(name: str, **fields: Any) -> None:
        steps.append({"step": name, "at": now(), **fields})
        print(f"[{now()}] {name}")

    c = Console(args.base, "C")
    d = Console(args.base, "D")
    c.login(args.email_c, args.password_c)
    d.login(args.email_d, args.password_d)
    record("logged-in")

    # --- source tenant: dataset WITH real indexed content -------------------------------------
    status, ds = c.call(
        "POST",
        "/console/api/datasets",
        {"name": f"kbTight-{now()}", "indexing_technique": "economy"},
    )
    if status not in (200, 201):
        raise SystemExit(f"dataset create failed: HTTP {status} {ds}")
    dataset_id = ds["id"]
    record("dataset-created-in-C", dataset=redact_body(ds))

    up = upload_file(c, "zarnathine.txt", DOC_TEXT.encode())
    record("file-uploaded", file=redact_body(up))

    status, doc = c.call(
        "POST",
        f"/console/api/datasets/{dataset_id}/documents",
        {
            "data_source": {
                "type": "upload_file",
                "info_list": {
                    "data_source_type": "upload_file",
                    "file_info_list": {"file_ids": [up["id"]]},
                },
            },
            "indexing_technique": "economy",
            "process_rule": {"mode": "automatic"},
            "doc_form": "text_model",
            "doc_language": "English",
        },
    )
    if status not in (200, 201):
        raise SystemExit(f"document create failed: HTTP {status} {doc}")
    batch = doc.get("batch")
    record("document-created", document=redact_body(doc))

    idx = wait_indexed(c, dataset_id, batch)
    record("document-indexed", indexing_status=redact_body(idx))

    # sanity: the dataset must now pass _get_available_datasets' having(count>0) filter
    # retrieval_model must be supplied IN FULL. Omitting it defaults to semantic search, which
    # 400s with "Default model not found for text-embedding" on a bed with no embedding model
    # configured; supplying it partially 400s the same way. Both of those silently produced the
    # zero-record result that an earlier version of this script narrated as a confirmation.
    status, hit = c.call(
        "POST",
        f"/console/api/datasets/{dataset_id}/hit-testing",
        {
            "query": QUERY,
            "retrieval_model": {
                "search_method": "keyword_search",
                "reranking_enable": False,
                "top_k": 2,
                "score_threshold_enabled": False,
            },
        },
    )
    hits = len((hit or {}).get("records", [])) if isinstance(hit, dict) else None
    record("hit-testing", http=status, records=hits, response=redact_body(hit))
    if status != 200 or not hits:
        raise SystemExit(f"hit-testing did not confirm the corpus is retrievable: HTTP {status}, {hits} records")

    # --- app in C, then cross-tenant import into D ---------------------------------------------
    src = source_dsl_runnable(dataset_id, f"tightctl-{now()}")
    app_c = import_app(c, src, "C: create source app")
    record("source-app-in-C", app=redact_body(app_c))

    status, exported = c.call("GET", f"/console/api/apps/{app_c['app_id']}/export")
    if status != 200:
        raise SystemExit(f"export failed: HTTP {status} {exported}")
    yaml_text = exported["data"] if isinstance(exported, dict) else exported
    record("exported-from-C", sha256=sha256(yaml_text))

    app_d = import_app(d, yaml_text, "experiment: C -> D")
    record("cross-tenant-import-into-D", app=redact_body(app_d))

    # --- single-step run both sides ------------------------------------------------------------
    node_c, data_c = draft_node(c, app_c["app_id"])
    node_d, data_d = draft_node(d, app_d["app_id"])

    ids_c = data_c.get("dataset_ids", [])
    ids_d = data_d.get("dataset_ids", [])
    record("persisted-dataset-ids", control_C=len(ids_c), experiment_D=len(ids_d))

    # The variable_mapping key is f"{node_id}.query" (knowledge_retrieval_node.py), and the query
    # has to actually match the indexed corpus -- run_node in the sibling script hardcodes an
    # unrelated question, which would make the control return [] for the wrong reason.
    st_c, run_c = run_query(c, app_c["app_id"], node_c, QUERY)
    record("control-run-in-C", http=st_c, response=redact_body(run_c))
    st_d, run_d = run_query(d, app_d["app_id"], node_d, QUERY)
    record("experiment-run-in-D", http=st_d, response=redact_body(run_d))

    def outcome(resp: dict[str, Any]) -> dict[str, Any]:
        data = (resp or {}).get("data", resp) or {}
        outputs = data.get("outputs") or {}
        result = outputs.get("result")
        return {
            "status": data.get("status"),
            "error": data.get("error"),
            "result_count": len(result) if isinstance(result, list) else None,
        }

    oc, od = outcome(run_c), outcome(run_d)

    verdict = {
        "control_dataset_had_indexed_content": True,
        "control_status": oc["status"],
        "control_result_count": oc["result_count"],
        "experiment_status": od["status"],
        "experiment_result_count": od["result_count"],
        "experiment_dataset_ids_dropped": len(ids_d) == 0 and len(ids_c) == 1,
        # the point of the tighter control: the control is capable of a NON-empty result,
        # so it is no longer running the same empty-short-circuit as the experiment
        "control_took_a_different_path": (oc["result_count"] or 0) > 0,
        # and the drop still surfaces as an ordinary success
        "experiment_succeeded_with_empty_result": od["status"] == "succeeded" and od["result_count"] == 0,
    }

    bundle = {
        "started_at": steps[0]["at"],
        "base": args.base,
        "purpose": "tighter control for D9 -- control dataset has indexed content",
        "query": QUERY,
        "steps": steps,
        "finished_at": now(),
        "verdict": verdict,
    }
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"kr-runtime-tighter-control-{now().replace(':', '').replace('-', '')}.json"
    path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
    print(f"\nverdict: {json.dumps(verdict)}")
    print(f"evidence: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
