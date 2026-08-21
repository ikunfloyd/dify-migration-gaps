# dify-migration-gaps

Reproducible failure modes when moving a [Dify](https://github.com/langgenius/dify) application
between environments (or between workspaces), pinned to **v1.16.0**.

This is an independent analysis. Every claim here is backed by one of exactly two things:

1. a **permalink into upstream source at a pinned commit**, or
2. a **from-zero reproduction log** produced on a clean stack on my own machine.

Nothing else is admissible. In particular this repository contains no material from any
employer, no third-party application definitions, and no customer data.

## Upstream baseline

| | |
|---|---|
| Repository | `langgenius/dify` |
| Commit | `5c6372d2f76d240265b92fd27c16bc772ffcb107` — *chore: bump version to 1.16.0 (#39196)* |
| Version | 1.16.0 |
| Read on | 2026-08-21 |

All line-number anchors in `docs/` refer to that commit. Line numbers drift; the commit does not.

## What is in here

| Path | What it is |
|---|---|
| `docs/upstream-facts.md` | Fact ledger — each claim graded *confirmed / drifted / refuted / unverified*, with its anchor |
| `docs/repro-log.md` | From-zero reproduction log, timestamped. **First line carries the kill date.** |
| `evidence/` | Raw captured artifacts (HTTP responses, exported DSL, container state) |
| `scripts/` | Scripts that drive the reproduction, so a reader can rerun it |

## The gap this starts with

Export a **workflow** (or advanced-chat) app containing a `knowledge-retrieval` node, then import it
under a **different tenant**. The node's `dataset_ids` come back empty, and the import reports
`status: "completed"` with `warnings: []`. Nothing tells the caller that a reference was discarded.

Scope matters here, and three of the four carriers behave differently: chat / agent-chat /
completion apps carry dataset ids unencrypted and unfiltered and show no drop at all; the Agent-v2
path faces the same situation and *does* warn; the snippet path does not encrypt in the first place.
The claim is therefore narrow — workflow-family apps, `knowledge-retrieval` nodes, with
`DSL_EXPORT_ENCRYPT_DATASET_ID` at its default of `true`.

The mechanism is not a bug in the encryption — the per-tenant key derivation is a deliberate
isolation boundary, and this analysis does not propose weakening it. The gap is that the
**failure to resolve the reference is not reported**, even though upstream already ships the exact
channel for reporting it (`ImportStatus.COMPLETED_WITH_WARNINGS` / `DslImportWarning`, already
produced elsewhere in the codebase and already rendered by the web client).

Precise anchors, and the parts of the above that are verified versus inferred, are in
`docs/upstream-facts.md`. Nothing in this README should be quoted without checking that file
first — the ledger is authoritative, the prose is not.

## Status

Analysis in progress. No upstream issue has been opened yet, and no patch has been submitted.
This repository is the deliverable in its own right; an upstream contribution, if it happens at
all, is a downstream option and is not assumed.
