# Upstream issue draft

Not filed. Draft only — review before anything gets posted to `langgenius/dify`. Every
sentence below traces to a **confirmed** or **confirmed + live** row in `docs/upstream-facts.md`;
if you add a claim while editing, check it against the ledger (or grade it there) before it ships.

Target: `langgenius/dify`, baseline commit `8387590ace4a094de812b7847fc6a4c3a27cd52b` (tag
`1.17.1`, the current release). Suggested labels: `bug`. Do not add a security label — see "Why
this is a bug report, not a vulnerability report" below.

**Filing decision (see notes at the bottom): file as TWO issues.** CODEOWNERS routes the two
carriers to different owners, so one combined issue lands on nobody in particular.

---

## Title

Cross-tenant DSL import silently drops `knowledge-retrieval` `dataset_ids` — no warning, in
either the app-DSL or the RAG-pipeline DSL path

## Body

### Summary

Exporting a workflow (or advanced-chat) app, or a RAG pipeline, that contains a
`knowledge-retrieval` node, then importing that DSL under a **different tenant/workspace**,
silently empties the node's `dataset_ids`. The import API reports success with no indication
anything was discarded:

- App-DSL path: `status: "completed"`, `warnings: []` (key present, explicitly empty).
- RAG-pipeline path: `status: "completed"`, and the response schema has **no `warnings` field at
  all** to be empty or non-empty.

At execution time it doesn't surface either — the node returns `SUCCEEDED` with `result: []`, the
same shape as a query that legitimately matched nothing.

This is not a report about the encryption itself — see "What this is not" below. It's that the
failure to resolve a reference isn't surfaced anywhere, even though the codebase already ships
structured reporting for *six other* classes of unresolvable reference
(`ImportStatus.COMPLETED_WITH_WARNINGS` / `DslImportWarning`), one of which is used by a sibling
path for this exact situation.

Verified on 1.17.1 (both reading the source and running it on a clean 1.17.1 stack), and
originally on 1.16.0. `git blame` puts the app-DSL drop at 2026-04-09 and the RAG-pipeline drop at
2025-09-18 — neither has been touched since.

### Root cause

`dataset_ids` on a `knowledge-retrieval` node is exported AES-encrypted with a key derived from
`sha256(source_tenant_id)`, and decrypted on import with `sha256(target_tenant_id)`. Across
tenants those keys differ, so decryption fails. Both affected import paths handle that failure the
same way — a list comprehension that silently filters out anything that fails to decrypt, with no
`else` branch, nothing appended to any warnings list, and no log line:

**App-DSL** (`api/services/app_dsl_service.py`):
```python
# :653-664 (loop :653, node-type test :654, comprehension :656-664)
node["data"]["dataset_ids"] = [
    decrypted_id
    for dataset_id in dataset_ids
    if (
        decrypted_id := self.decrypt_dataset_id(
            encrypted_data=dataset_id, tenant_id=app.tenant_id
        )
    )
]
```
Key derivation: `:1089-1092` (`sha256(tenant_id)`, IV = `key[:16]`). The mutated graph is what gets
persisted: `:668-680`. Gated by `DSL_EXPORT_ENCRYPT_DATASET_ID`, which defaults `true`
(`api/configs/feature/__init__.py:1293`).

Worth noting how close the fix already is: 24 lines below that comprehension, in the same `case`
branch, `:688` does `self._warnings.extend(warnings)` for agent-package warnings. The list, the
promotion helper (`:879-882`) and the response field (`:93`) are all right there.

**RAG-pipeline DSL** (`api/services/rag_pipeline/rag_pipeline_dsl_service.py`) — an independent
implementation, structurally identical drop:
```python
# _create_or_update_pipeline (:537), drop at :570-582
node["data"]["dataset_ids"] = [
    decrypted_id
    for dataset_id in dataset_ids
    if (
        decrypted_id := self.decrypt_dataset_id(
            encrypted_data=dataset_id,
            tenant_id=account.current_tenant_id,
        )
    )
]
```
Three differences from the app-DSL path, all making this one harder to notice or turn off:
- Export encryption (`_append_workflow_export_data`, `:705-710`) is **unconditional** — no
  `DSL_EXPORT_ENCRYPT_DATASET_ID` check anywhere in this file, so there's no flag to disable it
  for future exports.
