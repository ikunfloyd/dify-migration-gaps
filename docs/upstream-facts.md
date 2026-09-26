# Fact ledger

Every claim this repository makes, graded. Nothing gets quoted publicly unless it appears here as
**confirmed**.

Baseline: `langgenius/dify` @ `8387590ace4a094de812b7847fc6a4c3a27cd52b` (tag **1.17.1**, released
2026-09-10), re-verified 2026-09-18. Line numbers below were opened and read at that commit.

The analysis was originally written against 1.16.0 (`5c6372d`, 2026-08-21). It was re-anchored to
1.17.1 — **1501 commits later** — on 2026-09-18: every fact relocated and re-graded, and the three
reproductions re-run on a fresh 1.17.1 stack. **Nothing was refuted.** 43 facts re-graded: 31 hold
with anchors moved or unchanged, 8 needed rewording, 4 changed, 0 overturned. The old anchors and
the full per-fact comparison are in [`baselines/1.17.1/anchor-map.md`](../baselines/1.17.1/anchor-map.md);
they are kept there rather than here so this file states one baseline, not two.

Grades: **confirmed** = read it, says what is claimed · **corrected** = the fact holds but the
citation or wording was wrong, corrected value given · **live** = established by running the
reproduction, not by reading source · **inference** = derived, not directly read · **unverified** =
not settled.

---

## 1. The defect

| # | Fact | Grade | Anchor |
|---|---|---|---|
| D1 | On import, for each node with `data.type == KNOWLEDGE_RETRIEVAL`, `dataset_ids` is rebuilt by a walrus comprehension that keeps only ids for which `decrypt_dataset_id(...)` is truthy. No `else`, no append to warnings, no log. | confirmed + live | `api/services/app_dsl_service.py:653-664` — loop `:653`, type test `:654`, comprehension `:656-664`. Byte-identical to 1.16.0, shifted +159 lines |
| D2 | `decrypt_dataset_id` returns `None` at two exits: decrypted text is not a UUID, and a bare `except Exception` with no logging. It performs **no database access**; `tenant_id` feeds only the AES key. | confirmed | signature `:1107`; plain-UUID short circuit `:1110-1111`; returns at `:1126` and `:1129` (bare `except` at `:1127`). The whole body is hashlib/AES/base64/uuid — no session, no query |
| D3 | The AES key is `sha256(tenant_id)`, IV = `key[:16]`. No instance secret, no salt: the tenant UUID is the sole input. | confirmed | `api/services/app_dsl_service.py:1089-1092` (sha256 on `:1092`); encrypt IV `:1101`, decrypt IV `:1116` |
| D4 | The filtered graph is what gets persisted (`sync_draft_workflow`). | confirmed | `api/services/app_dsl_service.py:668-680`. `graph_for_sync` (`:668`) derives from the same `graph` object the comprehension mutated in place |
| D5 | The silence is structural: `self._warnings` is never appended on this branch, and `_status_with_warnings` only promotes to `COMPLETED_WITH_WARNINGS` when that list is non-empty. | confirmed | `:653-664` (no append), `:688` and `:739` (the only two `self._warnings.extend` calls in the file), `:879-882`. Note `:688` sits **24 lines below** the drop, inside the same `case` branch — agent-package warnings are collected there; the dataset_ids discard is not |
| D6 | Export encrypts with the **source** tenant's key; import decrypts with the **target** tenant's key. Within this call, tenant-UUID equality is what decides whether decryption succeeds. | confirmed | export `:841-846`; import passes `tenant_id=app.tenant_id` at `:661`. `target_tenant_id` is resolved at `:564` and assigned to a newly created app at `:598`; an overwrite import reaches this function only via `_load_app_for_overwrite`, which selects under `App.tenant_id == account.current_tenant_id`, so either way the key is the target workspace's |
| D7 | `DSL_EXPORT_ENCRYPT_DATASET_ID` defaults to `True`, and ships as `true`. It is read at **exactly one** runtime site repo-wide — inside the export helper. The import path never reads it. | confirmed | declaration `api/configs/feature/__init__.py:1293`; ships `docker/envs/core-services/shared.env.example:273`, `api/.env.example:785`; sole runtime read `app_dsl_service.py:1097-1098`. This is the source-level proof for do-not-claim #7 |
| D8 | At execution time, an empty `dataset_ids` does not raise. `DatasetRetrieval.knowledge_retrieval` computes `available_datasets_ids` and returns `[]` immediately if that list is empty — before the query or attachments are inspected. The node's `_run` treats this as a normal result: `status: SUCCEEDED`, `outputs: {"result": []}`. Nothing distinguishes it from a legitimate zero-hit search. | confirmed + live | short circuit `api/core/rag/retrieval/dataset_retrieval.py:158-160`; node success path `api/core/workflow/nodes/knowledge_retrieval/knowledge_retrieval_node.py:143-145`; live: `evidence/kr-runtime-execution-2026-09-04T084155Z.json` (1.16.0), `baselines/1.17.1/evidence/kr-runtime-execution-2026-09-18T120601Z.json` (1.17.1) |
| D9 | `_get_available_datasets` filters to datasets with at least one `completed`/`enabled`/non-archived document (`having(count > 0)`) unless the dataset is `provider == "external"`. A dataset with zero indexed documents fails this filter exactly like an empty `dataset_ids` does — both take the D8 short circuit. **The 2026-09-04 control tripped this**, so it ran the same path as the experiment. A tighter control run on 2026-09-18 indexed real content into the source dataset first: the control then returned **2 records** through the full retrieval path while the cross-tenant experiment returned 0. The two situations are therefore demonstrably different code paths. What remains indistinguishable is narrower, and is the claim that matters: **a dropped reference and a legitimate zero-hit search** both read `SUCCEEDED` + `result: []`. A populated dataset is distinguishable — it returns records, as the tighter control did. | confirmed + live | filter `api/core/rag/retrieval/dataset_retrieval.py:2064-2085` (`having` at `:2075`, external escape at `:2085`); live: `scripts/repro_kr_runtime_tighter_control.py`, `baselines/1.17.1/evidence/kr-runtime-tighter-control-20260918T120921Z.json` |

