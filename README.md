# Mariam-Osh ERP

Supply, stock and supplier debt run locally. Production screens are not part of the workplace yet.

**Read first:** [overview](docs/overview.md) → [functional rules](docs/functional.md) → [database](docs/database.md).

`docs/overview.md`, `docs/functional.md` and `docs/database.md` describe the behavior the code posts now. `docs/EBB-Holding-2026/` stays as the November 2026 design archive. Where they disagree, those three files are the ones to follow.

This directory is the repository root. The application stays isolated from ERPNext. Code and these notes stay in one repository.

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
