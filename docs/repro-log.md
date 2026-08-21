# Reproduction log

> **KILL DATE — not yet armed.** No upstream issue has been opened. The rule, fixed in advance so
> it is not renegotiated under sunk cost: *the day an upstream issue is opened, that date + 21 days
> gets written here as an absolute date. If no maintainer has responded substantively by then, code
> investment stops, the analysis is published as-is, and the line is closed.* Earliest date an issue
> may be opened: **2026-09-02** (no public activity within two weeks either side of a relocation —
> the upstream stale bot closes an issue after 15 days of inactivity plus a 3-day grace period, so an
> issue opened during a low-availability window gets closed underneath you).

Append-only. Each entry is timestamped at the moment it happened, not reconstructed afterwards.
Failures stay in. A log with no failures in it is a log that was written after the fact.

## Conventions

- **Bed**: a single Dify v1.16.0 stack booted from the upstream `docker/` compose files, in its own
  Compose project, isolated from anything else on the machine. No modifications to upstream images.
- Every assertion is either an observation (something a command printed) or an anchor
  (`path:line` at the pinned commit). Inferences are labelled as such inline.
- Raw artifacts land in `evidence/` and are referenced by filename, not pasted inline.

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
(`:1328-1333`). A stock 1.16 stack cannot produce a second tenant at all — there is no console
endpoint for it and `/console/api/setup` is one-shot.

**Disclosure.** The bed therefore runs with two non-default flags: `ALLOW_REGISTER=true`,
`ALLOW_CREATE_WORKSPACE=true`. Neither is read anywhere on the import path under test; they gate
account registration and workspace creation only. `DSL_EXPORT_ENCRYPT_DATASET_ID` was left unset and
is therefore `true` (its default, and the shipped value).

## 17:50:12Z — The experiment

One dataset, one workflow app with a single `knowledge-retrieval` node, one export, three imports.
Driver: `scripts/repro_kr_dataset_drop.py`. Raw output: `evidence/kr-dataset-drop-2026-08-21T175012Z.json`.

Exported artifact: **1636 bytes, sha256 `4bed143f0da7…`**. The same bytes were used for all three
imports; nothing was hand-edited except where control 2 says so.

| Run | Tenant | `dataset_ids` value sent | Import status | `warnings` | Persisted `dataset_ids` |
|---|---|---|---|---|---|
| Source app | A | plaintext UUID | `completed` | `[]` | **preserved** |
| **Control 1** | A → A | ciphertext (64 B) | `completed` | `[]` | **preserved** |
| **Experiment** | A → B | ciphertext (64 B) | `completed` | `[]` | **`[]` — dropped** |
| **Control 2** | A → B | plaintext UUID | `completed` | `[]` | **preserved** |

What each row rules out:

- **Control 1** — the exported artifact is not corrupt, and import does not drop dataset ids in
  general. The only variable left is the tenant.
- **Experiment** — the reference is gone, and the API reported `status: "completed"` with an empty
  `warnings` array. Nothing anywhere told the caller that something was discarded. This is the
  finding.
- **Control 2** — the same target tenant, same app shape, but a *readable* id: it survives, and the
  imported app now holds a dataset id belonging to a tenant that is not its own. So the drop is
  attributable to decryption failing, and to nothing else — no existence check and no tenant-scope
  filter runs on this path. (It also means the plaintext branch persists dangling foreign
  references, which is a separate observation, not the one being reported.)

Expected behaviour, for the record, is **not** "the import should fail". It is: when references are
discarded, say so. Upstream's own Agent path does exactly that for the same situation
(`api/services/agent/dsl_service.py:530-544`), using warning machinery that is already wired up in
the very file where the drop happens (`app_dsl_service.py:529`, `:708-711`).

Not tested: what the node does at execution time with an empty `dataset_ids`. No claim is made
about it.

