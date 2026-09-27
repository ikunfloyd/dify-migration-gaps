#!/usr/bin/env python3
"""
Reproduce: importing a workflow-app DSL into a different tenant silently drops the
knowledge-retrieval node's dataset_ids.

Runs entirely over the console HTTP API of a locally booted Dify v1.16.0 stack.
Writes a machine-readable evidence bundle; prints a human-readable trace.

Design notes that matter for the credibility of the output:

  * Two negative controls are mandatory, not optional. Control 1 (same tenant, byte-identical
    artifact) rules out "the export was already broken". Control 2 (the same artifact with the
    ciphertext replaced by the plaintext id — so NOT byte-identical, by construction) shows that a
    readable id survives into the same target tenant, which locates the drop at the branch taken
    when `decrypt_dataset_id` returns None, rather than at any existence or ownership check.
  * Evidence is the response body with UUID-shaped values redacted — not a reconstructed
    summary, and not raw either. Absence of a `warnings` key is recorded separately from an
    empty one, because `.get("warnings", [])` cannot tell them apart.
  * A screenshot of an empty node cannot distinguish a dropped id from a
    surviving-but-unresolvable one, which is why nothing here relies on the UI.
  * The AES key is sha256(tenant_id), so a bundle carrying both a tenant UUID and the ciphertext
    would let a reader recover the dataset UUID. No *complete* tenant UUID is written: `redact_id`
    emits an 8-hex prefix plus a hash prefix, leaving on the order of 88 bits unknown, which is
    what makes the recovery infeasible rather than merely inconvenient. It is not anonymisation --
    see `redact_id` -- and the prefix does travel in the same file as the ciphertext.

Usage:
    python3 repro_kr_dataset_drop.py \
        --base http://127.0.0.1:18091 \
        --email-a a@example.invalid --password-a ... \
        --email-b b@example.invalid --password-b ... \
        --out ../evidence
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.cookiejar
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

DSL_VERSION = "0.7.0"  # api/constants/dsl_version.py:1 @ 5c6372d


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def redact_id(value: str) -> str:
    """Tenant/dataset UUIDs appear only as a short prefix plus a hash.

    This is resistance to direct recovery, not anonymisation: 8 hex chars leak 32 bits and the
    hash prefix is a strong confirmer for anyone who already holds a candidate UUID. Treat these
    as pseudonyms tied to this run, not as safe-to-correlate identifiers.
    """
    return f"{value[:8]}…(sha256:{sha256(value)[:12]})"


def redact_body(obj: Any) -> Any:
    """Response body with every UUID-shaped value replaced. Structure and keys are untouched."""
    if isinstance(obj, dict):
        return {k: redact_body(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_body(v) for v in obj]
    if isinstance(obj, str):
        return UUID_RE.sub(lambda m: redact_id(m.group(0)), obj)
    return obj


class Console:
    """Cookie + CSRF console client. Dify 1.16 returns tokens as cookies, not in the body."""

    def __init__(self, base: str, label: str) -> None:
        self.base = base.rstrip("/")
        self.label = label
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def _csrf(self) -> str | None:
        for c in self.jar:
            if c.name == "csrf_token":
                return c.value
        return None

    def call(self, method: str, path: str, payload: Any = None) -> tuple[int, Any]:
        url = f"{self.base}{path}"
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        token = self._csrf()
        if token:
            req.add_header("X-CSRF-Token", token)
        try:
            with self.opener.open(req, timeout=120) as resp:
                raw = resp.read().decode()
                status = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            status = e.code
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, raw

    def login(self, email: str, password: str) -> None:
        # Password is base64-encoded, not encrypted: libs/encryption.py says so in its docstring.
        encoded = base64.b64encode(password.encode()).decode()
        status, body = self.call(
            "POST",
            "/console/api/login",
            {"email": email, "password": encoded, "language": "en-US", "remember_me": True},
        )
        if status != 200 or (isinstance(body, dict) and body.get("result") != "success"):
            raise SystemExit(f"[{self.label}] login failed: HTTP {status} {body}")

    def tenant_id(self) -> str:
        # /console/api/workspaces/current is POST-only in 1.16; the list endpoint marks the
        # active one with "current": true.
        status, body = self.call("GET", "/console/api/workspaces")
        if status != 200:
            raise SystemExit(f"[{self.label}] cannot list workspaces: HTTP {status} {body}")
        for ws in body.get("workspaces", []):
            if ws.get("current"):
                return ws["id"]
        raise SystemExit(f"[{self.label}] no current workspace in {body}")


def source_dsl(dataset_id: str, app_name: str) -> str:
    """Minimal workflow app whose only interesting content is one knowledge-retrieval node."""
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
                        "reranking_mode": "weighted_score",
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
        "version": DSL_VERSION,
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
    # Emitted as JSON: YAML is a superset of JSON, and this avoids depending on PyYAML.
    return json.dumps(doc, ensure_ascii=False, indent=2)


def import_app(client: Console, yaml_text: str, note: str) -> dict[str, Any]:
    status, body = client.call(
        "POST", "/console/api/apps/imports", {"mode": "yaml-content", "yaml_content": yaml_text}
    )
    print(f"  [{note}] import -> HTTP {status} status={body.get('status') if isinstance(body, dict) else body!r}")
    if status not in (200, 201) or not isinstance(body, dict):
        raise SystemExit(f"import failed ({note}): HTTP {status} {body}")
    return body


def draft_dataset_ids(client: Console, app_id: str) -> tuple[list[str], dict[str, Any]]:
    status, body = client.call("GET", f"/console/api/apps/{app_id}/workflows/draft")
    if status != 200 or not isinstance(body, dict):
        raise SystemExit(f"cannot read draft workflow: HTTP {status} {body}")
    for node in body.get("graph", {}).get("nodes", []):
        if node.get("data", {}).get("type") == "knowledge-retrieval":
            return list(node["data"].get("dataset_ids", [])), node["data"]
    raise SystemExit("no knowledge-retrieval node in the imported draft graph")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--email-a", required=True)
    ap.add_argument("--password-a", required=True)
    ap.add_argument("--email-b", required=True)
    ap.add_argument("--password-b", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ev: dict[str, Any] = {"started_at": now(), "base": args.base, "dsl_version": DSL_VERSION, "steps": []}

    def record(name: str, **fields: Any) -> None:
        ev["steps"].append({"step": name, "at": now(), **fields})
        print(f"[{now()}] {name}")

    a = Console(args.base, "A")
    b = Console(args.base, "B")
    a.login(args.email_a, args.password_a)
    b.login(args.email_b, args.password_b)
    ta, tb = a.tenant_id(), b.tenant_id()
    if ta == tb:
        raise SystemExit("tenant A and tenant B are the same tenant — the experiment is void")
    record("logged-in", tenant_a=redact_id(ta), tenant_b=redact_id(tb), tenants_differ=True)

    # --- source material in tenant A -------------------------------------------------
    status, ds = a.call("POST", "/console/api/datasets", {"name": f"kbA-{now()}", "indexing_technique": "economy"})
    if status not in (200, 201):
        raise SystemExit(f"dataset creation failed: HTTP {status} {ds}")
    dataset_id = ds["id"]
    record(
        "dataset-created-in-A",
        dataset_id=redact_id(dataset_id),
        indexing_technique=ds.get("indexing_technique"),
        embedding_model=ds.get("embedding_model"),
        note="economy indexing: no embedding-model credentials required",
    )

    src = source_dsl(dataset_id, "kr-source")
    app_a = import_app(a, src, "A: create source app")
    ids_a0, _ = draft_dataset_ids(a, app_a["app_id"])
    record(
        "source-app-in-A",
        app_id=redact_id(app_a["app_id"]),
        import_status=app_a.get("status"),
        dataset_ids_bound=[redact_id(i) for i in ids_a0],
        matches_dataset=ids_a0 == [dataset_id],
    )
    if ids_a0 != [dataset_id]:
        raise SystemExit("the source app did not actually bind the dataset — nothing downstream is meaningful")

    # --- export once. Control 1 and the experiment reuse these exact bytes; control 2
    # deliberately alters one substring and records its own hash. ---------------------
    status, exported = a.call("GET", f"/console/api/apps/{app_a['app_id']}/export")
    if status != 200:
        raise SystemExit(f"export failed: HTTP {status} {exported}")
    yaml_text = exported["data"]
    m = re.search(r"dataset_ids:\s*\n\s*-\s*(\S+)", yaml_text)
    ciphertext = m.group(1).strip("'\"") if m else None
    encrypted = bool(ciphertext) and ciphertext != dataset_id
    record(
        "exported-from-A",
        yaml_sha256=sha256(yaml_text),
        yaml_bytes=len(yaml_text),
        dataset_ids_ciphertext_len=len(ciphertext) if ciphertext else None,
        dataset_ids_is_ciphertext=encrypted,
        note="ciphertext value itself deliberately not recorded: key is sha256(tenant_id)",
    )
    if not encrypted:
        raise SystemExit(
            "exported dataset_ids is not ciphertext — DSL_EXPORT_ENCRYPT_DATASET_ID must be off; run is void"
        )

    # --- control 1: byte-identical artifact, same tenant -----------------------------
    ctl1 = import_app(a, yaml_text, "control 1: A -> A")
    ids_ctl1, _ = draft_dataset_ids(a, ctl1["app_id"])
    record(
        "control-1-same-tenant",
        artifact_sha256=sha256(yaml_text),
        import_status=ctl1.get("status"),
        warnings_key_present="warnings" in ctl1,
        warnings=ctl1.get("warnings"),
        response_redacted=redact_body(ctl1),
        dataset_ids=[redact_id(i) for i in ids_ctl1],
        preserved=ids_ctl1 == [dataset_id],
        shows="the exported artifact is intact and import does not drop ids in general",
    )

    # --- the reproduction: byte-identical artifact, different tenant -----------------
    exp = import_app(b, yaml_text, "experiment: A -> B")
    ids_exp, kr_data = draft_dataset_ids(b, exp["app_id"])
    record(
        "experiment-cross-tenant",
        artifact_sha256=sha256(yaml_text),
        artifact_identical_to_control_1=True,
        import_status=exp.get("status"),
        warnings_key_present="warnings" in exp,
        warnings=exp.get("warnings"),
        error=exp.get("error", ""),
        response_redacted=redact_body(exp),
        dataset_ids=ids_exp,
        dropped=ids_exp == [],
        # Derived from what this run actually observed, not asserted in advance: the same
        # driver is used against patched builds, where the reported status differs.
        shows=(
            "the reference is absent from the persisted graph; the import API response reported "
            f"{exp.get('status')!r} with "
            + ("a non-empty warnings list" if exp.get("warnings") else "no warnings")
            + ". Not checked: server logs, the web UI, or any other channel"
        ),
    )

    # --- control 2: same artifact with the ciphertext swapped for the plaintext id ----
    # NOT byte-identical by construction: exactly one substring differs.
    plain = yaml_text.replace(ciphertext, dataset_id)
    ctl2 = import_app(b, plain, "control 2: plaintext -> B")
    ids_ctl2, _ = draft_dataset_ids(b, ctl2["app_id"])
    # Does tenant B actually see this dataset? Asked, rather than assumed.
    _, b_datasets = b.call("GET", "/console/api/datasets?page=1&limit=100")
    b_visible = [d.get("id") for d in (b_datasets or {}).get("data", [])] if isinstance(b_datasets, dict) else []
    record(
        "control-2-plaintext-cross-tenant",
        artifact_sha256=sha256(plain),
        artifact_identical_to_experiment=False,
        artifact_diff="the single dataset_ids element: ciphertext replaced by the plaintext UUID",
        import_status=ctl2.get("status"),
        warnings_key_present="warnings" in ctl2,
        warnings=ctl2.get("warnings"),
        response_redacted=redact_body(ctl2),
        dataset_ids=[redact_id(i) for i in ids_ctl2],
        preserved=ids_ctl2 == [dataset_id],
        dataset_visible_to_target_tenant=dataset_id in b_visible,
        target_tenant_dataset_count=len(b_visible),
        shows=(
            "a readable id is written into the target tenant's graph even though that tenant's own "
            "dataset list does not contain it. So the element removed in the experiment was removed "
            "on the branch taken when decrypt_dataset_id returns None — not by an existence or "
            "ownership check, of which this path performs none"
        ),
    )

    ev["finished_at"] = now()
    ev["verdict"] = {
        "dropped_without_report": (
            ids_exp == []
            and not exp.get("warnings")
            and exp.get("status") == "completed"
        ),
        "control_1_preserved": ids_ctl1 == [dataset_id],
        "control_2_preserved": ids_ctl2 == [dataset_id],
    }

    out = pathlib.Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"kr-dataset-drop-{ev['started_at'].replace(':', '')}.json"
    dest.write_text(json.dumps(ev, indent=2, ensure_ascii=False))
    print(f"\nverdict: {json.dumps(ev['verdict'])}\nevidence: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
