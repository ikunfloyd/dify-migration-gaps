# Third-party material

This repository quotes source from [`langgenius/dify`](https://github.com/langgenius/dify) and
ships a patch against it. Dify is licensed under a modified Apache License 2.0 with additional
conditions; the full text as published at the pinned revision is reproduced below, per Apache
License 2.0 section 4(a).

## What is quoted, and from where

All excerpts are from `langgenius/dify`. Each is identified in place by file and line. No complete
upstream file is reproduced; the longest single excerpt is ten lines.

| Where in this repo | Upstream file | Lines | Revision |
|---|---|---|---|
| `docs/issue-draft.md` | `api/services/app_dsl_service.py` | 9 | `8387590` (tag 1.17.1) |
| `docs/issue-draft.md` | `api/services/rag_pipeline/rag_pipeline_dsl_service.py` | 10 | `8387590` |
| `docs/issue-draft.md` | `api/core/rag/retrieval/dataset_retrieval.py` | 3 | `8387590` |
| `fix/0001-report-dropped-knowledge-references.patch` | `api/services/app_dsl_service.py` | 18 context | `f4602cc` (`main`, 2026-09-25) |
| `fix/0001-report-dropped-knowledge-references.patch` | `api/tests/unit_tests/services/test_app_dsl_service.py` | 6 context | `f4602cc` |

Plus short quoted identifiers and docstrings cited inline throughout `docs/` and `baselines/`.

The patch file modifies `api/services/app_dsl_service.py` and
`api/tests/unit_tests/services/test_app_dsl_service.py`; the diff itself states what changed, per
Apache License 2.0 section 4(b). Upstream ships no `NOTICE` file, so section 4(d) does not apply.

Everything in this repository that is *not* an excerpt — the analysis, the reproduction scripts,
the captured evidence — is the author's own work and is MIT-licensed. See `LICENSE`.

## Dify's licence

Reproduced from `LICENSE` at `langgenius/dify`, revision `8387590ace4a094de812b7847fc6a4c3a27cd52b`
(tag 1.17.1). Check upstream for the current text before relying on it.

```
# Open Source License

Dify is licensed under a modified version of the Apache License 2.0, with the following additional conditions:

1. Dify may be utilized commercially, including as a backend service for other applications or as an application development platform for enterprises. Should the conditions below be met, a commercial license must be obtained from the producer:

a. Multi-tenant service: Unless explicitly authorized by Dify in writing, you may not use the Dify source code to operate a multi-tenant environment.
    - Tenant Definition: Within the context of Dify, one tenant corresponds to one workspace. The workspace provides a separated area for each tenant's data and configurations.

b. LOGO and copyright information: In the process of using Dify's frontend, you may not remove or modify the LOGO or copyright information in the Dify console or applications. This restriction is inapplicable to uses of Dify that do not involve its frontend.
    - Frontend Definition: For the purposes of this license, the "frontend" of Dify includes all components located in the `web/` directory when running Dify from the raw source code, or the "web" image when running Dify with Docker.

2. As a contributor, you should agree that:

a. The producer can adjust the open-source agreement to be more strict or relaxed as deemed necessary.
b. Your contributed code may be used for commercial purposes, including but not limited to its cloud business operations.

Apart from the specific conditions mentioned above, all other rights and restrictions follow the Apache License 2.0. Detailed information about the Apache License 2.0 can be found at http://www.apache.org/licenses/LICENSE-2.0.

The interactive design of this product is protected by appearance patent.

© 2025 LangGenius, Inc.
```

The full Apache License 2.0 that the above incorporates is at
<https://www.apache.org/licenses/LICENSE-2.0>.
