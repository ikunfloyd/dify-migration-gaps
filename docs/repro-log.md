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