- Its `decrypt_dataset_id` (`:936-945`) has neither a plain-UUID short circuit nor post-decrypt
  UUID validation — it returns `pt.decode()` raw at `:943`. So a hand-authored DSL with a plaintext
  dataset_id is dropped on its very first import, and conversely a non-empty garbage decode would
  be persisted where the app-DSL path would reject it.
- The import response model, `RagPipelineImportResponse`
  (`api/controllers/console/datasets/rag_pipeline/rag_pipeline_import.py:51-58`), has no
  `warnings` field — and its base sets `extra="ignore"` (`api/fields/base.py:9`), so one cannot
  arrive by accident. There is no `_warnings` list and no `_status_with_warnings` in that service
  at all. (`COMPLETED_WITH_WARNINGS` *is* reachable there, but only via shared version-skew
  checking at `api/services/dsl_version.py:19` — never for a lost reference.)

**At execution time**, the empty `dataset_ids` doesn't surface as an error either:
```python
# api/core/rag/retrieval/dataset_retrieval.py:158-160
available_datasets_ids = [i.id for i in available_datasets]
if not available_datasets_ids:
    return []
```
The node's `_run` (`.../knowledge_retrieval/knowledge_retrieval_node.py:143-145`) treats that as a
normal successful result: `status: SUCCEEDED`, `outputs: {"result": []}`.

### The reporting channel already exists and is already used — six times

`DslImportWarning`'s docstring is *"Portable DSL reference that could not be restored in the
target workspace"* (`api/services/entities/dsl_entities.py:31-37`). Every construction site in the
repo is in `api/services/agent/dsl_service.py`:

| line | code | covers |
|---|---|---|
| `:471` | `agent_workspace_skill_unresolved` | workspace skill not findable in the target tenant |
| `:606` | `agent_{kind}_omitted` | omitted skill or file asset |
| `:617` | `agent_tool_authorization_required` | tool needing authorization |
| `:633` | `agent_secret_required` | secret reference from soul / CLI-tool env |
| `:642` | `agent_human_contact_unresolved` | human contact needing reselection |
| `:657` | `agent_knowledge_unresolved` | agent soul dataset id absent from the target tenant |

That last one is the same situation as this report, handled: it substitutes a
`portable_ref("missing-dataset", ...)` sentinel (`:655`) and warns. The knowledge-retrieval graph
node is the one class of unresolvable reference with no equivalent.

Existing tests pin the encrypt/decrypt branches on both carriers
(`api/tests/test_containers_integration_tests/services/test_app_dsl_service.py:1625-1665`;
`api/tests/unit_tests/services/rag_pipeline/test_rag_pipeline_dsl_service.py:207-209, :941`).
None covers the silence of the import-side drop.

### Why this is worth fixing beyond the manual-export case

`api/services/data_migration/` — the built-in cross-tenant bulk mover, reachable from
`flask` (`api/commands/data_migration.py:406`) — delegates to the app-DSL carrier in both
directions, so it inherits this drop. It also **discards the warning channel**:
`import_service.py:345` accepts `COMPLETED_WITH_WARNINGS` as success and never reads the
`warnings` list, and its report's `ResourceType` (`data_migration/entities.py:30-35`) has no slot
for a lost reference. So wiring up the app-DSL branch alone would still leave this path silent.

(Stated from reading the delegation, not from running it — I have not driven a reproduction
through the migration CLI.)

The documented migration workflow tells operators to rely on the import report for follow-up
(`docs/cross-env-app-migration/README.md:242`).

### Steps to reproduce

Requires two tenants on one instance (stock env has no such route — see "Reproduction notes").

1. In tenant A: create a dataset (`economy` indexing avoids embedding-model setup), create a
   workflow app with a single `knowledge-retrieval` node bound to it (`retrieval_mode: multiple`).
