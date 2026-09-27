# dify-migration-gaps

Reproducible failure modes when moving a [Dify](https://github.com/langgenius/dify) application
between environments (or between workspaces), pinned to **v1.17.1**.

This is an independent analysis. Every claim here is backed by one of exactly two things:

1. a **`path:line` anchor into upstream source at a pinned commit**, verified by opening that
   line at that commit, or
2. a **from-zero reproduction log** produced on a clean stack on my own machine.

Nothing else is admissible. In particular this repository contains no material from any
employer, no third-party application definitions, and no customer data.

## Upstream baseline

| | Current | Original |
|---|---|---|
| Repository | `langgenius/dify` | same |
| Commit | `8387590ace4a094de812b7847fc6a4c3a27cd52b` | `5c6372d2f76d240265b92fd27c16bc772ffcb107` |
| Version | 1.17.1 (released 2026-09-10) | 1.16.0 |
| Read on | 2026-09-18 | 2026-08-21 |

All line-number anchors in `docs/` refer to the **current** commit. Line numbers drift; the commit
does not.

The analysis was first written against 1.16.0 and re-anchored to 1.17.1 — **1501 commits later** —
on 2026-09-18: every fact relocated and re-graded, and every reproduction re-run on a fresh 1.17.1
stack. 43 facts: the core finding stood, and no fact was overturned as a whole, though several
supporting sub-claims were corrected or withdrawn — E1 and E6 each lost half. The two defect sites were introduced by #17353 (2025-04-03, app-DSL) and #25360 (2025-09-18, RAG-pipeline)
respectively; neither was touched in between. The old→new anchor comparison lives in
[`baselines/1.17.1/anchor-map.md`](baselines/1.17.1/anchor-map.md) so the ledger states one
baseline rather than two.

## What is in here

| Path | What it is |
|---|---|
| `docs/upstream-facts.md` | Fact ledger — each claim graded *confirmed / corrected / live / inference / unverified*, with its anchor |
| `docs/repro-log.md` | From-zero reproduction log, timestamped, append-only |
| `docs/issue-a-app-dsl.md` · `docs/issue-b-rag-pipeline.md` | The two upstream issues, ready to post. Neither is filed. B waits on A |
| `docs/issue-draft.md` | The full argument in one piece — the source behind those two, including what they omit for length |
| `evidence/` | Raw captured artifacts from the 1.16.0 runs (HTTP responses with ids pseudonymised, artifact hashes, container state). The exported DSL itself is not captured — it carries ciphertext keyed to a tenant id |
| `baselines/1.17.1/` | The 1.17.1 re-verification: anchor map, its own evidence bundles, bed snapshot |
| `fix/` | A tested patch for the app-DSL carrier, with before/after evidence. Not submitted |
| `scripts/` | Scripts that drive the reproduction, so a reader can rerun it. **Point them at a throwaway stack** |
| `LICENSE` · `THIRD-PARTY-LICENSES.md` | MIT covers this repository's own work — the analysis, the scripts, the captured evidence. Source quoted from Dify stays under Dify's licence; `THIRD-PARTY-LICENSES.md` reproduces it and inventories every excerpt |

## The gap this starts with

Export a **workflow** (or advanced-chat) app containing a `knowledge-retrieval` node, then import it
under a **different tenant**. The node's `dataset_ids` come back empty, and the import reports
`status: "completed"` with `warnings: []`. Nothing tells the caller that a reference was discarded.

Scope matters here, and the carriers do not all behave the same way: chat / agent-chat /
completion apps carry dataset ids unencrypted and unfiltered and show no drop at all; the Agent-v2
path faces the same situation and *does* warn; the snippet path does not encrypt in the first place.
RAG-pipeline DSL import, originally listed only to bound the claim, turned out on testing
(2026-09-04, re-confirmed on 1.17.1) to have the **same drop** — structurally identical, and worse
in three ways: its export encryption is unconditional (no flag turns it off); its decoder has
neither a plain-UUID short circuit nor post-decrypt UUID validation; and its import response has no
`warnings` field to report into at all, even in principle. A repo-wide sweep at 1.17.1 confirms
the survey found exactly these two silent-drop implementations. Those greps are syntactic, so
"none was found" is what the evidence supports, not "no third exists". The claim is therefore: workflow / advanced-chat
apps with a `knowledge-retrieval` node, gated by `DSL_EXPORT_ENCRYPT_DATASET_ID` at its default of
`true`; **and**, separately, RAG-pipeline DSL with a `knowledge-retrieval` node, which is not
gated by that flag at all.

The mechanism is not a bug in the encryption — the per-tenant key derivation is a deliberate
workspace-scoping decision, and this analysis does not propose weakening it. (It is a scoping
mechanism, not the access check: authorisation is the tenant-filtered query at
`dataset_retrieval.py:2083`, which holds regardless of what a DSL claims.) The gap is that the
**failure to resolve the reference is not reported**, even though upstream already ships the exact
channel for reporting it (`ImportStatus.COMPLETED_WITH_WARNINGS` / `DslImportWarning`) and already
uses it for **six** other classes of unresolvable reference — including, on a sibling path, a
knowledge dataset that cannot be resolved in the target workspace.

Upstream's own cross-tenant bulk mover (`api/services/data_migration/`) delegates to the affected
carrier and then discards the warning channel outright, so the loss would stay invisible there even
if the import branch were fixed.

Precise anchors, and the parts of the above that are verified versus inferred, are in
`docs/upstream-facts.md`. Nothing in this README should be quoted without checking that file
first — the ledger is authoritative, the prose is not.

## Status

Re-verified against the current release. No upstream issue has been opened yet, and no patch has
been submitted. No upstream issue reporting this was found (searched 2026-09-18).
This repository is the deliverable in its own right; an upstream contribution, if it happens at
all, is a downstream option and is not assumed.