## 2. Why this is a reporting gap and not a design disagreement

| # | Fact | Grade | Anchor |
|---|---|---|---|
| R1 | Upstream already ships the reporting channel: `ImportStatus.COMPLETED_WITH_WARNINGS` and `DslImportWarning`, whose docstring is *"Portable DSL reference that could not be restored in the target workspace."* | confirmed | `api/services/entities/dsl_entities.py:16` (enum member), `:31-37` (class; docstring at `:32`) |
| R2 | Upstream has built structured reporting for **six** classes of unresolvable reference, all in one file — and the knowledge-retrieval node's `dataset_ids` is not among them. The sibling Agent path, facing the same situation, substitutes a `portable_ref("missing-dataset", ...)` sentinel **and** emits `agent_knowledge_unresolved`. | confirmed | all six construction sites are in `api/services/agent/dsl_service.py`: `:471` `agent_workspace_skill_unresolved`, `:606` `agent_{kind}_omitted`, `:617` `agent_tool_authorization_required`, `:633` `agent_secret_required`, `:642` `agent_human_contact_unresolved`, `:657` `agent_knowledge_unresolved`. Substitution at `:655`; guarded block `:649-663`. No other file in the repo constructs one |
| R3 | The machinery is already wired **in the same file** as the defect — the KR branch is the one that does not use it. | confirmed | `app_dsl_service.py:93` (`Import.warnings`), `:113`/`:117` (`self._warnings`), `:688` and `:739` (extends), `:879-882` (promotion), returned at `:363-371` and `:452-457` |
| R4 | Both carriers have tests pinning their encrypt/decrypt branches. The mechanism is deliberate and known. What no test covers is the **silence** of the import-side drop, on either path. | confirmed | app-DSL: `api/tests/test_containers_integration_tests/services/test_app_dsl_service.py:1625-1665` (config gate, plain UUID, invalid data, non-UUID plaintext). RAG-pipeline: `api/tests/unit_tests/services/rag_pipeline/test_rag_pipeline_dsl_service.py:207-209`, `:941` |
| R5 | The documented migration workflow tells operators to rely on the import report for follow-up items. | confirmed | `docs/cross-env-app-migration/README.md:242` ("Items marked `dependency-only`, `skipped`, or `unresolved` usually need manual follow-up"), `:283` |
| R6 | Upstream ships its **own cross-tenant bulk mover**, which delegates to the app-DSL carrier in both directions and adds a **second layer of silence**: it accepts `COMPLETED_WITH_WARNINGS` as success and never reads the `warnings` list. Fixing the app-DSL branch alone would not make the loss visible on this path. Its report model has no slot for it either — `ResourceType` is WORKFLOW / API_TOOL / WORKFLOW_TOOL / MCP_TOOL / DEPENDENCY. | confirmed | `api/services/data_migration/export_service.py:137-139`; `import_service.py:326-347`, discard at `:345`; CLI at `api/commands/data_migration.py:406`; `api/services/data_migration/entities.py:30-35`. Not live-tested — see do-not-claim #14 |
| R7 | Exactly **three** sites set `COMPLETED_WITH_WARNINGS`. One of them — version-skew promotion, extracted since 1.16.0 into a helper shared by all three importers — is the **only** route by which a RAG-pipeline import can ever return that status, and it says nothing about references. | confirmed | `app_dsl_service.py:879-882`; `snippet_dsl_service.py:611-613`; `api/services/dsl_version.py:19`, called from `app_dsl_service.py:272`, `snippet_dsl_service.py:56`/`:187`, `rag_pipeline_dsl_service.py:194` |

