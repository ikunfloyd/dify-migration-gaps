# Fact ledger

Every claim this repository makes, graded. Nothing gets quoted publicly unless it appears here as
**confirmed**.

Baseline: `langgenius/dify` @ `5c6372d2f76d240265b92fd27c16bc772ffcb107` (tag 1.16.0), read
2026-08-21. Line numbers below were opened and read at that commit.

Grades: **confirmed** = read it, says what is claimed · **corrected** = the fact holds but the
citation or wording was wrong, corrected value given · **live** = established by running the
reproduction, not by reading source · **inference** = derived, not directly read · **unverified** =
not settled.

---

## 1. The defect

| # | Fact | Grade | Anchor |
|---|---|---|---|
| D1 | On import, for each node with `data.type == KNOWLEDGE_RETRIEVAL`, `dataset_ids` is rebuilt by a walrus comprehension that keeps only ids for which `decrypt_dataset_id(...)` is truthy. No `else`, no append to warnings, no log. | confirmed | `api/services/app_dsl_service.py:496-505` |
| D2 | `decrypt_dataset_id` returns `None` at two exits: decrypted text is not a UUID, and a bare `except Exception` with no logging. It performs **no database access**; `tenant_id` feeds only the AES key. | corrected | returns at `:927` and `:930` (bare `except` at `:928`); signature at `:908`; plain-UUID short circuit at `:911-912` |
| D3 | The AES key is `sha256(tenant_id)`, IV = `key[:16]`. No instance secret, no salt: the tenant UUID is the sole input. | corrected | `api/services/app_dsl_service.py:890-893` (sha256 on `:893`); encrypt IV `:902`, decrypt IV `:917`. **Not** `:470-473` — that is the `match app_mode:` block |
| D4 | The filtered graph is what gets persisted (`sync_draft_workflow`). | confirmed | `api/services/app_dsl_service.py:509-521` |
| D5 | The silence is structural: `self._warnings` is never appended on this branch, and `_status_with_warnings` only promotes to `COMPLETED_WITH_WARNINGS` when that list is non-empty. | confirmed | `:496-505` (no append), `:529` and `:574` (the only `extend` calls), `:708-711` |
| D6 | Export encrypts with the **source** tenant's key; import decrypts with the **target** tenant's key. Tenant-UUID equality is the only variable deciding success. | confirmed | export `:670-675`, import `:439-444` |
| D7 | `DSL_EXPORT_ENCRYPT_DATASET_ID` defaults to `True`, and ships as `true`. | confirmed | `api/configs/feature/__init__.py:1210-1213`; `docker/envs/core-services/shared.env.example:240` |

## 2. Why this is a reporting gap and not a design disagreement

| # | Fact | Grade | Anchor |
|---|---|---|---|
| R1 | Upstream already ships the reporting channel: `ImportStatus.COMPLETED_WITH_WARNINGS` and `DslImportWarning`, whose docstring is *"Portable DSL reference that could not be restored in the target workspace."* | confirmed | `api/services/entities/dsl_entities.py:16, 21-22` |
| R2 | The sibling Agent path, facing the same situation, substitutes a `portable_ref("missing-dataset", ...)` sentinel **and** emits `agent_knowledge_unresolved`. | corrected | substitution `api/services/agent/dsl_service.py:536`; guarded block `:530-544` |
| R3 | The machinery is already wired **in the same file** as the defect — the KR branch is the one that does not use it. | confirmed | `app_dsl_service.py:529`, `:708-711` |
| R4 | Upstream has tests pinning all four encrypt/decrypt branches. The mechanism is deliberate and known. What no test covers is the **silence** of the import-side drop. | confirmed | `api/tests/test_containers_integration_tests/services/test_app_dsl_service.py:1612-1652` |
| R5 | The documented migration workflow tells operators to rely on the import report for follow-up items. | confirmed | `docs/cross-env-app-migration/README.md:213, 238, 242` |

## 3. Scope — what this is *not*

Stated as sharply as the code allows, because three of the four carriers behave differently.

| # | Fact | Grade | Anchor |
|---|---|---|---|
| S1 | Chat / agent-chat / completion apps carry dataset ids in `model_config` and are exported and imported **verbatim, unencrypted, unfiltered**. No drop occurs there. | confirmed | export `app_dsl_service.py:718-735`, import `:538-556` |
| S2 | Agent-v2 knowledge is **not** silent: it warns, and can hard-fail at publish. | confirmed | `agent/dsl_service.py:530-544`; `api/core/workflow/nodes/agent_v2/validators.py:387-404` (message at `:401-404`) |
| S3 | Snippet DSL dataset-id encryption is an explicit no-op ("For now, just return the dataset_id as-is"). | confirmed | `api/services/snippet_dsl_service.py:545, 549` |
| S4 | RAG-pipeline DSL is a separate implementation keyed on `account.current_tenant_id`. | confirmed | `api/services/rag_pipeline/rag_pipeline_dsl_service.py:875, 883` |
| S5 | If a target instance holds a tenant with the **same** UUID (a DB clone or restore), decryption succeeds, no existence check runs, and the id is preserved as a **dangling** reference — the opposite symptom. | inference from D2+D6 | — |

