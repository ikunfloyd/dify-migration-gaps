# Issue B — RAG-pipeline carrier

**Hold this one.** Post it only after Issue A has a response, and cross-link the two. Reasons, in
order of weight:

1. B needs a response-schema change before the fix is even expressible, so it is a larger decision
   than A. Filing both at once puts the small decision behind the large one.
2. If A is accepted, B can point at it as settled precedent for the same shape of problem, which is
   a much shorter argument than making the case twice.
3. If A gets no response inside the kill-date window, B should not be filed at all.

Fill Dify's `🕷️ Bug report` template with the fields below. Replace `#<A>` with Issue A's number.

---

## Title

```
RAG-pipeline DSL import silently drops knowledge-retrieval dataset_ids, and its response has no warnings field
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
Same shape as #<A>, on the RAG-pipeline importer, which is a separate implementation of the same
transport. Needs two tenants on one instance (see #<A> for how the bed is set up).

1. In tenant C, create a dataset, then a pipeline whose DSL contains a `knowledge-index` node
   (import is rejected without one) and import it.
2. Attach a `knowledge-retrieval` node bound to that dataset via
   `POST /console/api/rag/pipelines/{id}/workflows/draft`. This step is needed because
   `sync_draft_workflow` writes the graph verbatim — see the note on bootstrapping below.
3. Export the pipeline. `dataset_ids` is ciphertext.
4. Import the byte-identical DSL back into tenant C — `dataset_ids` survives.
5. Import the same DSL into tenant D — `dataset_ids` comes back `[]`, and the response reports
   `status: "completed"` with no `warnings` field to inspect.

**Why it happens.** Structurally identical to #<A>: a walrus comprehension drops whatever fails to
decrypt, with no `else`, nothing appended, no log —
`api/services/rag_pipeline/rag_pipeline_dsl_service.py:570-582` at 1.17.1, inside
`_create_or_update_pipeline` (`:537`):

```python
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

Three differences from the app-DSL path, each making this one harder to notice or to work around:

- **Export encryption is unconditional.** `_append_workflow_export_data` (`:705-710`) calls
  `encrypt_dataset_id` with no `DSL_EXPORT_ENCRYPT_DATASET_ID` check; that setting does not appear
  anywhere in this file, so there is no flag that turns it off for future exports.
- **The decoder has neither a plain-UUID short circuit nor post-decrypt UUID validation** (`:936-945`).
  It returns `pt.decode()` raw at `:943`. Two consequences: a hand-authored DSL carrying a plaintext
  `dataset_id` is dropped on its very first import, and conversely a non-empty garbage decode would
  be persisted where the app-DSL path would reject it. The first of these is also why step 2 above
  attaches the node after import instead of shipping it in the bootstrap DSL — there would be
  nothing left to export.
- **The response model has no `warnings` field at all.** `RagPipelineImportResponse`
  (`api/controllers/console/datasets/rag_pipeline/rag_pipeline_import.py:51-58`) has none, and its
  base sets `extra="ignore"` (`api/fields/base.py:9`), so one cannot arrive by accident. There is
  no `_warnings` list and no `_status_with_warnings` anywhere in the service.

`COMPLETED_WITH_WARNINGS` *is* reachable on this path, but only through the shared version-skew
check at `api/services/dsl_version.py:19` — never for a lost reference.

Scripted reproduction and evidence: https://github.com/ikunfloyd/dify-migration-gaps — the driver
asserts the absence of the `warnings` key explicitly and raises if one ever appears, so it will
notice if this changes. Also reproduced on 1.16.0; `git blame` dates this comprehension to
2025-09-18.
````

## ✔️ Expected Behavior

````markdown
Same ask as #<A>: when a non-empty input element is silently omitted, report it. The difference is
that this path cannot express that today, so it needs one more step first.

A fix here looks like:

1. Add `warnings: list[DslImportWarning]` to `RagPipelineImportResponse` and to the service's
   `RagPipelineImportInfo`.
2. Give the service a `_warnings` list and a `_status_with_warnings`, mirroring
   `app_dsl_service.py:879-882`.
3. Append on the discard branch, as in #<A>.

Step 1 is a response-schema change, which is why this is a separate issue rather than part of
#<A> — it is a decision about the API surface, not just about a branch that forgets to report.

What this is **not** asking for, same as #<A>: no change to the per-tenant key derivation, no
failing the import, no restoring or existence-checking the reference.

Worth deciding separately, and I have no strong view: whether `decrypt_dataset_id` here should gain
the plain-UUID short circuit and the post-decrypt UUID validation that the app-DSL version has. It
would make a hand-written pipeline DSL survive its first import and stop garbage decodes from being
persisted, but it is a behaviour change beyond reporting, so I have deliberately kept it out of
the ask above.
````

## ❌ Actual Behavior

````markdown
The reference is gone from the persisted graph, and unlike #<A> there is not even an empty
`warnings` array to notice.

| | app-DSL (#<A>) | RAG-pipeline (this issue) |
|---|---|---|
| Import response | `completed`, `warnings: []` | `completed`, **no `warnings` field** |
| Export encryption | gated by `DSL_EXPORT_ENCRYPT_DATASET_ID` | unconditional |
| Plain-UUID short circuit in the decoder | yes | no |
| Post-decrypt UUID validation | yes | no |
| Warning channel in the service | present, unused on this branch | absent entirely |

A same-tenant control import of the byte-identical artifact preserves `dataset_ids`, so the export
is intact and the importer does not drop ids in general.

There is no plaintext control for this path, because a plaintext id cannot survive import in *any*
tenant here — the decoder has no short circuit for it. That is itself part of the finding rather
than a gap in the testing.

Existing unit tests pin the encrypt/decrypt round trip
(`api/tests/unit_tests/services/rag_pipeline/test_rag_pipeline_dsl_service.py:207-209`, `:941`).
None covers the import-side silence.
````

---

## Notes for posting (not part of the issue)

- Replace every `#<A>` with the real number, and add a line to A pointing here once B exists.
- `api/services/rag_pipeline/` matches `/api/services/rag_pipeline/ @JohnJyong` in CODEOWNERS
  (`:60`). That governs automatic review requests on a **PR**, not issue assignment — it predicts
  who would review a patch, not where this issue lands.
- No patch is offered here on purpose. The schema change is a decision for whoever owns that API
  surface; offering a diff before that decision would be presumptuous, and the issue is stronger
  asking the question than pre-answering it.
- Same rule as A: no security label.