## 3. Scope — what this is *not*

Stated as sharply as the code allows, because the sibling carriers do not behave the same way.
A repo-wide sweep at 1.17.1 confirmed the boundary: `grep -rn 'pad(\|unpad('` over non-test `api/`
returns exactly four DSL hits across two files, and `grep -rn '"dataset_ids"\] ='` exactly five
assignment sites across three. **There are exactly two silent-drop implementations. There is no third.**

| # | Fact | Grade | Anchor |
|---|---|---|---|
| S1 | Chat / agent-chat / completion apps carry dataset ids in `model_config` and are exported and imported **verbatim, unencrypted, unfiltered** — the export strips only `credential_id`. No drop occurs there. | confirmed | export `app_dsl_service.py:885-906` (`_append_model_config_export_data`; `credential_id` strip `:903-904`, assignment `:906`), import `:699-722` (`from_model_config_dict` at `:711`) |
| S2 | Agent-v2 knowledge is **not** silent: it warns, and can hard-fail at publish. | confirmed | `agent/dsl_service.py:649-663`; `api/core/workflow/nodes/agent_v2/validators.py:412-428` (message at `:427`) |
| S3 | Snippet DSL dataset-id encryption is an explicit no-op ("For now, just return the dataset_id as-is"), **and there is no import-side decrypt at all**. So the snippet path does not drop — it preserves a foreign-tenant UUID verbatim, producing a dangling reference (the S5 symptom) rather than an empty list. Its import response *can* carry warnings and the channel is wired; nothing populates it for dataset ids because nothing filters them. | confirmed | no-op `api/services/snippet_dsl_service.py:593-599` (comment `:597`, return `:599`); export call `:567-569`; warnings wiring `:75`, `:478`, `:611-613`; response model `api/controllers/console/workspace/snippets.py:57-64` |
| S4 | RAG-pipeline DSL is a **separate implementation**, keyed on `account.current_tenant_id`, and it has the **same drop, plus three ways it is worse**. (a) Same shape: `_create_or_update_pipeline` filters a knowledge-retrieval node's `dataset_ids` through `decrypt_dataset_id` with a walrus comprehension, no `else`, nothing appended anywhere — structurally identical to D1. (b) Export encryption here is **unconditional**: no `DSL_EXPORT_ENCRYPT_DATASET_ID` check anywhere in the file, so no flag turns it off for future exports (contrast D7). (c) Its `decrypt_dataset_id` has **neither a plain-UUID short circuit nor post-decrypt UUID validation** (contrast D2) — it unconditionally AES-decrypts and returns `pt.decode()` raw, so a hand-written DSL with a plaintext dataset_id is dropped on its first import, *and* a non-empty garbage decode would survive into the persisted graph. (d) The response model has **no `warnings` field at all**, and its base sets `extra="ignore"`, so one cannot arrive by accident — R1's channel doesn't merely go unused here as on the app-DSL path; there is nowhere for it to report into without a schema change. | confirmed + live | drop `rag_pipeline_dsl_service.py:570-582` (inside `_create_or_update_pipeline`, `:537`); unconditional encrypt `:705-710`; decoder `:936-945` (raw return `:943`); response schema `api/controllers/console/datasets/rag_pipeline/rag_pipeline_import.py:51-58`, base `api/fields/base.py:9`; live: `evidence/kr-dataset-drop-rag-pipeline-2026-09-04T085016Z.json` (1.16.0), `baselines/1.17.1/evidence/kr-dataset-drop-rag-pipeline-2026-09-18T120551Z.json` (1.17.1) |
| S5 | If a target instance holds a tenant with the **same** UUID (reachable only by DB-level clone or restore — no application path accepts a caller-supplied tenant UUID), decryption succeeds, the id is kept verbatim, and **no existence check runs anywhere on the import path**. Whether that leaves a *dangling* reference depends on whether the dataset row came across too: a full clone preserves it and the reference resolves; a partial one does not and the reference dangles. Either way the import is silent about it — which is the point, and is the opposite symptom to the drop. | confirmed (code) / inference (operational premise) | the code half is now read, not inferred: key derivation `app_dsl_service.py:1090-1092` makes success equivalent to tenant-UUID equality; `decrypt_dataset_id` `:1106-1129` returns the UUID with zero DB access; the comprehension `:656-664` preserves whatever it returns without validation. What remains inference is only that a same-UUID tenant is reachable in practice |
| S6 | Two further paths **propagate** the app-DSL drop without adding a new implementation: the migration-package mover (see R6) and the recommended-app catalog / explore templates. Both delegate to the app-DSL carrier in both directions and inherit its silence. | confirmed (delegation) / not live-tested | see R6 anchors; catalog path delegates through the same `AppDslService` export/import entry points |