## 4. Reproduction environment — deviations from stock

Disclosed because without them the run is not reproducible.

| # | Fact | Grade | Anchor |
|---|---|---|---|
| E1 | A stock 1.16 stack **cannot** create a second tenant. `ALLOW_REGISTER` and `ALLOW_CREATE_WORKSPACE` both default `False` and appear in no shipped env example. | confirmed | `api/configs/feature/__init__.py:1457-1464` |
| E2 | `flask create-tenant` needs **both** flags: `create_account` raises `AccountNotFound` without the first, `create_owner_tenant_if_not_exist` raises `WorkSpaceNotAllowedCreateError` without the second. | confirmed + live | `api/commands/account.py:89-145`; `api/services/account_service.py:438-441`, `:1328-1333`. Observed live: with only `ALLOW_CREATE_WORKSPACE=true` the command still failed with `AccountNotFound` |
| E3 | There is no console POST that creates a workspace. | confirmed | all routes in `api/controllers/console/workspace/workspace.py` read; `/console/api/setup` is one-shot at `setup.py:81-84` |
| E4 | Neither flag touches the import code path under test. | inference | both are read only via `FeatureService.get_system_features()` in the account/registration path |
| E5 | Console login takes the password **base64-encoded**, not encrypted — upstream's own docstring says so. Auth is cookie-based; every subsequent call needs `X-CSRF-Token`. | confirmed | `api/libs/encryption.py:1-9`; `controllers/console/wraps.py:564-580` |
| E6 | `/console/api/workspaces/current` is POST-only; the list endpoint marks the active workspace with `"current": true`. | live | observed: `GET /console/api/workspaces/current` → HTTP 405 |

## 5. Do-not-claim list

Statements that are **not** supported. None of these may appear in an issue, in this log, or in
anything spoken.

1. ~~"`_generate_aes_key` is at `app_dsl_service.py:470-473`"~~ — it is `890-893`. `470-473` is the
   `match app_mode:` block.
2. ~~"Cross-environment DSL import drops dataset references"~~ — too broad, and false for three of
   four carriers (S1, S3, S4). It is specifically: workflow / advanced-chat apps,
   `knowledge-retrieval` nodes, `DSL_EXPORT_ENCRYPT_DATASET_ID=true`.
3. ~~"Dify silently loses knowledge-base links on import"~~ — the Agent path is not silent (S2). A
   log containing `agent_knowledge_unresolved` disproves the word.
4. ~~"The dataset isn't in tenant B, so it was removed"~~ — no such mechanism. `decrypt_dataset_id`
   performs zero database access. Proven live by control 2: a *readable* id survives into a tenant
   that does not own it.
5. ~~"This reproduces on a default stack"~~ — it needs two non-default flags (E1).
6. ~~Screenshots as evidence~~ — the canvas renders `null` for a dropped id, a surviving
   unresolvable id, and a genuinely missing dataset alike
   (`web/app/components/workflow/nodes/knowledge-retrieval/node.tsx:26`), and runtime retrieval is
   tenant-filtered regardless (`api/core/rag/retrieval/dataset_retrieval.py:1929`). Raw JSON only.
7. ~~"Turning the flag off fixes it"~~ — it changes future exports only. `decrypt_dataset_id` never
   reads the flag; already-exported DSLs still drop.
8. ~~"Upstream hasn't thought about this"~~ — they have (R4). The untested part is the silence.
9. ~~"A RAG maintainer owns this"~~ — CODEOWNERS routes by path; `app_dsl_service.py` matches only
   `*` (`.github/CODEOWNERS:7`) and `/api/` (`:34`). No RAG-owned pattern reaches it.
10. ~~"There is no CLA"~~ — only "nothing in this checkout" is verifiable offline; an org-level
    GitHub App leaves no in-repo trace. Note also `LICENSE:13-16`.
11. ~~"The frontend surfaces these warnings everywhere"~~ — only two call sites render the
    structured payload; four other surfaces show a static string.
12. ~~"The node errors at runtime"~~ — **unverified**. Not tested; execution behaviour with an empty
    `dataset_ids` was never exercised.
13. ~~"iteration/loop/llm nodes were moved to graphon"~~ — verified only that those directories are
    absent and that `graphon==0.6.0` is pinned (`api/pyproject.toml:48`). "Moved there" is inference.

## 6. Corrections carried in from an earlier draft

Recorded so the mistakes are not silently re-introduced.

- `.github/CODEOWNERS` RAG block is lines **61-97** (37 patterns incl. one at `:149`), not 62-93.
- Only CODEOWNERS `:57-59` are stale; `:56` (`nodes/agent/`) is live — that directory exists.
- `app_dsl_service.py:757-833` is the whole function; the `match` is `:767-829`, with `case _: pass`
  at `:827`. `"trigger-plugin"` is not an enum member but a constant at
  `api/core/trigger/constants.py:5`.
- The broad `except Exception` spans `:765-829` with the handler at `:830-831`.
