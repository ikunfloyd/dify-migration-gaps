# Issue B — RAG-pipeline carrier

**Hold this one.** Post it only after Issue A has a response, and cross-link the two. Reasons, in
order of weight:

1. B needs a response-schema change before the fix is even expressible, so it is a larger decision
   than A. Filing both at once puts the small decision behind the large one.
2. If A is accepted, B can point at it as settled precedent for the same shape of problem, which is
   a much shorter argument than making the case twice.
3. If A gets no response inside the kill-date window, B should not be filed at all.

Fill Dify's `🕷️ Bug report` template with the fields below. Replace every `#NNN` with Issue A's
real number.

**When pasting: copy only what is *inside* the outer ```` ```markdown ```` fences.**

---

## Title

```
RAG-pipeline DSL import drops knowledge-retrieval dataset_ids across workspaces, and its response has no warnings field
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
Same shape as #NNN, on the RAG-pipeline importer — a separate implementation of the same
transport. As there, the ordinary trigger is moving a DSL between two installations; two workspaces
on one instance is just the cheaper way to reproduce it (see #NNN for how that bed was made).

1. In workspace C, create a dataset, then import a pipeline whose DSL contains a
   `knowledge-index` node — `POST /console/api/rag/pipelines/imports` with
   `{"mode": "yaml-content", "yaml_content": "..."}`. Without that node the import fails with
   *"DSL is not valid, please check the Knowledge Index node."*
2. Add a `knowledge-retrieval` node bound to that dataset. This is a whole-graph replace, not an
   append: `GET /console/api/rag/pipelines/{pipeline_id}/workflows/draft`, add the node to the
   returned `graph`, then `POST` the same path with `{"graph": ..., "hash": <the hash from that
   GET>, "environment_variables": [], "conversation_variables": [], "rag_pipeline_variables": []}`.
   The hash must match or the write is rejected (`WorkflowHashNotEqualError`). Going through the
   draft is what makes this possible: that path stores the graph without decoding ids.
3. Export: `GET /console/api/rag/pipelines/{pipeline_id}/exports?include_secret=false`; the DSL
   is in the response's `data`. `dataset_ids` is ciphertext.
4. Import the byte-identical DSL back into workspace C — `dataset_ids` survives. Read it back
   with `GET /console/api/rag/pipelines/{pipeline_id}/workflows/draft`; the ids live in the
   persisted graph, not in the import response.
5. Import the same DSL into workspace D — `dataset_ids` comes back `[]`, and the response reports
   `status: "completed"` with no `warnings` field to inspect.

**Why it happens.** Structurally identical to #NNN: a walrus comprehension drops whatever fails to
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
  be persisted where the app-DSL path would reject it. The first of these is why step 2 adds the
  node after import rather than shipping it in the bootstrap DSL: that DSL is hand-written, so its
  dataset_id is plaintext and would be dropped on the way in. An already-exported ciphertext
  reference imported back into its own workspace survives fine — step 4 is exactly that.
- **The response model has no `warnings` field at all.** `RagPipelineImportResponse`
  (`api/controllers/console/datasets/rag_pipeline/rag_pipeline_import.py:51-58`) has none, and its
  base sets `extra="ignore"` (`api/fields/base.py:9`), so one cannot arrive by accident. There is
  no `_warnings` list and no `_status_with_warnings` anywhere in the service.

`COMPLETED_WITH_WARNINGS` *is* reachable on this path, but only through the shared version-skew
check at `api/services/dsl_version.py:19` — never for a lost reference.

Scripted reproduction and evidence: https://github.com/ikunfloyd/dify-migration-gaps — the driver
asserts the absence of the `warnings` key explicitly and raises if one ever appears, so it will
notice if this changes. Introduced by #25360 (2025-09-18) and unchanged since; the node-type test directly above it
blames to 2026-03-15 (#33445), which was an enum move, not a change to this logic. Also reproduced
on 1.16.0.
````

## ✔️ Expected Behavior

````markdown
Same ask as #NNN: when a non-empty input element is discarded, report it. The observable is that
an import which drops a knowledge reference should say so in its response rather than reporting
plain success. The difference from #NNN is that this path cannot express that today.

How, is your call. The shape matching #NNN would be a `warnings` list on
`RagPipelineImportResponse` and on the service's `RagPipelineImportInfo`, a `_warnings` collector
and a `_status_with_warnings` mirroring `app_dsl_service.py:879-882`, and an append on the discard
branch — a suggestion, not the only option. Its first step changes the API surface, which is why
this is separate from #NNN: there the channel already exists and one branch simply does not use
it.

What this is **not** asking for, same as #NNN: no change to the per-tenant key derivation, no
failing the import, no restoring or existence-checking the reference.

Worth deciding separately, and I have no strong view: whether `decrypt_dataset_id` here should gain
the plain-UUID short circuit and the post-decrypt UUID validation that the app-DSL version has. It
would make a hand-written pipeline DSL survive its first import and stop garbage decodes from being
persisted, but it is a behaviour change beyond reporting, so I have deliberately kept it out of
the ask above.
````

## ❌ Actual Behavior

````markdown
The reference is gone from the persisted graph, and unlike #NNN there is not even an empty
`warnings` array to notice.

| | app-DSL (#NNN) | RAG-pipeline (this issue) |
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

- Replace every `#NNN` with the real number, and add a line to A pointing here once B exists.
  (An earlier draft used `#NNN`; markdown swallows that as an HTML tag and it renders as
  nothing at all.)
- `api/services/rag_pipeline/` matches `/api/services/rag_pipeline/ @JohnJyong` in CODEOWNERS
  (`:60`). That governs automatic review requests on a **PR**, not issue assignment — it predicts
  who would review a patch, not where this issue lands.
- No patch is offered here on purpose. The schema change is a decision for whoever owns that API
  surface; offering a diff before that decision would be presumptuous, and the issue is stronger
  asking the question than pre-answering it.
- Same rule as A: no security label.
