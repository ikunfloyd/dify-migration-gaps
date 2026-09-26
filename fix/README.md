# Proposed fix — app-DSL path

A patch for the app-DSL carrier (D1/D5), with before-and-after evidence from the same
reproduction that established the defect.

Not submitted upstream. Dify requires an associated issue and an assignment before a PR
(`.github/PULL_REQUEST_TEMPLATE.md`), so this waits on the issue.

| | |
|---|---|
| Patch | [`0001-report-dropped-knowledge-references.patch`](0001-report-dropped-knowledge-references.patch) |
| Applies to | `langgenius/dify` `origin/main` @ `f4602cc1fe` (2026-09-25) — verified with `git apply --check` on a pristine worktree |
| Size | `api/services/app_dsl_service.py` +32 −9, plus 96 lines of tests |
| Scope | the app-DSL carrier only. The RAG-pipeline carrier (S4) needs a response-schema change first and is deliberately not touched here |

## What it does

Replaces the walrus comprehension that silently discards undecryptable `dataset_ids` with an
explicit loop that appends a `DslImportWarning` on the discard branch. Nothing else changes: the
encryption is untouched, the import still succeeds, and the reference is neither restored nor
existence-checked. Only the silent omission is reported.

Every piece of machinery it uses already exists in the same file — `self._warnings`,
`_status_with_warnings`, `Import.warnings`. Nothing new is introduced.

## The four decisions, and why

These are the parts a reviewer will actually argue about; the line count is not.

**1. What goes in `details` — `node_id` and `node_title`, never the undecryptable value.**

Both the AES key and the IV derive from the tenant id alone, so echoing the ciphertext back would
widen exposure while helping nobody: the recipient cannot decode it, cannot look it up, and cannot
act on it. The dataset *name* is unavailable — this code path performs zero database access, which
is exactly why it cannot tell a foreign reference from a corrupt one. So the warning reports what
it honestly knows: which node, by the title the operator sees on the canvas.

**2. One warning per dropped reference, not one per node with a count.**

Matches the seven existing construction sites in `agent/dsl_service.py`, and the per-element `path`
keeps the original index, which survives duplicates in a way an aggregate count would not.

**3. Empty strings are skipped, not reported.**

An empty string was never a reference, so dropping it is not a loss. Reporting it would produce a
warning for something the operator never configured. A `len(before) - len(after)` count gets this
wrong; the explicit `elif dataset_id:` does not. There is a test pinning this.

**4. `code = "workflow_knowledge_unresolved"`.**

Follows the existing `agent_knowledge_unresolved` naming. The `workflow` prefix covers both
affected modes, since advanced-chat and workflow apps travel through the same `workflow.graph`
import branch.

The warning carries the node title rather than only the array index, because
`workflow.graph.nodes.1` is not something an operator can find on a canvas.

## Verification

**Unit tests** — four, added next to `test_create_or_update_app_removes_imported_workflow_viewport`
(which covers the viewport logic two lines above the patched loop, so the fixture shape is already
established there). Run against a real 1.17.1 build, all passing: a cross-tenant reference is
reported; one warning per unresolved reference; an empty string is not reported; the response
status is promoted to `COMPLETED_WITH_WARNINGS`.

**End-to-end** — `scripts/repro_kr_dataset_drop.py`, unmodified, against the same bed used for the
1.17.1 baseline, patched and unpatched. The driver's own verdict flips and nothing else moves:

| run | before | after |
|---|---|---|
| Source app (tenant A) | `completed` | `completed` |
| Control 1 — A → A, byte-identical artifact | `completed`, preserved | `completed`, preserved |
| **Experiment — A → B** | `completed`, `warnings: []` | **`completed-with-warnings`** |
| Control 2 — plaintext id → B | `completed`, preserved | `completed`, preserved |
| `dropped_without_report` | `true` | **`false`** |

Both controls stay quiet, which is the half that matters for review: the change reports the real
loss without inventing warnings for imports that lost nothing.

The response body the experiment now returns
([full bundle](evidence/kr-dataset-drop-PATCHED-2026-09-26T040513Z.json)):

```json
{
  "code": "workflow_knowledge_unresolved",
  "path": "workflow.graph.nodes.1.data.dataset_ids.0",
  "message": "Knowledge base reference in node 'Knowledge Retrieval' could not be restored in this workspace and must be reselected.",
  "details": { "node_id": "kr", "node_title": "Knowledge Retrieval" }
}
```

## What this does not fix

- **The RAG-pipeline carrier (S4).** Structurally identical drop, but its response model has no
  `warnings` field and its service has no `_warnings` list at all, so it needs a schema change
  before the same approach is even expressible. Separate issue, separate patch.
- **The migration-package mover (R6).** It delegates to this carrier and then discards the warning
  channel — `import_service.py:345` accepts `COMPLETED_WITH_WARNINGS` as success and never reads
  the list. This patch makes the warning exist; that path still throws it away.
- **Visibility at runtime.** A node whose references were dropped still executes as `SUCCEEDED`
  with `result: []`. This patch makes the loss visible *at import time*, which is where the
  operator can still act on it.

## Reproducing the before/after

```bash
# unpatched: dropped_without_report: true
python3 scripts/repro_kr_dataset_drop.py --base http://127.0.0.1:18092 \
    --email-a ... --password-a ... --email-b ... --password-b ... --out /tmp/before

# apply the patch to the running build, restart the api container, then:
# patched: dropped_without_report: false, experiment status completed-with-warnings
python3 scripts/repro_kr_dataset_drop.py ... --out /tmp/after
```

Bed setup is in `docs/repro-log.md`; the 1.17.1 section covers the flags and the second-tenant
route.
