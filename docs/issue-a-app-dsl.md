# Issue A — app-DSL carrier

Ready to post. Fill Dify's `🕷️ Bug report` template with the fields below.

**When pasting: copy only what is *inside* the outer ```` ```markdown ```` fences.** The wrappers
are there to keep this file readable; pasting them makes the whole field render as literal code.

Post B only after A gets a response — see `issue-b-rag-pipeline.md`.

---

## Title

```
Workflow DSL import drops knowledge-retrieval dataset_ids across workspaces without reporting it
```

## Dify version

```
1.17.1
```

## Cloud or Self Hosted

```
Self Hosted (Docker)
```

## Steps to reproduce

````markdown
**The ordinary trigger is moving a DSL between two Dify installations** — staging to production, a
workflow a colleague exports and sends you, a template from a community repo. A knowledge-retrieval
node's `dataset_ids` are exported encrypted under a key derived from the source workspace's tenant
id, and every installation generates its own tenant ids (`uuid4`, `api/models/account.py`), so the
importing side cannot decode them. They are dropped, and the import reports success.

I reproduced it with two tenants on one instance because that is cheaper than running two stacks —
the code path is the same one, and the same thing happens between two workspaces on one install.
`flask create-tenant` is how the second tenant was made here; it prompts for email, name and
language, prints a generated password once, and needs `ALLOW_REGISTER=true` and
`ALLOW_CREATE_WORKSPACE=true`. Neither flag is read anywhere on the import path
(`api/services/system_feature_service.py:51`, `:106`, `:149` are their only non-test readers) — the
bug does not depend on them, only my way of getting a second tenant does.

1. In workspace A, create a dataset (`economy` indexing avoids needing an embedding model) and a
   workflow app with one `knowledge-retrieval` node bound to it.
2. Export: `GET /console/api/apps/{app_id}/export`. In the YAML, `dataset_ids` is ciphertext, not
   the plain UUID.
3. Import that YAML back into workspace A:
   `POST /console/api/apps/imports` with `{"mode": "yaml-content", "yaml_content": "..."}`.
   Read the result back with `GET /console/api/apps/{new_app_id}/workflows/draft` — the ids are in
   the persisted graph, not in the import response. `dataset_ids` survives.
4. Import the **byte-identical** YAML into workspace B. `dataset_ids` comes back `[]`, and the
   import response is `status: "completed"` with `warnings: []` — the key is present and empty.
5. Optional, to see the runtime side: single-step the node with
   `POST /console/api/apps/{app_id}/workflows/draft/nodes/{node_id}/run`, body
   `{"inputs": {"<node_id>.query": "anything"}}`. It returns `"status": "succeeded"` with
   `"outputs": {"result": []}`. Configure `multiple_retrieval_config` with
   `"reranking_mode": "reranking_model"` and no model — `"weighted_score"` without a `weights`
   object raises `weights is required` before `dataset_ids` is ever consulted
   (`knowledge_retrieval_node.py:249-251`), which is a fixture problem, not this bug.

**Why it happens.** Export encrypts with a key derived from `sha256(source_tenant_id)`
(`app_dsl_service.py:1089-1092`, `:841-846`); import decrypts with the target tenant's
(`:661`). In this cross-workspace reproduction the decode returns `None`, and the comprehension
discards that element — no `else`, nothing appended to the warnings list, no log line
(`api/services/app_dsl_service.py:653-664` at 1.17.1):

```python
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

The mutated graph is what gets persisted (`:668-680`). Gated by `DSL_EXPORT_ENCRYPT_DATASET_ID`,
default `true` (`api/configs/feature/__init__.py:1293`) — note the import side never reads that
flag, so turning it off does not help a DSL that was already exported.

The retrieval call then short-circuits before the query is inspected
(`api/core/rag/retrieval/dataset_retrieval.py:158-160`) and the node's `_run` treats that as an
ordinary success (`.../knowledge_retrieval/knowledge_retrieval_node.py:143-145`).

Introduced by #17353 (2025-04-03) and unchanged since. (`git blame` points at #34869, 2026-04-10,
but that commit converted `if/elif` to `match/case` and only reindented these lines.) Also
reproduced on 1.16.0.

Scripted reproduction, evidence bundles with ids pseudonymised, and a per-claim source ledger:
https://github.com/ikunfloyd/dify-migration-gaps — `scripts/repro_kr_dataset_drop.py` is this
procedure end to end and runs unmodified against 1.17.1.
````