## 4. Reproduction environment — deviations from stock

Disclosed because without them the run is not reproducible.

| # | Fact | Grade | Anchor |
|---|---|---|---|
| E1 | `ALLOW_REGISTER` and `ALLOW_CREATE_WORKSPACE` both default `False`. **Since 1.17.x they do ship in an env example** (`shared.env.example:28-29`, both `false`) — at 1.16.0 they appeared in none, so the "undocumented" framing no longer applies. What still applies: no console route creates a second workspace, and `/console/api/setup` is one-shot, so on a stock stack there is no path to a second tenant *that this survey found*. Other supported entry points were not exhaustively enumerated. | confirmed (defaults, shipped) / bounded survey (absence of a route) | defaults `api/configs/feature/__init__.py:1595-1602`; shipped `docker/envs/core-services/shared.env.example:28-29` |
| E2 | `flask create-tenant` needs **both** flags: `create_account` raises `AccountNotFoundError("Account registration is disabled.")` without the first, and `create_owner_tenant` raises `WorkSpaceNotAllowedCreateError` without the second. The raised class changed between baselines — 1.16.0 raised the HTTP-layer `AccountNotFound`, 1.17.1 raises the service error — but the gate is unchanged. At 1.17.1 the command also **aborts in a non-TTY shell unless `--language` is passed**. | confirmed + live | `api/commands/account.py:91-147`; `api/services/account_service.py:421-422`, `:1085-1086`; class at `api/services/errors/account.py:4`. Observed live on both baselines |
| E3 | There is no console POST that creates a workspace; `/console/api/setup` is one-shot. | confirmed | all routes in `api/controllers/console/workspace/workspace.py` read; one-shot guard `api/controllers/console/setup.py:90-91` (`SetupAlreadyCompletedError` → `AlreadySetupError`) |
| E4 | Neither flag touches the import code path under test. Repo-wide the only non-test readers are in the account/registration/login path. | confirmed | `api/services/system_feature_service.py:51` (`is_registration_allowed`), `:106` (`is_workspace_creation_allowed`), `:149` (public system-features payload). `FeatureService.get_system_features()` is no longer the reader — the ledger's earlier mechanism sentence was correct in substance, wrong in detail |
| E5 | Console login takes the password **base64-encoded**, not encrypted — upstream's own docstring says so. Auth is cookie-based; every subsequent call needs `X-CSRF-Token`. | confirmed | docstring `api/libs/encryption.py:1-9` (byte-identical across both baselines), applied by `@decrypt_password_field` (`api/controllers/console/wraps.py:550-569`, wired at `api/controllers/console/auth/login.py:128`); CSRF enforcement `api/libs/token.py:197-227` — which exempts admin-key requests and whitelisted paths, so "every subsequent call" is true of the console session flow the drivers use, not of the API surface generally. **Correction:** the ledger previously cited `wraps.py:564-580` for the CSRF half — that was never a CSRF anchor, at either baseline |
| E6 | `/console/api/workspaces/current` **no longer exists** at 1.17.1. At 1.16.0 it was POST-only (observed: `GET` → HTTP 405); that class and its deprecated `/info` alias are gone, replaced by `GET /console/api/workspaces/current/summary`. The list endpoint still marks the active workspace with `"current": true`, which is what the drivers use. | confirmed (1.17.1) / live (the 1.16.0 405) | `api/controllers/console/workspace/workspace.py:260-273` (summary route), `:229-234` and `:126` (list endpoint's `current` flag) |

## 5. Do-not-claim list

Statements that are **not** supported. None of these may appear in an issue, in this log, or in
anything spoken.

1. ~~"`_generate_aes_key` is at `app_dsl_service.py:470-473`"~~ — it is `1089-1092` (it was
   `890-893` at 1.16.0). Do not substitute a new explanation of what `470-473` *is* instead: that
   span has been re-cited wrongly twice now, and at 1.17.1 it is neither the `match app_mode:`
   block (that is `:625`) nor, precisely, the `confirm_import` handler (which ends at `:469`). The
   only claim worth keeping is the negative one.
2. ~~"Cross-environment DSL import drops dataset references"~~ — still too broad. The chat-family
   carrier does not encrypt or filter at all (S1), the Agent path warns (S2), and the snippet path
   neither encrypts nor filters (S3). The claim is: workflow / advanced-chat apps with
   `knowledge-retrieval` nodes (gated by `DSL_EXPORT_ENCRYPT_DATASET_ID` at its default),
   **and** RAG-pipeline DSL with a `knowledge-retrieval` node (S4 — ungated, no flag turns it off).
   Both live-verified on 1.16.0 and again on 1.17.1.
3. ~~"Dify silently loses knowledge-base links on import"~~ — the Agent path is not silent (S2). A
   log containing `agent_knowledge_unresolved` disproves the word.
4. ~~"The dataset isn't in tenant B, so it was removed"~~ — no such mechanism. `decrypt_dataset_id`
   performs zero database access. Control 2 shows a *readable* id being written into tenant B's
   graph while B's own dataset list is empty (`dataset_visible_to_target_tenant: false`,
   `target_tenant_dataset_count: 0`).
