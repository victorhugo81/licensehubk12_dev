<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="app/static/img/licensehubk12_dark.png">
    <source media="(prefers-color-scheme: light)" srcset="app/static/img/licensehubk12%20-%20White%20Logo.png">
    <img alt="LicenseHubK12" src="app/static/img/licensehubk12%20-%20White%20Logo.png" width="360">
  </picture>
</p>

# LicenseHubK12

A software license management platform for K-12 school districts. IT, curriculum, and district administrators use it to track educational software licenses, contracts, vendors, per-school allocations, renewals, and spend — one place to answer *"what do we own, who's using it, and what needs renewing?"*

Built as part of the same suite as TrackItK12, AssistItK12, and AnalyticsK12, and follows their conventions (Flask app factory, Bootstrap 5 design tokens, `uv`-managed dependencies).

## Features

- **Dashboard** — district-wide license status, utilization, expiring licenses (30/60/90-day filters), recent activity, and color-coded alerts.
- **License management** — full CRUD with search, filtering, and server-side pagination; per-school allocation with a hard-enforced rule that allocations can never exceed a license's total license count.
- **License utilization** — per-license breakdown with a Chart.js chart of allocation by school.
- **Schools, vendors, and contracts** — full CRUD, following the district's real setup order (School → Vendor → Contract → License): contracts are created under a vendor and can bundle multiple license titles, with vendor pages rolling up spend and expiring licenses, and contracts tracking vendor contact and renewal/cancellation deadlines. Each contract can also have the signed agreement (PDF or Word) attached, downloadable from its detail page.
- **CSV import** — two-phase (preview, then commit) bulk import of license/allocation data; invalid rows are never written to the database.
- **Bulk user import** — create many user accounts at once from a CSV file, or configure a scheduled FTP/FTPS pull that runs the same import automatically; new accounts get a password-set link instead of a visible temporary password (Settings > Bulk User Import).
- **Reports** — inventory, expiring licenses, utilization, spending (by contract/vendor), and school allocation, each exportable to CSV, Excel, and PDF.
- **Notifications** — generated for license/contract expirations, renewal deadlines, high/over utilization, unused licenses, and new licenses being added; each notification is clickable (marks it read and opens the license/contract it's about), and every category can be turned on/off independently (Settings > Notification Settings).
- **Role-based access control** — Administrator, IT Administrator, Curriculum Administrator, School Administrator, and Viewer roles, enforced at the route-decorator level (not just hidden UI). School Administrators can additionally create (but not edit/delete) vendors, contracts, and licenses, scoped to their own school.
- **Audit log** — every create/update/delete records who, what, when, from where, and the field-level diff.
- **JSON API** — session-authenticated read endpoints for licenses, vendors, schools, and expiring-license queries, built for future SIS/Clever/Canvas integration.

## Screenshots

_placeholder — add screenshots of the dashboard, license detail, and reports pages here._

## Tech stack

- Python 3.13+, Flask (app factory pattern), Flask-SQLAlchemy, Flask-Login, Flask-WTF, Flask-Migrate/Alembic, Flask-Limiter, Flask-Mail, Flask-APScheduler (optional)
- SQLite for local development; MySQL/MariaDB in production via `DATABASE_URL`
- Bootstrap 5 + Bootstrap Icons + Jinja2, Chart.js
- `uv` for dependency management
- openpyxl / reportlab for Excel/PDF report exports
- `cryptography` for encrypting the FTP import password at rest; `redis` (optional) for shared rate-limit storage across multiple gunicorn workers

## Installation

This project uses [`uv`](https://docs.astral.sh/uv/) — not pip/venv — for dependency management.

```bash
uv sync
cp .env.example .env
# edit .env: set a real SECRET_KEY (the app won't start without one) -
# APP_ENV=development is already set for local use

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

- Set `APP_ENV=production` so `ProductionConfig` is selected (`DEBUG` off, cookies marked `Secure`, error pages never leak stack traces). The app now refuses to start if `APP_ENV` is unset, or if `production` is selected without a `SECRET_KEY` - it will not silently fall back to development settings.
- Set `BEHIND_PROXY=true` if serving behind nginx/another reverse proxy (the documented setup below) so `ProxyFix` reads the real client IP from `X-Forwarded-*` headers - without it, rate limiting and audit-log IP addresses only ever see the proxy's own address.
- Point `DATABASE_URL` at MySQL/MariaDB and run `flask db upgrade` against it before first launch.
- Serve behind a WSGI server (`gunicorn` is already a dependency): `uv run gunicorn -w 4 -b 0.0.0.0:8000 run:app`.
- Put a reverse proxy (nginx, etc.) in front for TLS termination and static file caching.
- Logs are written to rotating files under `instance/logs/` — ship these to your log aggregator of choice.
- If using the optional in-process scheduler, run only one worker with `SCHEDULER_ENABLED=True` to avoid duplicate notification runs; otherwise drive `flask run-checks` from an external scheduler.
- If running more than one gunicorn worker (`-w > 1`), point `RATELIMIT_STORAGE_URI` at a shared store (e.g. `redis://host:6379/0`) instead of the default `memory://` — each worker enforces rate limits independently otherwise, multiplying every limit (including login brute-force protection) by the worker count. `redis` is already a project dependency for this.
- Set `MAIL_SERVER`/`MAIL_USERNAME`/`MAIL_PASSWORD`/`MAIL_DEFAULT_SENDER` so password-reset links are actually emailed (`app/services/mailer.py`); without it, resets fall back to an admin-visible log line that never includes the token itself.

## Security considerations

- Passwords are hashed with Werkzeug's `generate_password_hash` (PBKDF2/scrypt) — never stored or logged in plaintext. New/changed passwords are also checked against a short list of common/breached passwords (`app/forms.py::not_common_password`).
- CSRF protection is enabled globally (Flask-WTF `CSRFProtect`); every form includes a token.
- RBAC is enforced at the route-decorator level (`app/utils/decorators.py`), not just by hiding UI — verified directly in `tests/test_rbac.py`.
- The JSON API authenticates via the same session cookie as the rest of the app and is subject to standard CSRF protection, so a state-changing request needs an authenticated same-origin session with a valid CSRF token — it isn't reachable as a bare external API.
- Login is rate-limited and accounts lock temporarily after repeated failed attempts; the lockout message is identical to a normal failed login (no distinct "this account is locked" text) and every failed attempt costs one password-hash comparison (real or dummy), so neither the message nor response time reveals whether an email is registered.
- The post-login `?next=` redirect only ever follows a same-site relative path — protocol-relative URLs (`//evil.example`) are rejected, not just anything starting with `/`.
- Changing or resetting a password rotates `User.security_stamp`, which is embedded in the session id (`User.get_id()`) - any other already-issued session cookie for that account stops working immediately, closing the "someone has my session, so I reset my password" gap that stateless signed-cookie sessions otherwise leave open.
- Every response carries `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, a `Content-Security-Policy` (script tags use a fresh per-request nonce, not `unsafe-inline`), and `Strict-Transport-Security` when cookies are secure (`app/__init__.py::_register_security_headers`).
- Deploying behind a reverse proxy requires `BEHIND_PROXY=true` so `ProxyFix` reads the real client IP - without it, per-IP rate limiting and the audit log's IP column only ever see the proxy's own address.
- CSV imports are validated field-by-field before any database write; invalid rows are never imported, uploaded files are never trusted for their filename or extension, and each import is capped at 20,000 rows regardless of file size.
- CSV/Excel report exports neutralize any cell that starts with `=`, `+`, `-`, `@`, a tab, or a carriage return (`app/utils/exports.py`), preventing formula/DDE injection when a report is later opened in Excel/Sheets.
- All database access goes through the SQLAlchemy ORM — no raw SQL string interpolation.
- Every create/update/delete is written to the audit log with a field-level diff, the acting user, and their IP address.
- `flask seed` (fictional demo data with a well-known password) refuses to run against `APP_ENV=production`; use `python installation/seed_data.py` for a real district instance.

## Project layout

```text
app/
  routes/          Flask blueprints (one per feature area)
  services/        business logic: status calculation, allocation rules, audit, notifications, automated checks, email
  integrations/    pluggable external-system connectors (Synergy, Clever, Canvas, CSV import, FTP user import)
  utils/           RBAC decorators, API auth, exports, template filters, encryption helpers
  templates/       Jinja2 templates, organized to match the blueprints
  static/          CSS (Bootstrap 5 + design tokens), JS, images
  models.py        SQLAlchemy models
  forms.py         WTForms forms
migrations/        Alembic migration history
installation/      create_env.py (generates .env) and seed_data.py (baseline roles/categories/admin user)
tests/             pytest suite
```

See `CLAUDE.md` for a day-to-day reference on working in this codebase.

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
