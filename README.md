# Mariam-Osh ERP

Phase 2 supply-to-stock is running locally. The Phase 0 design remains the business authority. Production, sack consumption, manual grain issue and write-offs are not built yet.

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

This directory is the repository root. The application name is ebb-erp. It stays isolated from ERPNext, and code and design stay in one repository. `main.py` is the original PyCharm sample, not ERP code.

## Run locally
PostgreSQL for this workspace listens on `127.0.0.1:55432`. Start it with `scripts\local-db.ps1 -Action start` when it is stopped. Details are in [local setup](docs/development.md).

```
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py seed_demo
npm run build
.venv\Scripts\python manage.py runserver
```

`scripts\check.ps1` runs Ruff, Django checks, a migration drift check and the PostgreSQL tests.

Open http://127.0.0.1:8000/ for the Russian workplace and http://127.0.0.1:8000/admin/ for the technical admin. The admin page is only for the superuser. Factory roles use the workplace.

These accounts and quantities are synthetic local demo data, not factory records:

- `admin` / `Demo-admin-1` — technical admin
- `supply` / `Demo-supply-1` — orders, prices, debt, amendments, demo payments, and wheat release
- `customs` / `Demo-customs-1` — shipments, wagons and customs charges, without supplier prices
- `storage` / `Demo-storage-1` — opening stock, goods receipts, local checks and stock corrections, without supplier prices

The seeded company is Мариам-Ош. The opening document is marked synthetic: 8,000 kg and 2,000 kg of wheat, and 500 empty sacks. Bran is in the catalogue only and has no stock balance.