## ✔️ Expected Behavior

````markdown
When a non-empty input element is discarded, say so — through the mechanism this codebase already
has. `DslImportWarning` exists for exactly this (`api/services/entities/dsl_entities.py:31-37`,
docstring: *"Portable DSL reference that could not be restored in the target workspace"*), it is
constructed in `api/services/agent/dsl_service.py` for the other kinds of reference that cannot be
restored in a target workspace, and the same `match`-case branch in `app_dsl_service.py` already
extends `self._warnings` a few lines below the drop. The knowledge-retrieval branch is the one that
collects nothing.

To be clear about what this is **not** asking for:

- **Not** a change to the per-workspace key derivation. That boundary is deliberate and this report
  does not touch it.
- **Not** that the import should fail, nor that the reference be restored or existence-checked.
- **Not** every DSL carrier. Chat / agent-chat / completion apps carry their dataset ids in
  `model_config` and round-trip them verbatim, unencrypted and unfiltered, so nothing drops there.
  The Agent-v2 knowledge path already warns. The snippet path does not encrypt at all
  (`api/services/snippet_dsl_service.py:593-599`).
- **Not** a report about the node erroring at runtime — it does not. Mentioned only because that is
  the natural first guess.

The RAG-pipeline importer has a structurally identical drop, but reporting it there needs a
response-schema change first, so it is a separate issue rather than part of this one.
````

## ❌ Actual Behavior

````markdown
The reference is gone from the persisted graph, and neither channel I checked reports it.

| | |
|---|---|
| Import response | `status: "completed"`, `warnings: []` — key present, explicitly empty |
| Persisted graph | `dataset_ids: []` |
| Node execution | `"status": "succeeded"`, `"outputs": {"result": []}` |

I did not examine server logs or the web UI, so this is "the import response and the node result
say nothing", not "nothing anywhere says anything". What the source does show is that the discard
branch itself neither warns nor logs.

That last row is what makes it hard to notice: a dropped reference and a query that legitimately
matched nothing produce the same result shape, so an app that has quietly stopped consulting its
knowledge base looks like one whose search found nothing. With a dataset that actually has indexed
content, the same node returns 2 records before the move and 0 after.

Two controls narrow the cause. Re-importing the **byte-identical** artifact into the source
workspace preserves `dataset_ids`, so the export is not corrupt and import does not drop ids in
general. Importing the same artifact with the ciphertext replaced by a plaintext UUID into the
*target* workspace also preserves it — while that workspace's own dataset list is empty — so the
element is removed on the branch taken when `decrypt_dataset_id` returns `None`, not by any
existence or ownership check. That function performs no database access at all, which is also why
it cannot tell a foreign reference from a corrupt one.

Existing tests pin all four encrypt/decrypt branches
(`api/tests/test_containers_integration_tests/services/test_app_dsl_service.py:1625-1665`). None
covers the silence of the import-side drop.

I have a patch written: it replaces the comprehension with an explicit loop that appends a
`DslImportWarning` on the discard branch, using only machinery already in that file — +23 −9 in the
service plus five unit tests. Re-running the same reproduction against a patched build, the
cross-workspace import returns `"completed-with-warnings"` naming the node, while both controls
stay at `"completed"` with no warnings. It was executed on a 1.17.1 build (that is what my bed
runs) and applied and compiled against `main` at `f4602cc`; the block it replaces is byte-identical
at both. One externally visible consequence: an import that loses a reference would return
`COMPLETED_WITH_WARNINGS` instead of `COMPLETED` — every in-tree consumer of the import result that
I checked already accepts that status.

https://github.com/ikunfloyd/dify-migration-gaps/blob/main/fix/ — happy to open it as a PR if
that is useful.
````

---

## Notes for posting (not part of the issue)

- The six Self Checks are all `required: true` and are the poster's own attestations. The
  searched-for-existing-issues one is supportable: three searches on 2026-09-18 (`dataset_ids`;
  knowledge-retrieval + import + workspace; `DslImportWarning` / `COMPLETED_WITH_WARNINGS`),
  including closed issues, turned up nothing matching. #42087 has a similar symptom but is Cloud,
  single-workspace, cause unidentified.
- No security label. Public-first is defensible: runtime retrieval re-filters by the executing tenant (`dataset_retrieval.py:2083`),
  so a persisted foreign id grants nothing.
- Once the number is known, write the absolute date into the time-budget note at the top of
  `docs/repro-log.md`.
