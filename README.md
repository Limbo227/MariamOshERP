# Mariam-Osh ERP

Phase 0 core design — updated 2026-11-10 from Bakai's annotated answers and follow-up decisions.
The design package is complete for the core build. No ERP application has been implemented or deployed.

**Read first:** [core scope and build sequence](docs/core-scope.md) → [business rules](docs/business-rules.md) → [visual diagrams](docs/diagrams/README.md) → [database design](docs/domain-model.md).

## Documentation map
- [Architecture and technology choices](docs/architecture.md), [stack ADR](docs/adr/0001-django-postgresql.md), [core-scope ADR](docs/adr/0002-core-production-scope.md).
- [Table dictionary](docs/data-dictionary.md), [procurement](docs/procurement-workflows.md), [manufacturing and inventory](docs/inventory-workflows.md).
- [Access rules](docs/roles-and-permissions.md), [decisions and assumptions](docs/domain-decisions.md), [remaining details](docs/open-questions.md).
- [Acceptance scenarios](docs/acceptance.md), [original requirement coverage](docs/requirements-coverage.md), [Phase 0 review](docs/phase-0-review.md).
- [Handoff for the next developer or AI agent](docs/handoff.md).

## Authority and folder structure
Later written owner answers override assumptions in the original brief. The root EBB_ERP_Mariam_Osh_Project_Brief_Cursor_v1.0.md and [archival brief](docs/00-project-brief.md) are unchanged historical sources. Current rules live in docs/business-rules.md.
Exact annotated input and prior design files are preserved in docs/history/2026-11-10-owner-input/. That snapshot is historical, not implementation guidance.

docs/ contains the maintained design; docs/adr/ records architectural decisions; docs/diagrams/ holds editable Mermaid/SVG sources and PNG previews; docs/history/ holds immutable evidence.
Existing .idea/, .venv/ and main.py are preserved. main.py is the original PyCharm sample, not ERP code.

Use this directory as the future repository root; the application/project name is ebb-erp. This supersedes the earlier suggestion to nest another repository and move documentation into it. The clean workspace is already isolated from ERPNext, and one repository keeps code and design together. Phase 1 will add config/, apps/, templates/, static/, tests/ and local setup files here, with isolated dependencies and synthetic fixtures.
