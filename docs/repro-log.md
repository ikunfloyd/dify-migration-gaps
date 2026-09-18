# Reproduction log

> **KILL DATE — not yet armed.** No upstream issue has been opened. The rule, fixed in advance so
> it is not renegotiated under sunk cost: *the day an upstream issue is opened, that date + 21 days
> gets written here as an absolute date. If no maintainer has responded substantively by then, code
> investment stops, the analysis is published as-is, and the line is closed.* Earliest date an issue
> may be opened: **2026-09-02** (no public activity within two weeks either side of a relocation —
> upstream's stale workflow closes an issue after 15 days of inactivity plus a 3-day grace period
> [`.github/workflows/stale.yml` at the pinned commit; an externally-controlled setting that may have
> changed since], so an issue opened during a low-availability window gets closed underneath you).
> Note the consequence: a 21-day kill date fires *after* the bot may already have closed the issue,
> so the internal decision point sits around day 14.

Append-only, written during the session it describes. Timestamps come from the commands
themselves (`date -u`, container clocks, the driver script's own clock) rather than from memory —
but a reader has no way to verify that from the repository alone, so treat them as the author's
record, not as attested time. Failures stay in: the two failed tenant-creation attempts below are
the reason the flag disclosure exists at all.

## Conventions

- **Bed**: a single Dify v1.16.0 stack booted from the upstream `docker/` compose files, in its own
  Compose project, isolated from anything else on the machine. No modifications to upstream images.
- Every assertion is either an observation (something a command printed) or an anchor
  (`path:line` at the pinned commit). Inferences are labelled as such inline.
- The experiment's response bodies land in `evidence/` with UUID-shaped values replaced by a
  prefix-plus-hash pseudonym; structure and keys are untouched. They are neither raw nor a
  reconstruction. Steps outside the driver script (boot, tenant creation) are recorded here in
  prose, with the config snapshot in `evidence/bed-config-snapshot.txt`.

---

## 2026-08-21 — Bed prepared

- Upstream compose skeleton copied out of a read-only v1.16.0 checkout (commit `5c6372d`) into a
  standalone working directory. Nothing in the source checkout was modified.
- All required images already present locally at tag `1.16.0`, so the boot needs no registry access:
  `dify-api`, `dify-web`, `dify-agent-backend`, `dify-agent-local-sandbox`, `dify-plugin-daemon`,
  plus `postgres`, `redis`, `weaviate`, `nginx`, `squid`.

## 2026-08-21T17:27:12Z — Bed booted

`docker compose up -d`, own Compose project, ports bound to `127.0.0.1` only. 14 containers.
API answered `GET /console/api/setup` → `{"step":"not_started"}` at **17:36:32Z** (≈9 min, all of it
database migration and gunicorn boot; no image pulls).

## 17:39:31Z — Tenant A

`POST /console/api/init` (the `INIT_PASSWORD` gate — its result lives in the Flask session, so the
cookie jar must be carried into the next call) → `POST /console/api/setup` → HTTP 201.
`setup` takes the password **in plain text**; `login` takes it **base64-encoded**. Upstream's own
docstring is explicit that this is obfuscation, not encryption
(`api/libs/encryption.py:1-9`).

## 17:41:49Z — Tenant B: two failures, then a config disclosure

| Attempt | Config | Result |
|---|---|---|
| 17:41:49Z | stock | `flask create-tenant` → `AccountRegisterError: 400 Bad Request: Account not found.` |
| 17:43:36Z | `ALLOW_CREATE_WORKSPACE=true` | same failure |
| 17:46:15Z | `+ ALLOW_REGISTER=true` | `Account and tenant created.` |

Both are needed, for different reasons: `create_account` raises `AccountNotFound` when registration
is disabled (`api/services/account_service.py:438-441`), and tenant creation is separately gated
(`:1328-1333`). No console endpoint for creating a workspace was found among the routes read in
`api/controllers/console/workspace/workspace.py`, and `/console/api/setup` is one-shot — so on a
stock stack there is no route to a second tenant *that this survey found*. Other supported entry
points were not exhaustively enumerated.

**Disclosure.** The bed therefore runs with two non-default flags: `ALLOW_REGISTER=true`,
`ALLOW_CREATE_WORKSPACE=true`. Neither is read anywhere on the import path under test; they gate
account registration and workspace creation only. `DSL_EXPORT_ENCRYPT_DATASET_ID` is **absent from
the container environment**, so the app uses its declared default of `True`
(`api/configs/feature/__init__.py:1210-1213`). Captured, rather than asserted:
`evidence/bed-config-snapshot.txt` holds the `env` output and the image id.

## 17:50:12Z / 18:00:18Z — The experiment, run twice

One dataset, one workflow app with a single `knowledge-retrieval` node, one export, three imports.
Driver: `scripts/repro_kr_dataset_drop.py`.

Run once at 17:50:12Z, then **re-run at 18:00:18Z after an external review of the first bundle**.
The first run recorded `warnings` via `.get("warnings", [])`, which cannot distinguish an empty
array from a missing key, and it asserted rather than checked whether the target tenant could see
the surviving dataset. Both were fixed in the driver and the run repeated; only the second bundle is
kept, because the first one cannot support the sentences written about it. Results were identical
where the two overlap. Evidence: `evidence/kr-dataset-drop-2026-08-21T180018Z.json`.

Control 1 and the experiment used the **byte-identical** exported artifact. Control 2 by
construction did not: exactly one substring differs (the single `dataset_ids` element, ciphertext
replaced by the plaintext UUID), and it carries its own sha256 in the evidence bundle. Each run's
artifact hash is recorded alongside it.

| Run | Tenant | `dataset_ids` value sent | Import status | `warnings` | Persisted `dataset_ids` |
|---|---|---|---|---|---|
| Source app | A | plaintext UUID | `completed` | `[]` | **preserved** |
| **Control 1** | A → A | ciphertext (64 B) | `completed` | `[]` | **preserved** |
| **Experiment** | A → B | ciphertext (64 B) | `completed` | `[]` | **`[]` — dropped** |
| **Control 2** | A → B | plaintext UUID | `completed` | `[]` | **preserved** |

What each row rules out:

- **Control 1** — the exported artifact is not corrupt, and import does not drop dataset ids in
  general. What differs between this row and the experiment is the target tenant — together with
  everything that necessarily travels with it (the acting account, that tenant's workspace state).
  The source anchors, not this row alone, are what narrow the cause to the tenant-keyed decrypt.
- **Experiment** — the reference is gone from the persisted graph, and the import API response
  carried `status: "completed"` with an explicitly present, empty `warnings` array
  (`warnings_key_present: true` — an absent key would be a different and weaker observation). So
  *the import API response* said nothing about the discard. Server logs, the web UI and any other
  channel were not examined, and no claim is made about them. This is the finding.
- **Control 2** — same target tenant, same app shape, but a *readable* id: it survives into B's
  persisted graph while B's own dataset list is empty (`dataset_visible_to_target_tenant: false`,
  `target_tenant_dataset_count: 0`). So the element removed in the experiment was removed on the
  branch taken when `decrypt_dataset_id` returns `None` — not by an existence or ownership check,
  because this path performs none. (Note what this does *not* say: it does not isolate *why*
  decryption returned `None` — bad base64, padding, or a non-UUID result would all land in the same
  branch — and it does not argue that persisting a dangling foreign id is correct behaviour.)

Expected behaviour, for the record, is **not** "the import should fail", and not that the reference
should be restored, kept, or checked for existence. It is narrower: when a non-empty input element
is omitted, say so. The Agent path is cited only as proof that the structured-warning channel
already exists and is already used for unresolvable references
(`api/services/agent/dsl_service.py:530-544`) — its mechanism is *not* the same one (it holds
plaintext ids and queries the target tenant, so it knows the resource is genuinely missing; this
path only knows that a value would not decode). The machinery it uses is wired up in the very file
where the drop happens (`app_dsl_service.py:529`, `:708-711`).

Not tested at the time this section was written: what the node does at execution time with an
empty `dataset_ids`. Addressed below, 2026-09-04.

---

## 2026-09-04 — Runtime execution behaviour (do-not-claim item #12)

Same bed (`~/dify-oss-bed/docker`), brought back up via `docker compose up -d` after 9+ days
stopped. Postgres data volume survived the stop/start, so `/console/api/setup` still reported
`finished` from the 2026-08-21 session — but the original tenant A/B credentials were never
persisted anywhere outside that session's memory, so two fresh tenants were created instead of
reusing A/B: `flask create-tenant --email c-runtime@example.invalid` and
`--email d-runtime@example.invalid` (both require `ALLOW_REGISTER=true` and
`ALLOW_CREATE_WORKSPACE=true`, already set from the original bed disclosure — see E2).

Driver: `scripts/repro_kr_runtime_execution.py`. It repeats the cross-tenant import (tenant
C → tenant D, same mechanism as the original experiment) and then single-step-runs the
knowledge-retrieval node via `POST /console/api/apps/{app_id}/workflows/draft/nodes/{node_id}/run`
in both tenants.

First attempt (`evidence/kr-runtime-execution-2026-09-04T084119Z.json`, kept rather than deleted)
failed identically in both tenants with `error: "weights is required"` — a defect
in the test DSL, not the system under test: `multiple_retrieval_config.reranking_mode:
"weighted_score"` requires a `weights` object that the minimal DSL never supplied
(`knowledge_retrieval_node.py:229`), and that check runs before `dataset_ids` is ever consulted.
Fixed by switching `reranking_mode` to `"reranking_model"` with no model configured, which takes
the `else: reranking_model = None` branch instead (same file, `:232`) — a test-fixture fix, kept
local to the new script (`source_dsl_runnable`) rather than touching the already-evidenced
`repro_kr_dataset_drop.source_dsl`.

Second attempt: `evidence/kr-runtime-execution-2026-09-04T084155Z.json`.

| Run | Tenant | `dataset_ids` | Node status | `error` | `outputs.result` |
|---|---|---|---|---|---|
| Control | C (source) | present, but dataset has 0 indexed documents | `succeeded` | `null` | `[]` |
| Experiment | D (cross-tenant import) | dropped by the D1 defect | `succeeded` | `null` | `[]` |

What this shows: the node does not error when `dataset_ids` is empty. It returns a normal
`SUCCEEDED` result with no findings — indistinguishable, at the API level, from a query that
legitimately matched nothing.

What this does **not** show, and the control cannot be stretched to claim: the control dataset
had zero indexed documents, so it *also* took the empty-`available_datasets_ids` short circuit at
`dataset_retrieval.py:121-123` (see upstream-facts.md D9) — `_get_available_datasets` filters out
datasets with no completed/enabled documents the same way it filters out an empty `dataset_ids`
list. The control and the experiment therefore ran the identical code path, not two different
ones. That the *specific* branch taken differs between "reference dropped" and "real empty
result" is established by reading the source (D8's anchors), not demonstrated live here. A
tighter control would index real content into the tenant-C dataset first — not done in this
session; noted rather than silently skipped.

---

## 2026-09-04 (continued) — RAG-pipeline DSL import (S4)

Same bed, same tenants C and D. Driver: `scripts/repro_kr_dataset_drop_rag_pipeline.py`, same
four-row shape as the original experiment (source, control 1 same-tenant, experiment cross-tenant)
minus control 2 — plaintext-vs-tenant is not reachable here (see below).

First obstacle, found by reading `rag_pipeline_dsl_service.decrypt_dataset_id` before running
anything: unlike the app-DSL path (D2), it has **no plain-UUID short circuit** — it always
attempts AES decryption, on every import, including a pipeline's very first one. A hand-authored
DSL with a plaintext dataset_id in a `knowledge-retrieval` node would therefore be dropped on its
own bootstrap import — there would be nothing left to export. Worked around by importing a
pipeline with only the required `knowledge-index` node (import fails without one: "DSL is not
valid, please check the Knowledge Index node."), then attaching the `knowledge-retrieval` node
afterward via `POST .../workflows/draft` (`sync_draft_workflow` — writes the graph verbatim, never
calls `decrypt_dataset_id`). This is also why there is no control-2 analogue for this path: control
2 in the original experiment relied on a plaintext id surviving import in the *target* tenant to
show the drop isn't an existence check; here a plaintext id can't survive import in *any* tenant,
so that particular control question doesn't apply the same way.

Ran clean on the first attempt with a real DSL (no fixture bugs this time).
Evidence: `evidence/kr-dataset-drop-rag-pipeline-2026-09-04T085016Z.json`.

| Run | Tenant | `dataset_ids` sent | Import status | `warnings` key present | Persisted `dataset_ids` |
|---|---|---|---|---|---|
| Control 1 | C → C | ciphertext (64 B) | `completed` | no | **preserved** |
| Experiment | C → D | ciphertext (64 B), byte-identical to control 1 | `completed` | no | **`[]` — dropped** |

Two things beyond the drop itself, both checked rather than assumed:

- **Export encryption is unconditional here.** `_append_workflow_export_data` calls
  `encrypt_dataset_id` with no `DSL_EXPORT_ENCRYPT_DATASET_ID` (or any other flag) check anywhere
  in `rag_pipeline_dsl_service.py`. Unlike the app-DSL path, there is no environment variable that
  turns this off for future exports.
- **The response schema has no `warnings` field, not just an empty one.** The driver asserts this
  explicitly (`response_has_warnings_key: false` in the evidence, and the script raises if a
  `warnings` key is ever present in an import response — a canary in case a future upstream change
  adds one). `RagPipelineImportResponse`
  (`controllers/console/datasets/rag_pipeline/rag_pipeline_import.py:51-57`) simply has no such
  field. R1's reporting channel (`DslImportWarning` / `COMPLETED_WITH_WARNINGS`) isn't merely
  unused on this path the way it is on the app-DSL path (R3) — there's nowhere for it to report
  into without a schema change first.

Updated `docs/upstream-facts.md` S4 from "not tested" to confirmed + live, and do-not-claim item 2
now names RAG-pipeline DSL as a second confirmed carrier rather than a scope-bounding exception.


---

## 2026-09-18 — Re-pinned to 1.17.1, everything re-run

Upstream shipped **1.17.1** on 2026-09-10 (`8387590ace4a094de812b7847fc6a4c3a27cd52b`), **1501
commits** past the 1.16.0 baseline this analysis was written against, and both files carrying the
defect had commits in between — `app_dsl_service.py` 13 of them, one landing the same day this
section was written. Filing against a month-old tag invites "can you confirm on latest?", and with
upstream's stale bot at 15 days plus a 3-day grace, a wasted round trip is expensive. So the
baseline moved and everything was re-done rather than argued about.

### What was checked before touching anything

`git blame` at 1.17.1 dates the defect. The app-DSL drop (`:653-664`) was last touched
`1117b6e72d7`, **2026-04-09**; the RAG-pipeline drop (`:571-580`) `85cda47c70a`, **2025-09-18** —
a year to the day. `decrypt_dataset_id` (`:1107-1129`) splits between `2e9997110a1` (2025-04-03) and
`598ec07c911` (2025-09-08). In `git diff 1.16.0..1.17.1` the comprehension lines appear only as
*context*, never on either side of a hunk. Across 1501 commits nobody edited them.

Also checked before building anything: no upstream issue reports this. Three searches
(`dataset_ids`; knowledge-retrieval + import + workspace; `DslImportWarning` /
`COMPLETED_WITH_WARNINGS`) turned up nothing matching. #42087 has a similar *symptom* (workflow
retrieval returns `{"result":[]}`) but is Cloud, single-workspace, retrieval-testing-works, root
cause unidentified — not this path. #42499 mentions RAG-pipeline import but is an RBAC regression.

### Bed

New, isolated from the 1.16.0 one rather than upgrading it, so both remain runnable: 1.17.1's own
`docker/` compose files copied to `~/dify-oss-bed-1.17.1/docker`, `COMPOSE_PROJECT_NAME=difybed1171`,
ports `127.0.0.1:18092`/`18454`. Same two non-default flags disclosed for the original bed
(`ALLOW_REGISTER`, `ALLOW_CREATE_WORKSPACE`); `DSL_EXPORT_ENCRYPT_DATASET_ID` again absent from the
environment, so the declared default `True` applies. Images pulled fresh — digests and the effective
container env are in `baselines/1.17.1/evidence/bed-config-snapshot.txt`, which unlike the 1.16.0
bundles also records the upstream commit the run was made against. That omission in the earlier
bundles is real: nothing inside them says which version produced them, only the filename date.

API answered `/console/api/setup` about 10s after `compose up`. (An earlier poll reported "ready"
off a 502 from nginx — the readiness condition was too loose and was tightened to match on `"step"`.)

Tenant A via `/console/api/init` → `/console/api/setup`. Tenants B, C, D via `flask create-tenant`.
**New operational detail:** at 1.17.1 that command prompts for a language and therefore aborts
(`Language: Aborted!`) under `docker compose exec -T`; `--language en-US` must be passed explicitly.
The 1.16.0 log does not mention this because the prompt was not hit there.

### The three existing drivers, unmodified

None needed adaptation. The console paths, the DSL version (`CURRENT_APP_DSL_VERSION = "0.7.0"`,
unchanged between baselines) and the import payload shape all still match. The RAG-pipeline
controller was refactored to `@model_validate(RagPipelineImportPayload)` between baselines, but the
accepted body did not change.

| driver | result on 1.17.1 |
|---|---|
| `repro_kr_dataset_drop.py` | `dropped_without_report: true`, control 1 preserved, control 2 preserved — identical to 1.16.0. `warnings_key_present: true`, `warnings: []`, `status: "completed"` |
| `repro_kr_dataset_drop_rag_pipeline.py` | `dropped_without_report: true`, control 1 preserved, `response_schema_has_no_warnings_field: true` — the script's canary (it raises if a `warnings` key ever appears) did not fire |
| `repro_kr_runtime_execution.py` | node `succeeded`, `error: null` |

Evidence: `baselines/1.17.1/evidence/`.

### D9's caveat, discharged

The 2026-09-04 section closed by naming a limitation instead of hiding it: the control dataset had
zero indexed documents, so `_get_available_datasets` filtered it out with the same `having(count>0)`
predicate an empty `dataset_ids` trips, and control and experiment ran the *same* short circuit. New
driver `scripts/repro_kr_runtime_tighter_control.py` fixes that — it uploads a document with
deliberately distinctive invented tokens ("zarnathine protocol"), waits for `indexing_status:
completed`, confirms via hit-testing, and only then builds the app.

| | `dataset_ids` | node status | `result` |
|---|---|---|---|
| Control — tenant C, dataset **with** indexed content | 1 id | `succeeded` | **2 records** |
| Experiment — tenant D, cross-tenant import | dropped to `[]` | `succeeded` | 0 records |

The control now demonstrably does not take the experiment's short circuit. Two failures on the way,
both kept: the first run assumed `draft_node()` returned a graph when it returns `(node_id,
node_data)`, and the first patch still routed through the sibling script's `run_node()`, whose query
is hardcoded to an unrelated question — which would have made the control return `[]` for entirely
the wrong reason and looked like a confirmation. A local `run_query()` taking the caller's query
replaced it.

What this still does **not** show, and do-not-claim #12 now says so explicitly: that an operator can
tell the two apart. Both read `SUCCEEDED` + `result: []`.

### Re-anchoring the ledger

Every fact relocated section by section, each anchor established by opening the file at 1.17.1 and
quoting the decisive lines rather than adjusting the old number to fit. Every fact graded as
anything other than "moved" then went through a second, adversarial pass instructed to refute the
first.

43 facts: 2 same anchor, 29 moved, 8 need rewording, 4 changed, **0 refuted**. Two refutations
succeeded, both narrowing an overstatement rather than overturning a fact — D6 had been called a
reword on the grounds that a `target_tenant_id` local was new behaviour (it is not; the 1.16.0
assignment sat in the same create-branch), and E2 had been called a change when only the anchors and
the raised class moved. Full comparison: `baselines/1.17.1/anchor-map.md`.

Two errors in the ledger itself surfaced, neither caused by the version bump:

- The CSRF half of E5 cited `wraps.py:564-580`. That was never a CSRF anchor at *either* baseline —
  at 1.16.0 those lines were `decrypt_password_field`. Real anchor: `api/libs/token.py:197-227`.
- S4 said "plus **two** ways it is worse" and then listed three. Now three, and (c) is wider than
  written: the RAG decoder has no post-decrypt UUID validation either, so a non-empty garbage decode
  survives into the persisted graph where the app-DSL path would reject it.

E1 lost half a claim: `ALLOW_REGISTER`/`ALLOW_CREATE_WORKSPACE` now **do** ship in an env example
(`shared.env.example:28-29`), which they did not at 1.16.0. E6 lost more — `/console/api/workspaces/current`
does not exist at 1.17.1 at all, so "POST-only" is not a thing to say about it any more.

### Sweep for carriers the ledger missed

`grep -rn 'pad(\|unpad('` over non-test `api/` returns exactly four DSL hits across two files;
`grep -rn '"dataset_ids"\] ='` exactly five assignment sites across three. **Still exactly two
silent-drop implementations. No third carrier discards a reference.**

Two *propagation* paths were missing from the ledger, though, and one of them matters:

- **The migration-package mover** (`services/data_migration/`) — upstream's own cross-tenant bulk
  mover, i.e. the tool an operator would actually reach for to do what this analysis does by hand.
  It delegates to the app-DSL carrier both ways and adds a second layer of silence: `import_service.py:345`
  accepts `COMPLETED_WITH_WARNINGS` as success and never reads the list. Fixing the app-DSL branch
  alone would not surface anything here. Recorded as R6/S6 and, because it has **not** been run,
  fenced by new do-not-claim #14.
- The recommended-app catalog / explore templates, same delegation, same silence.

The reporting side got more precise too: exactly **six** `DslImportWarning` construction sites exist
repo-wide, all in `agent/dsl_service.py`, covering six classes of unresolvable reference — the ledger
had cited one. And exactly three sites set `COMPLETED_WITH_WARNINGS`, one of which
(`dsl_version.py:19`, extracted since 1.16.0) is shared by all three importers, making it the only
route by which a RAG-pipeline import can return that status — for version skew, never for a lost
reference.

### Second, independent derivation

The core questions were answered from source a second time, posed blind — without this analysis's
framing and without reference to it, so a wrong premise would surface as a rejection rather than be
confirmed by suggestion. That pass reached the same conclusions and sharpened two: the RAG decoder's
missing post-decrypt UUID validation (above), and that `RagPipelineImportResponse`'s base sets
`extra="ignore"` (`api/fields/base.py:9`), so a warnings field cannot arrive by accident — the schema
change really is a prerequisite. Those working notes are not committed; they were an instrument, not
evidence.

### Kill date

Still not armed. No upstream issue has been opened.