4b. ~~"The drop is caused by the wrong tenant key"~~ — say "by `decrypt_dataset_id` returning
   `None`". That function returns `None` for several reasons (bad base64, padding, a decrypted
   value that is not a UUID); the run does not isolate which one, and it does not need to.
5. ~~"This reproduces on a default stack"~~ — it needs two non-default flags (E1).
6. ~~Screenshots as evidence~~ — the canvas renders `null` for a dropped id, a surviving
   unresolvable id, and a genuinely missing dataset alike
   (`web/app/components/workflow/nodes/knowledge-retrieval/node.tsx:26`), and runtime retrieval is
   tenant-filtered regardless (`api/core/rag/retrieval/dataset_retrieval.py:2083`). Raw JSON only.
7. ~~"Turning the flag off fixes it"~~ — it changes future exports only. The flag has exactly one
   runtime read site, inside the export helper (`app_dsl_service.py:1097-1098`, D7);
   `decrypt_dataset_id` never reads it, so already-exported DSLs still drop. And it does not exist
   at all on the RAG-pipeline path (S4b).
8. ~~"Upstream hasn't thought about this"~~ — they have (R4). The untested part is the silence.
9. ~~"A RAG maintainer owns this"~~ — CODEOWNERS routes by path, and **the two carriers route
   differently**. `api/services/app_dsl_service.py` matches only `*` (`.github/CODEOWNERS:7`) and
   `/api/` (`:37`) — no RAG-owned pattern reaches it. But the RAG-pipeline carrier
   `api/services/rag_pipeline/rag_pipeline_dsl_service.py` **does** match `/api/services/rag_pipeline/`
   (`:60`). Filing as two issues routes them to different owners; filing as one does not.
