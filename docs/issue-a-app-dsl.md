# Issue A — app-DSL carrier

Ready to post. Fill Dify's `🕷️ Bug report` template with the fields below; the template has only
three free-text areas and asks not to be modified, so everything is arranged to fit them.

Post B only after A gets a response — see `issue-b-rag-pipeline.md`.

---

## Title

```
Cross-tenant DSL import silently drops knowledge-retrieval dataset_ids
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
Needs two tenants on one instance. A stock stack has no route to a second one, so the bed used here
runs `flask create-tenant` with `ALLOW_REGISTER=true` and `ALLOW_CREATE_WORKSPACE=true` (at 1.17.1
that command also needs an explicit `--language`, or it aborts on its prompt in a non-TTY shell).
Neither flag is read anywhere on the import path — `api/services/system_feature_service.py:51`,
`:106`, `:149` are their only non-test readers.

1. In tenant A, create a dataset (`economy` indexing avoids needing an embedding model) and a
   workflow app with a single `knowledge-retrieval` node bound to it.
2. Export it: `GET /console/api/apps/{app_id}/export`. `dataset_ids` in the YAML is ciphertext,
   not the plain UUID.
3. Import the byte-identical YAML back into tenant A — `dataset_ids` survives.
4. Import the same byte-identical YAML into tenant B — `dataset_ids` comes back `[]`, and the
   response is `status: "completed"` with `warnings: []` (key present, explicitly empty).
5. Run the node. It returns `SUCCEEDED` with `outputs: {"result": []}`.

**Why it happens.** `dataset_ids` is exported AES-encrypted under a key derived from
`sha256(source_tenant_id)` and decrypted on import under `sha256(target_tenant_id)`, so across
tenants `decrypt_dataset_id` returns `None`. The import-side comprehension drops those elements
with no `else`, nothing appended to the warnings list, and no log line —
`api/services/app_dsl_service.py:653-664` at 1.17.1:

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
which defaults `true` (`api/configs/feature/__init__.py:1293`) — note the import side never reads
that flag, so turning it off does not help a DSL that was already exported.

Nothing surfaces it downstream either. `DatasetRetrieval.knowledge_retrieval` short-circuits before
the query is inspected (`api/core/rag/retrieval/dataset_retrieval.py:158-160`), and the node's
`_run` treats that as an ordinary success (`.../knowledge_retrieval/knowledge_retrieval_node.py:143-145`).

Scripted reproduction, raw evidence bundles with ids pseudonymised, and a per-claim source ledger:
https://github.com/ikunfloyd/dify-migration-gaps — the drivers run unmodified against 1.17.1.
Also reproduced on 1.16.0; `git blame` dates this comprehension to 2026-04-09.
````

## ✔️ Expected Behavior

````markdown
When a non-empty input element is silently omitted, say so — through the mechanism this codebase
already has. `DslImportWarning` exists for exactly this
(`api/services/entities/dsl_entities.py:31-37`, docstring: *"Portable DSL reference that could not
be restored in the target workspace"*), it is constructed in `api/services/agent/dsl_service.py`
for the other kinds of reference that cannot be restored in a target workspace, and the very same
`match`-case branch in `app_dsl_service.py` already extends `self._warnings` a few lines below the
drop. The knowledge-retrieval branch is the one that collects nothing.

To be clear about what this is **not** asking for:

- **Not** a change to the per-tenant key derivation. That boundary is deliberate and this report
  does not touch it.
- **Not** that the import should fail, nor that the reference be restored or existence-checked.
- **Not** every DSL carrier. Chat / agent-chat / completion apps carry `dataset_ids` in
  `model_config` unencrypted and unfiltered, so nothing drops there. The Agent-v2 knowledge path
  already warns. The snippet path does not encrypt at all
  (`api/services/snippet_dsl_service.py:593-599`).
- **Not** a report about the node erroring at runtime — it does not. Mentioned only because that
  is the natural first guess.

The RAG-pipeline importer has a structurally identical drop, but fixing it needs a response-schema
change first, so it is a separate issue rather than part of this one.
````

## ❌ Actual Behavior

````markdown
The reference is gone from the persisted graph and no channel reports it.

| | |
|---|---|
| Import response | `status: "completed"`, `warnings: []` — the key is present and explicitly empty |
| Persisted graph | `dataset_ids: []` |
| Node execution | `status: SUCCEEDED`, `outputs: {"result": []}` |

That last row is the part that makes it hard to notice: a dropped reference and a query that
legitimately matched nothing produce the same result shape, so an app that has quietly stopped
consulting its knowledge base looks like one whose search found nothing.

Two controls in the linked reproduction narrow the cause. Re-importing the **byte-identical**
artifact into the source tenant preserves `dataset_ids`, so the export is not corrupt and import
does not drop ids in general. Importing the same artifact with the ciphertext replaced by the
plaintext UUID into the *target* tenant also preserves it — while that tenant's own dataset list is
empty — so the element is removed on the branch taken when `decrypt_dataset_id` returns `None`,
not by any existence or ownership check. (That function performs no database access at all.)

Existing tests pin all four encrypt/decrypt branches
(`api/tests/test_containers_integration_tests/services/test_app_dsl_service.py:1625-1665`). None
covers the silence of the import-side drop.

I have a patch for this written and tested — it replaces the comprehension with an explicit loop
that appends a `DslImportWarning` on the discard branch, using only machinery already in that file:
+23 −9 in the service plus five unit tests. Verified end-to-end by re-running the same reproduction
against a patched build: the cross-tenant import returns `completed-with-warnings` naming the node,
while both controls stay at `completed` with no warnings. One externally visible consequence worth
flagging: an import that loses a reference would return `COMPLETED_WITH_WARNINGS` instead of
`COMPLETED`; every existing consumer of the import result already accepts that status.

The patch is at https://github.com/ikunfloyd/dify-migration-gaps/blob/main/fix/ — happy to open it
as a PR against `main` if that is useful.
````

---

## Notes for posting (not part of the issue)

- The six Self Checks are all `required: true`. The searched-for-existing-issues one is honest:
  three searches on 2026-09-18 (`dataset_ids`; knowledge-retrieval + import + workspace;
  `DslImportWarning` / `COMPLETED_WITH_WARNINGS`) turned up nothing matching. #42087 has a similar
  symptom but is Cloud, single-workspace, cause unidentified.
- Do not add a security label. An independent review of the disclosure question concluded
  public-first is defensible: runtime retrieval re-filters by the executing tenant
  (`dataset_retrieval.py:2083`), so a persisted foreign id grants nothing.
- The evidence-repo links are live — the repository is public as of 2026-09-27.
- Once the number is known, start the kill-date clock in `docs/repro-log.md`: opened + 21 days
  written as an absolute date, with the real decision point around day 14 because the stale bot
  closes at 15 days idle plus a 3-day grace.
- If a PR follows, the template asks that PRs created by an automated agent say so in the
  description. That is a question about the PR, not about this issue.
