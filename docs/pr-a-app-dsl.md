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
silently empties every `knowledge-retrieval` node's encrypted `dataset_ids`. The ids are encrypted on
export under a key derived from the source workspace's tenant id and decrypted on import under the
target's, so across workspaces `decrypt_dataset_id` returns `None`, and the comprehension in
`_create_or_update_app` discards those elements with no `else`, nothing appended to the warnings
list, and no log line. The import reports `completed` and nothing in its `warnings` mentions the
loss; at runtime the node then returns `succeeded` with `result: []`, which is the same shape as a
search that legitimately matched nothing.

This change reports the discard through the mechanism the file already has. `DslImportWarning`
exists for exactly this case, and the same `match`-case branch already extends `self._warnings`
for agent-package warnings a few lines below; the knowledge-retrieval branch was the one that
collected nothing.

The encryption is untouched. The import still succeeds, and the reference is neither restored nor
existence-checked — only the silent omission is now reported, so the operator knows which node to
rebind. This is the patch offered in #43062.

## Changes

- `api/services/app_dsl_service.py` (+23 −9): the walrus comprehension becomes an explicit loop.
  Decodable ids are kept as before; each non-empty id that will not decode appends a
  `DslImportWarning` with `code="workflow_knowledge_unresolved"`, a `path` down to the element
  (`workflow.graph.nodes.{i}.data.dataset_ids.{j}`), and `details={"node_id", "node_title"}`.
  Empty strings are skipped — an empty string was never a reference to lose.
- `api/tests/unit_tests/services/test_app_dsl_service.py` (+162): one helper and seven tests next
  to `test_create_or_update_app_removes_imported_workflow_viewport`, which covers the viewport
  handling immediately above the same loop. They pin: a cross-workspace reference is dropped *and*
  reported with exact code/path/message/details; an id encrypted under the importing workspace's
  own tenant still decodes and produces no warning; a plain dataset id (encryption off on export)
  passes through and produces no warning; one warning per unresolved element; empty strings
  produce no warning; two knowledge nodes in one graph get separate warnings with their own index
  and id; and `_status_with_warnings` promotes the result to `COMPLETED_WITH_WARNINGS` once a
  warning has been collected. Four of the seven fail if the loop is reverted to the comprehension;
  the own-workspace, plaintext and empty-string tests pass either way by design, since they pin
  behaviour that must not change.

## Two decisions worth reviewing

**The node title is in the message, not only in `details`.** The web client de-duplicates import
warnings by message text — `web/app/components/app/create-from-dsl-modal/dsl-import-warning-description.tsx`
de-duplicates by `warning.message.trim()` and shows at most `MAX_VISIBLE_IMPORT_WARNINGS = 3`.
With a fixed message string, three affected nodes collapse into one line and the operator cannot
tell how many nodes need rebinding. With the title in the message, losses inside one node collapse
(which is what you want) while nodes with different titles stay distinct, within the client's
existing three-message limit. A node whose DSL carries no `title` is reported under the English
default label, `Knowledge Retrieval`. The phrasing follows the existing sibling messages:
*"… is unavailable in the target workspace."*

**The undecodable value is not echoed.** It is the ciphertext the caller just uploaded, so
returning it tells them nothing they do not have, and it cannot help with reselection. The dataset
name is genuinely unavailable here: `decrypt_dataset_id` performs no database access, which is also
why it cannot tell a foreign reference from a corrupt one. The warning reports what it honestly
knows — which node, by its title.

One externally visible consequence: a cross-workspace import that loses a reference now returns
`COMPLETED_WITH_WARNINGS` instead of `COMPLETED`. Every in-tree consumer of the app-import result
already accepts that status — `services/app/console_service.py`,
`services/data_migration/import_service.py`, and the web create-from-DSL, update-DSL and
`use-import-dsl` surfaces — and an import that loses nothing is unaffected.

## Relation to #43083

#43083 takes the same approach — explicit loop, `DslImportWarning` on the discard branch. The
differences, each pinned by a test here:

- the message carries the node title, so the web client's dedupe keeps one line per distinctly
  titled node instead of collapsing every affected node into one (see above; the multi-node test
  asserts the messages differ);
- the `path` reaches the element (`…dataset_ids.{j}`) rather than stopping at the list, matching
  the existing `agent_knowledge_unresolved` shape;
- there is a multi-node test, and the warning code is `workflow_knowledge_unresolved`, following
  the sibling naming.

## Verification

- The seven new unit tests pass on a patched 1.17.1 build; the existing tests in the file are
  untouched.
- `ruff check` and `ruff format --check` (ruff 0.16.9, `api/.ruff.toml`) are clean on both changed
  files. `pyrefly check` (1.3.1) on both files, with the core config and the stricter
  `tests/unit_tests/pyrefly.toml`, reports nothing beyond the `yaml` untyped-import warning that is
  already there on `main`. The import linter is left to CI.
- End-to-end, the same reproduction that established the defect was re-run against a patched build:
  the cross-workspace import returns `completed-with-warnings` naming the node, while a
  same-workspace re-import of the byte-identical artifact and a plaintext-id import into the target
  workspace both stay at `completed` with no warnings — the change reports the real loss without
  inventing warnings for imports that lost nothing.
- That end-to-end run was on a 1.17.1 build (the reproduction bed); the block this patch replaces
  is byte-identical between 1.17.1 and `main`, and the patch applies cleanly to current `main`.
- Reproduction scripts, evidence bundles and a per-claim source ledger:
  https://github.com/ikunfloyd/dify-migration-gaps

Out of scope, deliberately: the RAG-pipeline importer has a structurally identical drop, but
`rag_pipeline_dsl_service.py` has no `_warnings` collector and `RagPipelineImportResponse` has no
`warnings` field, so reporting there needs a schema change first — a separate issue.

## Checklist

- [ ] This change requires a documentation update, included: [Dify Document](https://github.com/langgenius/dify-docs)
- [x] I understand that this PR may be closed in case there was no previous discussion or issues. (This doesn't apply to typos!)
- [x] I've verified the change and added or updated tests where meaningful regression risk justifies coverage.
- [ ] I've updated the documentation accordingly.
- [ ] I ran `make lint && make type-check` (backend) and `vp staged` (frontend) to appease the lint gods — ruff and pyrefly are clean on the changed files; the full `make lint` (import-linter and the rest) is left to CI
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
