# Baseline 1.17.1 — re-verification

The original analysis was pinned to **1.16.0** (`5c6372d`, read 2026-08-21). By 2026-09-18 upstream
had shipped **1.17.1** (`8387590ace4a094de812b7847fc6a4c3a27cd52b`, released 2026-09-10), **1501
commits** later, and both files carrying the defect had been modified in between. An issue filed
against a month-old tag invites "can you confirm on latest?" — which costs a round trip against a
stale bot that closes after 15 days of inactivity.

So the whole thing was re-run against 1.17.1: every ledger fact relocated and re-graded, the three
reproductions re-executed on a fresh stack, and an exhaustive sweep for carriers the ledger had
missed.

| | 1.16.0 | 1.17.1 |
|---|---|---|
| Commit | `5c6372d2f76d240265b92fd27c16bc772ffcb107` | `8387590ace4a094de812b7847fc6a4c3a27cd52b` |
| Released | — | 2026-09-10 |
| Bed | `~/dify-oss-bed/docker`, project `docker`, port 18091 | `~/dify-oss-bed-1.17.1/docker`, project `difybed1171`, port 18092 |
| Evidence | `evidence/` | `baselines/1.17.1/evidence/` |

## Headline

**Nothing was refuted.** 43 facts re-graded, zero overturned. The defect is intact in both carriers,
the reporting channel it should use is intact and now used in *more* places, and the scope
boundaries still hold.

| outcome | count |
|---|---|
| holds, same anchor | 2 |
| holds, anchor moved | 29 |
| holds, needs rewording | 8 |
| changed | 4 |
| **refuted** | **0** |

Per-fact detail: [`anchor-map.md`](anchor-map.md).

## The defect code is not merely present — it is untouched

`git blame` at 1.17.1 dates the two drop sites and the decoder:

| site | last touched | age at 2026-09-18 |
|---|---|---|
| `app_dsl_service.py:653-664` (app-DSL drop) | `1117b6e72d7`, 2026-04-09 | 5 months |
| `rag_pipeline_dsl_service.py:571-580` (RAG-pipeline drop) | `85cda47c70a`, 2025-09-18 | 12 months |
| `app_dsl_service.py:1107-1129` (`decrypt_dataset_id`) | `2e9997110a1` 2025-04-03 / `598ec07c911` 2025-09-08 | 12–17 months |

The `git diff 1.16.0..1.17.1` for both files shows the comprehension lines only as *context* —
they are not on either side of a change hunk. Across 1501 commits nobody edited them.

## The reproductions, re-run on 1.17.1

A fresh bed was booted from 1.17.1's own `docker/` compose files with the same two non-default flags
the original disclosed (`ALLOW_REGISTER`, `ALLOW_CREATE_WORKSPACE`), `DSL_EXPORT_ENCRYPT_DATASET_ID`
left unset so the declared default `True` applies. Image digests and effective container environment
are captured in [`evidence/bed-config-snapshot.txt`](evidence/bed-config-snapshot.txt) — which,
unlike the 1.16.0 bundles, also records the upstream commit the run was made against.

The three existing drivers ran **unmodified**. The console API paths, the DSL version (`0.7.0`) and
the import payload shape were all unchanged, so no adaptation was needed.

| driver | verdict on 1.17.1 |
|---|---|
| `repro_kr_dataset_drop.py` | `dropped_without_report: true`, both controls preserved — identical to 1.16.0 |
| `repro_kr_dataset_drop_rag_pipeline.py` | `dropped_without_report: true`, control preserved, `response_schema_has_no_warnings_field: true` |
| `repro_kr_runtime_execution.py` | node `succeeded`, `error: null` — no runtime error, as on 1.16.0 |

Operational detail worth recording: at 1.17.1 `flask create-tenant` aborts in a non-TTY shell unless
`--language` is passed explicitly. The 1.16.0 log does not mention this.

## D9's caveat is now discharged

The 2026-09-04 runtime run carried a limitation that was recorded rather than hidden: its control
dataset had **zero indexed documents**, so `_get_available_datasets`' `having(count > 0)` filter sent
the control down the *same* empty short circuit as the experiment. Two rows, one code path — the run
could not show the two situations were distinguishable at all.

A new driver, [`repro_kr_runtime_tighter_control.py`](../../scripts/repro_kr_runtime_tighter_control.py),
removes it: the source tenant's dataset is given a real indexed document first.

| | `dataset_ids` | node status | `result` |
|---|---|---|---|
| Control (tenant C, dataset **with** indexed content) | 1 id | `succeeded` | **2 records** |
| Experiment (tenant D, cross-tenant import) | dropped to `[]` | `succeeded` | 0 records |

The control now returns a non-empty result through the full retrieval path, so it is demonstrably
*not* running the experiment's short circuit. Evidence:
[`evidence/kr-runtime-tighter-control-20260918T120921Z.json`](evidence/).

What this still does **not** establish, and must not be claimed: that an operator can tell the two
apart from the node result. A dropped reference and a genuine zero-hit search both yield
`SUCCEEDED` + `result: []`. The tighter control proves the control is *capable* of a non-empty
result; it does not make the failure visible.

