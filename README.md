# LicenseHubK12

A software license management platform for K-12 school districts. IT, curriculum, and district administrators use it to track educational software licenses, contracts, vendors, per-school allocations, renewals, and spend — one place to answer *"what do we own, who's using it, and what needs renewing?"*

Built as part of the same suite as TrackItK12, AssistItK12, and AnalyticsK12, and follows their conventions (Flask app factory, Bootstrap 5 design tokens, `uv`-managed dependencies).

## Features

- **Dashboard** — district-wide license status, utilization, expiring licenses (30/60/90-day filters), recent activity, and color-coded alerts.
- **License management** — full CRUD with search, filtering, and server-side pagination; per-school allocation with a hard-enforced rule that allocations can never exceed a license's total license count.
- **License utilization** — per-license breakdown with a Chart.js chart of allocation by school.
- **Schools, vendors, and contracts** — full CRUD, following the district's real setup order (School → Vendor → Contract → License): contracts are created under a vendor and can bundle multiple license titles, with vendor pages rolling up spend and expiring licenses, and contracts tracking vendor contact and renewal/cancellation deadlines.
- **CSV import** — two-phase (preview, then commit) bulk import of license/allocation data; invalid rows are never written to the database.
- **Reports** — inventory, expiring licenses, utilization, spending (by contract/vendor), and school allocation, each exportable to CSV, Excel, and PDF.
- **Notifications** — generated for license/contract expirations, renewal deadlines, high/over utilization, and unused licenses.
- **Role-based access control** — Administrator, IT Administrator, Curriculum Administrator, School Administrator, and Viewer roles, enforced at the route-decorator level (not just hidden UI).
- **Audit log** — every create/update/delete records who, what, when, from where, and the field-level diff.
- **JSON API** — session- or bearer-token-authenticated endpoints for licenses, vendors, schools, and expiring-license queries, built for future SIS/Clever/Canvas integration.

## Screenshots

_placeholder — add screenshots of the dashboard, license detail, and reports pages here._

## Tech stack

- Python 3.13+, Flask (app factory pattern), Flask-SQLAlchemy, Flask-Login, Flask-WTF, Flask-Migrate/Alembic, Flask-Limiter, Flask-APScheduler (optional)
- SQLite for local development; MySQL/MariaDB in production via `DATABASE_URL`
- Bootstrap 5 + Bootstrap Icons + Jinja2, Chart.js
- `uv` for dependency management
- openpyxl / reportlab for Excel/PDF report exports

## Installation