10. ~~"There is no CLA"~~ — only "nothing in this checkout" is verifiable offline; an org-level
    GitHub App leaves no in-repo trace. Note also `LICENSE:13-16`.
11. ~~"The frontend surfaces these warnings everywhere"~~ — it does not, but the ledger's earlier
    counts are stale. At 1.17.1 **four** call sites in three files render the structured payload
    via the shared `DSLImportWarningDescription` component
    (`web/app/components/app/create-from-dsl-modal/index.tsx:162`,
    `web/app/components/workflow/update-dsl-modal.tsx:102`, `web/hooks/use-import-dsl.ts:84` and
    `:169`), where two did at 1.16.0 — PR #41502, merged between the baselines, replaced the static
    fallback string. Some surfaces still show a static string.
12. ~~"The node errors at runtime"~~ — **tested and false** (D8/D9). Execution succeeds silently:
    `status: SUCCEEDED`, `outputs: {"result": []}`, no error, no log line distinguishing it from a
    legitimate zero-hit search. Do not claim the opposite either — the 2026-09-18 tighter control
    (D9) establishes that a populated dataset takes a *different* path and returns records, but
    **not** that an operator can tell the two apart from the node result. They both read
    `SUCCEEDED` + `result: []`.
13. ~~"iteration/loop/llm nodes were moved to graphon"~~ — verified only that those directories are
    absent from `api/core/workflow/nodes/` and that `graphon==0.7.0` is pinned
    (`api/pyproject.toml:48`; it was `0.6.0` at 1.16.0). "Moved there" is inference.
14. ~~"The migration-package mover loses dataset references"~~ — R6 is established by **reading**
    the delegation and the discarded `warnings` list, not by running it. No reproduction has been
    driven through `flask` data-migration. Say "by construction it delegates to the same carrier and
    discards the warning channel", not "we observed it".

## 6. Corrections carried in from earlier drafts

Recorded so the mistakes are not silently re-introduced.

- `app_dsl_service.py:470-473` is **not** `_generate_aes_key` (do-not-claim #1). At 1.16.0 the wrong
  citation was explained as "that is the `match app_mode:` block"; at 1.17.1 that explanation is
  itself stale — `:470-473` is now the `confirm_import` exception handler.
- The CSRF half of E5 was cited as `wraps.py:564-580`. That was **never** a CSRF anchor, at either
  baseline; at 1.16.0 those lines were `decrypt_password_field`. Correct anchor: `api/libs/token.py:197-227`.
- CODEOWNERS: the 1.16.0 correction about the RAG block (`61-97`) and the workflow-nodes block
  (`:56-59`) is **moot at 1.17.1** — upstream deleted every `/api/core/workflow/` pattern, so that
  tree now falls through to `/api/` (`:37`). The RAG block is `:59-94`.
- `"trigger-plugin"` is not an enum member but a constant at `api/core/trigger/constants.py:5`.
