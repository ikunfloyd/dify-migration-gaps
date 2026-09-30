# PR — app-DSL carrier

Ready to open against `langgenius/dify` `main`. The branch is `kr-dataset-drop-warning` in
`~/workspace/dify-upstream`, rebased onto current `main`. Push it to your fork, then open the PR
with the title and body below.

**When pasting: copy only what is *inside* the outer ```` ```markdown ```` fences.**

Upstream's PR template is prefilled in the description box; replace it wholesale with the body
below — the body already carries the template's checklist.

---

## Title

```
fix(api): report knowledge-retrieval dataset ids dropped on cross-workspace DSL import
```

## Body

````markdown
Fixes #43062

## Summary

With dataset-id encryption on export at its default (`DSL_EXPORT_ENCRYPT_DATASET_ID=true`),
importing a workflow or advanced-chat DSL into a workspace other than the one it was exported from
silently drops every encrypted reference in a `knowledge-retrieval` node's `dataset_ids`. The ids
are encrypted under a key derived from the source workspace's tenant id and decrypted under the
target's, so across workspaces `decrypt_dataset_id` returns `None`, and the comprehension in
`_create_or_update_app` discards those elements with no `else`, nothing appended to the warnings
list, and no log line. The import reports `completed` and nothing in its `warnings` mentions the
loss; at runtime the node then returns `succeeded` with `result: []`, which is the same shape as a
search that legitimately matched nothing.

This change reports the discard through the mechanism the file already has: `DslImportWarning`,
which the same `match`-case branch already collects for agent-package references a few lines
below. The encryption is untouched; the import still succeeds, and the reference is neither
restored nor existence-checked. Only the silent omission is reported, so the operator knows which
node to rebind. This is the patch offered in #43062.

## Differences from #43083, each pinned by a test

#43083 takes the same approach (explicit loop, `DslImportWarning` on the discard branch). What
differs:

- The message carries the node title. The web client de-duplicates import warnings by message
  text (`dsl-import-warning-description.tsx`: a `Set` over `message.trim()`, at most
  `MAX_VISIBLE_IMPORT_WARNINGS = 3` shown), so with a fixed message three affected nodes collapse
  into one line and the operator cannot tell how many nodes need rebinding. With the title, each
  distinctly titled node keeps its own line. A node with no `title` is reported under the English
  default label, `Knowledge Retrieval`.
- The `path` reaches the element (`workflow.graph.nodes.{i}.data.dataset_ids.{j}`) rather than
  stopping at the list, matching the existing `agent_knowledge_unresolved` shape.

The undecodable value itself is not echoed: it is the ciphertext the caller just uploaded and
cannot help with reselection. The dataset name is unavailable here, since `decrypt_dataset_id`
performs no database access.

## Changes

- `api/services/app_dsl_service.py`: the walrus comprehension becomes an explicit loop. Decodable
  ids are kept as before; each non-empty id that will not decode appends a `DslImportWarning` with
  `code="workflow_knowledge_unresolved"`, the element path, and `details={"node_id", "node_title"}`.
  Empty strings are skipped, since an empty string was never a reference to lose. The persisted
  `dataset_ids` are identical to before for every input.
- `api/tests/unit_tests/services/test_app_dsl_service.py`: one helper and eight tests, next to
  the existing viewport test for the same loop. They pin the warning's exact code, path, message
  and details; one warning per unresolved element; separate warnings with distinct messages for
  two nodes; the default label for an untitled node; promotion of the status to
  `COMPLETED_WITH_WARNINGS`; and three cases that must stay silent (own-workspace ciphertext,
  plain id, empty string). Five of the eight fail if the loop is reverted.

One externally visible consequence: a cross-workspace import that loses a reference now returns
`COMPLETED_WITH_WARNINGS` instead of `COMPLETED`. Every in-tree consumer already accepts that
status: the controllers special-case only `FAILED` and `PENDING`
(`controllers/console/app/app_import.py`, `controllers/openapi/app_dsl.py`,
`controllers/inner_api/app/dsl.py`), `services/app/console_service.py` and
`services/data_migration/import_service.py` accept it explicitly, and the web create-from-DSL,
update-DSL and `use-import-dsl` surfaces branch on it. An import that loses nothing is unaffected.

Out of scope, deliberately: the RAG-pipeline importer has a structurally identical drop, but
`rag_pipeline_dsl_service.py` has no `_warnings` collector and `RagPipelineImportResponse` has no
`warnings` field, so reporting there needs a schema change first. Separate issue.

## Verification

- The eight new unit tests pass on a patched 1.17.1 build (the replaced block is byte-identical
  between 1.17.1 and `main`); the existing tests in the file are untouched.
- `ruff check`, `ruff format --check` (0.16.9) and `pyrefly check` (1.3.1, core config and
  `tests/unit_tests/pyrefly.toml`) are clean on the two changed files. The full `make lint`
  (import-linter and the rest) is left to CI.
- End to end, the reproduction from #43062 re-run against the patched build: the cross-workspace
  import returns `completed-with-warnings` naming the node, while a same-workspace re-import of
  the byte-identical artifact and a plaintext-id import both stay at `completed` with no
  warnings. Scripts and evidence: https://github.com/ikunfloyd/dify-migration-gaps

## Checklist

- [ ] This change requires a documentation update, included: [Dify Document](https://github.com/langgenius/dify-docs)
- [x] I understand that this PR may be closed in case there was no previous discussion or issues. (This doesn't apply to typos!)
- [x] I've verified the change and added or updated tests where meaningful regression risk justifies coverage.
- [ ] I've updated the documentation accordingly.
- [ ] I ran `make lint && make type-check` (backend) and `vp staged` (frontend) to appease the lint gods (ruff and pyrefly clean on the changed files; full `make lint` left to CI)
````

---

## Notes for posting (not part of the PR)

- The checklist above is the template's current one on `main`; the third item's wording changed
  recently ("where meaningful regression risk justifies coverage"). Verify against the box when
  you open it.
- `ruff check` and `ruff format --check` were run with ruff 0.16.9 against `api/.ruff.toml` and
  are clean on both files. `pyrefly check` 1.3.1 was run inside a throwaway
  `langgenius/dify-api:1.17.1` container (the only local interpreter with Dify's dependencies),
  pointed at the `main`-based tree, with both the core config and `tests/unit_tests/pyrefly.toml`:
  the only diagnostic, on pristine `main` and on the branch alike, is the `yaml` untyped-import
  warning, which CI's `types-PyYAML` silences. import-linter was not run (needs `uv sync`).
- After opening, comment once on #43062 linking the PR, so the issue shows both.