This project uses [`uv`](https://docs.astral.sh/uv/) — not pip/venv — for dependency management.

```bash
uv sync
cp .env.example .env
# edit .env and set a real SECRET_KEY

uv run flask db upgrade
uv run flask seed        # optional: fictional demo district data
uv run flask run
```

Visit `http://127.0.0.1:5000`. (On macOS, port 5000 is often claimed by AirPlay Receiver — if the page doesn't load, run `uv run flask run --port 5050` instead, or disable AirPlay Receiver in System Settings.) If you ran `flask seed`, sign in with:

```
victor.solis@licensehubk12.example.org / ChangeMe!2026
```

### Guided setup (`installation/`)

For a real district instance rather than a local demo, use the interactive scripts under `installation/` — they generate `.env` for you and seed only the real baseline data (roles, categories, default thresholds, one admin user), with no fictional vendors/licenses:

```bash
uv sync
python installation/create_env.py   # generates .env - prompts to provision a MySQL DB, or skip for SQLite
python installation/seed_data.py    # applies migrations, then prompts for your admin email/password and district name
uv run flask run
```

`create_env.py` won't overwrite an existing `.env`. `seed_data.py` applies any pending migrations itself (via `flask_migrate.upgrade()` — the same mechanism as `flask db upgrade`) before seeding, so it works against a freshly provisioned, empty database without a separate migration step. Migrations remain the single source of truth for schema state either way — the seed script never uses `db.create_all()`.

## Environment configuration

Copy `.env.example` to `.env` and fill in the values relevant to your environment. Key variables:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session/CSRF signing key. Generate a real random value for anything beyond local dev. |
| `DATABASE_URL` | SQLAlchemy connection string. Omit for a local SQLite file under `instance/`. For production, e.g. `mysql+pymysql://user:pass@host:3306/licensehubk12`. |
| `SESSION_COOKIE_SECURE` / `REMEMBER_COOKIE_SECURE` | Set `True` whenever serving over HTTPS (the default in `ProductionConfig`). |
| `SESSION_TIMEOUT_MINUTES` | Idle session lifetime. |
| `SYNERGY_*`, `CLEVER_*`, `CANVAS_*` | Optional integrations — each stays fully disabled until its `*_ENABLED` flag and credentials are set. |
| `UPLOAD_FOLDER`, `MAX_CONTENT_LENGTH_MB` | CSV import upload handling. |

Never commit `.env`.

## Database setup & migrations

Schema changes are managed with Flask-Migrate/Alembic — never hand-edit the database.

```bash
uv run flask db upgrade          # apply all pending migrations
uv run flask db migrate -m "..."  # after changing app/models.py
uv run flask db downgrade -1     # roll back one migration
```

## Seed data

```bash
uv run flask seed
```

Populates fictional sample data: five roles, category list, a small fictional district (5 schools + a district office), five vendors (IXL Learning, Curriculum Associates, Benchmark Education, Canvas/Instructure, Clever), five license titles with realistic allocations and contracts, and one demo user per role. Safe to re-run — it upserts rather than duplicating.

## Running locally

```bash
uv run flask run                 # dev server, http://127.0.0.1:5000
uv run flask run-checks          # run the automated expiration/utilization/renewal checks once
uv run pytest                    # test suite
```

`flask run-checks` is scheduler-agnostic (see `app/services/checks.py`) — wire it up with system cron, Windows Task Scheduler, Celery beat, or the built-in optional APScheduler job (`SCHEDULER_ENABLED=True` in config) without touching the check logic itself.

## Production deployment notes

- Set `FLASK_ENV=production` (or otherwise select `ProductionConfig`) so `DEBUG` is off, cookies are marked `Secure`, and error pages never leak stack traces.
- Point `DATABASE_URL` at MySQL/MariaDB and run `flask db upgrade` against it before first launch.
- Serve behind a WSGI server (`gunicorn` is already a dependency): `uv run gunicorn -w 4 -b 0.0.0.0:8000 run:app`.
- Put a reverse proxy (nginx, etc.) in front for TLS termination and static file caching.
- Logs are written to rotating files under `instance/logs/` — ship these to your log aggregator of choice.
- If using the optional in-process scheduler, run only one worker with `SCHEDULER_ENABLED=True` to avoid duplicate notification runs; otherwise drive `flask run-checks` from an external scheduler.

## Security considerations

- Passwords are hashed with Werkzeug's `generate_password_hash` (PBKDF2/scrypt) — never stored or logged in plaintext.
- CSRF protection is enabled globally (Flask-WTF `CSRFProtect`); every form includes a token.
- RBAC is enforced at the route-decorator level (`app/utils/decorators.py`), not just by hiding UI — verified directly in `tests/test_rbac.py`.
- The JSON API requires a per-user bearer token for any state-changing request; a browser session alone can never be leveraged for a cross-site write against it.
- Login is rate-limited and accounts lock temporarily after repeated failed attempts.
- CSV imports are validated field-by-field before any database write; invalid rows are never imported, and uploaded files are never trusted for their filename or extension.
- All database access goes through the SQLAlchemy ORM — no raw SQL string interpolation.
- Every create/update/delete is written to the audit log with a field-level diff, the acting user, and their IP address.

## Project layout

```text
app/
  routes/          Flask blueprints (one per feature area)
  services/        business logic: status calculation, allocation rules, audit, notifications, automated checks
  integrations/    pluggable external-system connectors (Synergy, Clever, Canvas, CSV import)
  utils/           RBAC decorators, API auth, exports, template filters
  templates/       Jinja2 templates, organized to match the blueprints
  static/          CSS (Bootstrap 5 + design tokens), JS, images
  models.py        SQLAlchemy models
  forms.py         WTForms forms
migrations/        Alembic migration history
installation/      create_env.py (generates .env) and seed_data.py (baseline roles/categories/admin user)
tests/             pytest suite
```

See `CLAUDE.md` for a day-to-day reference on working in this codebase.