2. Export the app (`GET /console/api/apps/{app_id}/export`). Confirm `dataset_ids` in the
   exported YAML is ciphertext, not the plain dataset UUID.
3. Import the byte-identical YAML into tenant A again (control) — `dataset_ids` survives.
4. Import the same byte-identical YAML into tenant B — `dataset_ids` comes back `[]`. Response:
   `status: "completed"`, `warnings: []` (key present).
5. For the RAG-pipeline path: repeat with a pipeline (`knowledge-index` node + `knowledge-retrieval`
   node bound to an existing dataset) via `POST /console/api/rag/pipelines/imports`. Same result,
   and the response body has no `warnings` key to check.

Scripted reproduction (three drivers, one per path plus a runtime check), raw evidence bundles
(UUIDs redacted to a prefix + hash), and the per-fact source ledger are here:
`https://github.com/ikunfloyd/dify-migration-gaps`. The drivers run unmodified against
1.17.1.

### What this is not

- **Not** a request to weaken the per-tenant key derivation — that's a deliberate isolation
  boundary and this report doesn't touch it.
- **Not** a claim that import should fail, or that the reference should be auto-restored or
  existence-checked. The ask is narrower: when a non-empty input element is silently omitted,
  report it — the way the codebase already does in six other places.
- **Not** every DSL carrier. Chat / agent-chat / completion apps carry `dataset_ids` in
  `model_config` unencrypted and unfiltered — no drop. The Agent-v2 knowledge path is not silent.
  The snippet path neither encrypts nor filters (`snippet_dsl_service.py:593-599`) — it preserves
  the foreign id verbatim instead. A repo-wide sweep confirms there are exactly **two**
  silent-drop implementations, not more.
- **Not** a claim about the node erroring at runtime — it doesn't; flagging that only because a
  natural first guess is that a missing reference would raise.

### Reproduction notes (for anyone trying to repeat this)

Stock `docker/` compose ships `ALLOW_REGISTER` and `ALLOW_CREATE_WORKSPACE` both `false`
(`shared.env.example:28-29`), and no console route creates a second workspace, so a second tenant
needs `flask create-tenant` with both flags enabled — and, at 1.17.1, an explicit `--language`,
or the command aborts on its language prompt in a non-TTY shell. Neither flag touches the import
path under test (`api/services/system_feature_service.py:51, :106, :149` are the only readers).

### Suggested direction (not a PR)

On the app-DSL path the `DslImportWarning` / `COMPLETED_WITH_WARNINGS` machinery is already in the
same file and already used 24 lines away; wiring the decrypt-failure branch into it looks like the
natural fix. The RAG-pipeline path needs the `warnings` field added to its response schema first,
plus a `_warnings` list and `_status_with_warnings` in the service. Happy to open a PR for the
app-DSL side.

---

## Notes for whoever posts this (not part of the issue body)

- **File as two issues.** This was previously an open judgement call; at 1.17.1 it has a factual
  answer. `api/services/rag_pipeline/rag_pipeline_dsl_service.py` matches
  `/api/services/rag_pipeline/ @JohnJyong` (`.github/CODEOWNERS:60`), while
  `api/services/app_dsl_service.py` matches only `*` (`:7`) and `/api/` (`:37`). One combined
  issue routes to nobody in particular; two route to different owners. Cross-link them.
- **Consider leading with a PR on the app-DSL side rather than an issue.** The change is small and
  the machinery is already present, so it needs review rather than triage — and it sidesteps the
  biggest practical obstacle, which is that a maintainer cannot reproduce this in three minutes
  (two tenants, two non-default flags). A PR can carry a test; the existing test file already
  covers all four encrypt/decrypt branches and is the obvious home for one covering the silence.
- The evidence-repo link assumes `ikunfloyd/dify-migration-gaps` is pushed and public.
  Local commits are ahead of `origin/main` — push first, or the linked ledger will be stale
  relative to what the issue claims.
- Kill-date clock (see `docs/repro-log.md`, top): starts on the day this is actually opened.