## Exhaustive carrier sweep — still exactly two silent drops

The ledger's scope section was written from four known carriers. A repo-wide sweep at 1.17.1 went
looking for a fifth.

`grep -rn 'pad(\|unpad(' --include='*.py' api --exclude-dir=tests` returns exactly four DSL hits
(`app_dsl_service.py:1103/:1118`, `rag_pipeline_dsl_service.py:933/:942`); the only other match is
tool-credential encryption, not id transport. `grep -rn '"dataset_ids"\] =' --include='*.py' api
--exclude-dir=tests` returns exactly five assignment sites across three files. There is no sixth.

**Two distinct silent-drop implementations, unchanged: `app_dsl_service.py:656-664` and
`rag_pipeline_dsl_service.py:573-582`.** No third carrier discards a reference.

But the sweep found **two propagation paths the ledger never recorded**. Neither adds a new drop
implementation; both widen the blast radius of the two that exist:

1. **The migration-package mover** — `api/services/data_migration/export_service.py:137-139`,
   `import_service.py:326-347`, `api/commands/data_migration.py:406`. This is *upstream's own
   cross-tenant bulk mover*: exactly the tool an operator would reach for to do what this analysis
   reproduces by hand. It delegates to the app-DSL carrier in both directions, and it adds a
   **second layer of silence** — `import_service.py:345` accepts `COMPLETED_WITH_WARNINGS` as
   success and never reads the `warnings` list. Even if the app-DSL branch were fixed to emit a
   `DslImportWarning`, this path would still throw it away. Its report model has no slot for it
   either: `ResourceType` (`data_migration/entities.py:30-35`) is WORKFLOW / API_TOOL /
   WORKFLOW_TOOL / MCP_TOOL / DEPENDENCY.
2. **The recommended-app catalog / explore templates** — also delegates to the app-DSL carrier,
   same silence.

## The reporting channel is more used than the ledger says

Exactly **six** `DslImportWarning` construction sites exist repo-wide, all in one file,
`api/services/agent/dsl_service.py`:

| line | code | covers |
|---|---|---|
| `:471` | `agent_workspace_skill_unresolved` | workspace skill not findable by name in the target tenant |
| `:606` | `agent_{kind}_omitted` | omitted skill or file asset (two kinds) |
| `:617` | `agent_tool_authorization_required` | dify tool needing authorization |
| `:633` | `agent_secret_required` | secret reference from soul / CLI-tool environments |
| `:642` | `agent_human_contact_unresolved` | human contact needing reselection |
| `:657` | `agent_knowledge_unresolved` | agent soul dataset id absent from the target tenant |

This strengthens the argument materially. The ledger cited only the last one. Upstream has in fact
built structured reporting for **six** classes of unresolvable reference — and the
knowledge-retrieval node's `dataset_ids` is not among them.

Exactly **three** sites set `COMPLETED_WITH_WARNINGS`: `app_dsl_service.py:879-882`,
`snippet_dsl_service.py:611-613`, and `api/services/dsl_version.py:19`. That third one is new since
1.16.0 — version-skew promotion extracted into a helper shared by all three importers. Its
consequence for S4 is precise and worth stating in the issue: **a RAG-pipeline import *can* return
`COMPLETED_WITH_WARNINGS`, but only for DSL version skew, never for a lost reference** — there is no
`_warnings` list and no `_status_with_warnings` anywhere in `rag_pipeline_dsl_service.py`.

## Second, independent derivation

The core claims were derived from the source a second time, from blind questions posed without this
analysis's framing and without reference to it — so that a wrong premise would surface as a
rejection rather than be confirmed by suggestion. That pass reached the same conclusions, and
sharpened two:

- **The RAG-pipeline decoder has no post-decrypt UUID validation either** — it returns `pt.decode()`
  raw (`:943`), where the app-DSL path requires the result to be a UUID. So that path filters only
  falsey values, and a non-empty decoded *garbage* string would survive into the persisted graph.
  Ledger S4(c) understates this; it mentions only the missing plain-UUID short circuit.
- **`RagPipelineImportResponse`'s base sets `extra="ignore"`** (`api/fields/base.py:9`), so a
  warnings field cannot even arrive by accident — the schema change really is a prerequisite.

That pass's working notes are not committed here; it was a verification instrument, not evidence.

## What this changes for filing

- The `DSL_EXPORT_ENCRYPT_DATASET_ID` flag has **exactly one runtime read site** repo-wide
  (`app_dsl_service.py:1097`, inside the export helper). That is the source-level proof for
  do-not-claim #7 — turning the flag off cannot fix an already-exported DSL.
- **CODEOWNERS now routes the two carriers differently.** `api/services/rag_pipeline/` matches
  `:60 @JohnJyong`; `app_dsl_service.py` matches only `*` (`:7`) and `/api/` (`:37`). The "file as
  one issue or two" question in the issue draft now has a factual answer: two issues route to
  different owners, one does not.
- Do-not-claim #11 is stale **in the report's favour**. PR #41502 (merged between the two baselines)
  replaced the static fallback string with a shared `DSLImportWarningDescription` component; four
  call sites now render the structured payload where two did before.
