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
From the repository root in PowerShell. PostgreSQL for this workspace listens on `127.0.0.1:55432`. Django reads the database name, user and password from `.env`. Do not run `scripts\local-db.ps1 -Action init` again once `.local\pgdata` exists. Details are in [local setup](docs/development.md).

```
scripts\local-db.ps1 -Action start
.venv\Scripts\python manage.py migrate
npm run build
.venv\Scripts\python manage.py runserver 127.0.0.1:8000
```

Leave that last window open. Stop the site with Ctrl+C. Stop PostgreSQL later with `scripts\local-db.ps1 -Action stop`. `migrate` only applies missing migrations; it does not wipe the database. `npm run build` rebuilds `static/css/app.css` after template or style changes. Skip it when the stylesheet is already built.

`scripts\check.ps1` runs Ruff, Django checks, a migration drift check and the PostgreSQL tests. Tests use a separate database and do not write into the company database.

Open http://127.0.0.1:8000/ for the Russian workplace and http://127.0.0.1:8000/admin/ for the technical admin.

Sign in with the superuser `admin`. Its password is the one already stored on that account; it is not kept in this repository. An active superuser can open both the workplace and `/admin/`.

A normal user is not a superuser and cannot open `/admin/`. The workplace allows that user only when the account is active and belongs to the Django group named `boss`. The group is an access switch for the business screens. It does not post documents by itself and it does not grant technical admin. Add the user to `boss` from `/admin/` under Groups, or in the Django shell with `user.groups.add(Group.objects.get_or_create(name="boss")[0])`. Anyone else who reaches a workplace URL gets the Russian “no access” page.
