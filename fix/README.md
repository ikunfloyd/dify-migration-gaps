# Proposed fix — app-DSL path

A patch for the app-DSL carrier (D1/D5), with before-and-after evidence from the same
reproduction that established the defect.

Not submitted upstream. Dify's PR template asks for an associated issue and `Fixes #<n>`, and warns
that a PR without prior discussion may be closed (`.github/pull_request_template.md` on `main`), so
this waits on the issue.

| | |
|---|---|
| Patch | [`0001-report-dropped-knowledge-references.patch`](0001-report-dropped-knowledge-references.patch) |
| Applies to | `langgenius/dify` `origin/main` @ `6decc78fd5` (2026-09-30) — the branch is rebased onto it, so the patch applies cleanly |
| Size | `api/services/app_dsl_service.py` **+23 −9**; `api/tests/.../test_app_dsl_service.py` **+179** (one helper, eight tests) |
| Scope | the app-DSL carrier only. The RAG-pipeline carrier (S4) needs a response-schema change first and is deliberately not touched here |

## What it does

Replaces the walrus comprehension that silently discards undecryptable `dataset_ids` with an
explicit loop that appends a `DslImportWarning` on the discard branch. Nothing else changes: the
encryption is untouched, the import still succeeds, and the reference is neither restored nor
existence-checked. Only the silent omission is reported.

Every piece of machinery it uses already exists in the same file — `self._warnings`,
`_status_with_warnings`, `Import.warnings`. Nothing new is introduced.

One externally visible consequence, called out because it is a behaviour change and not just a
richer response body: a cross-tenant import that loses a reference now returns
`COMPLETED_WITH_WARNINGS` where it used to return `COMPLETED`. Every existing consumer of the
import result already accepts that status; an import that loses nothing is unaffected.

## The four decisions, and why

These are the parts a reviewer will actually argue about; the line count is not.

**1. What goes in `details` — `node_id` and `node_title`, never the undecryptable value.**

Both the AES key and the IV derive from the tenant id alone, so echoing the ciphertext back would
widen exposure while helping nobody: the recipient cannot decode it, cannot look it up, and cannot
act on it. The dataset *name* is unavailable because `decrypt_dataset_id` performs no database
access — it is pure hashlib/AES/base64/uuid, which is exactly why it cannot tell a foreign
reference from a corrupt one. (The enclosing `_create_or_update_app` does touch the database for
other purposes; the point is that the decode itself has nothing to look a name up with.) So the
warning reports what it honestly knows: which node, by the title the operator sees on the canvas.

**2. One warning per dropped reference, not one per node with a count.**

Matches the existing construction sites in `agent/dsl_service.py`, and the per-element `path` keeps
the original index, which survives duplicates in a way an aggregate count would not.

This composes with how the web client renders them, which is also why decision 1 puts the node
title in the *message* and not only in `details`:
`web/app/components/app/create-from-dsl-modal/dsl-import-warning-description.tsx` de-duplicates by
message text (`new Set(warnings.map(w => w.message.trim()))`) and shows at most three. So several
losses inside one node collapse to a single line — which is what an operator wants — while losses
in different nodes stay distinct, because the titles differ. Had the message omitted the title,
every warning would have collapsed into one and the operator would not know how many nodes to fix.

**3. Empty strings are skipped, not reported.**

An empty string was never a reference, so dropping it is not a loss. Reporting it would produce a
warning for something the operator never configured. A `len(before) - len(after)` count gets this
wrong; the explicit `elif dataset_id:` does not. There is a test pinning this.

**4. `code = "workflow_knowledge_unresolved"`.**

Follows the existing `agent_knowledge_unresolved` naming. The `workflow` prefix covers both
affected modes, since advanced-chat and workflow apps travel through the same `workflow.graph`
import branch. The message reuses the established sibling phrasing — *"is unavailable in the target
workspace"* — and adds the node title, because `workflow.graph.nodes.1` is not something an
operator can find on a canvas.

## Verification

**Unit tests** — eight, in `api/tests/unit_tests/services/test_app_dsl_service.py`, next to
`test_create_or_update_app_removes_imported_workflow_viewport` (which covers the viewport handling
immediately above the patched loop, so the fixture shape was already established there). Run
against a real 1.17.1 build, all passing:

| test | pins |
|---|---|
| `..._warns_when_knowledge_reference_cannot_be_restored` | a cross-tenant reference is dropped *and* reported, with exact code/path/message/details |
| `..._keeps_knowledge_reference_encrypted_for_this_workspace` | an id encrypted under the importing workspace's own tenant still decodes, and nothing is reported |
| `..._keeps_plaintext_knowledge_reference` | a plain dataset id, as exported with encryption off, passes through, and nothing is reported |
| `..._reports_one_warning_per_unresolved_knowledge_reference` | per-element granularity and index |
| `..._does_not_warn_about_empty_knowledge_references` | an empty string is not reported as a loss |
| `..._reports_each_knowledge_node_separately` | two knowledge nodes are not conflated; each warning carries its own node index and id, and the two messages differ |
| `..._reports_untitled_knowledge_node_under_default_label` | a node with no title is reported under `Knowledge Retrieval`, the node type's default label |
| `..._promotes_the_import_status` | the response status stops saying plain `completed` |

Five of these fail if the loop is reverted to the original comprehension. The own-workspace,
plaintext and empty-string tests pass either way by design — they pin behaviour that must *not*
change.

**End-to-end** — `scripts/repro_kr_dataset_drop.py`, unmodified in substance, against the same bed
used for the 1.17.1 baseline, patched and unpatched. The driver's own verdict flips and nothing
else moves:

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
([full bundle](evidence/kr-dataset-drop-PATCHED-2026-09-26T064145Z.json)):

```json
{
  "code": "workflow_knowledge_unresolved",
  "path": "workflow.graph.nodes.1.data.dataset_ids.0",
  "message": "Knowledge base in node 'Knowledge Retrieval' is unavailable in the target workspace and must be reselected.",
  "details": { "node_id": "kr", "node_title": "Knowledge Retrieval" }
}
```

**Where this was executed.** Both the unit tests and the end-to-end run were exercised on a
**1.17.1** build, because that is what the reproduction bed runs. The patch itself targets
`origin/main`; the block it replaces is byte-for-byte identical at both revisions, which is why the
same change ports cleanly. It has **not** been executed on a main build — stated plainly rather
than implied, since the two are not the same claim.

## Known edge cases, not fixed here

Both predate the patch and behave identically before and after it; recorded so a reviewer does not
have to find them.

- A malformed DSL whose `dataset_ids` is a bare string rather than a list gets iterated
  character-by-character. The persisted result is the same as before (everything drops), but the
  patch now emits one warning per character. Guarding it would mean changing how malformed input is
  handled, which is a different change.
- A non-string element inside `dataset_ids` raises `AttributeError` out of `_is_valid_uuid`, which
  catches only `(ValueError, TypeError)`. This is pre-existing: the original comprehension raised
  at the same point.

## What this does not fix

- **The RAG-pipeline carrier (S4).** Structurally identical drop — the same comprehension,
  byte-for-byte — but its response model has no `warnings` field and its service has no `_warnings`
  list at all, so it needs a schema change before the same approach is even expressible. Separate
  issue, separate patch.
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
