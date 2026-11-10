# Local setup

The application uses the PostgreSQL cluster already created for this workspace. Binaries are in `.local/postgres`, data is in `.local/pgdata`, and the server listens only on `127.0.0.1:55432`. Database name: `ebb_erp`. Credentials are in `.env`, which is not committed.

```
scripts\local-db.ps1 -Action start
scripts\local-db.ps1 -Action status
scripts\local-db.ps1 -Action stop
```

Do not run `-Action init` again once `.local/pgdata` exists. That command initialises a new cluster and will refuse if one is already present.

From the repository root, with the virtual environment:

```
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py seed_demo
npm run build
.venv\Scripts\python manage.py runserver
```

`npm run build` writes `static/css/app.css` and copies HTMX into `static/vendor`. `seed_demo` is safe to repeat: it does not post the synthetic opening balance a second time.

`scripts\check.ps1` is the repeatable check: Ruff, Django system check, migration drift, and pytest against PostgreSQL. Pytest creates `test_ebb_erp` and does not write the demo rows into `ebb_erp`.
