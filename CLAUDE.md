# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This App Is

**LicenseHubK12** is a K-12 school district software license management platform. It tracks educational software licenses, vendors, contracts, and per-school allocations, and answers: what licenses does the district own, how many are in use, which schools have them, what's being spent, and what's coming up for renewal. Role-based access control is built in at the route level (not bolted on), CSV import is two-phase (preview then commit), and every mutation is audit-logged.

---

## Running the App

```bash
uv run flask run                 # dev server, http://127.0.0.1:5000
uv run flask db upgrade          # apply migrations (run this first on a fresh clone)
uv run flask seed                # optional fictional demo data
uv run flask run-checks          # run the expiration/utilization/renewal notification checks once
uv run pytest                    # test suite
```

Dependencies are managed with `uv`, not pip/venv:

```bash
uv sync
uv add <package>
```

---

## Database

SQLite locally (`instance/licensehubk12.db`), MySQL/MariaDB in production via `DATABASE_URL`. Flask-Migrate/Alembic manages all schema changes — never hand-edit the database or use `db.create_all()` outside of tests.

```bash
uv run flask db migrate -m "description"   # after changing app/models.py
uv run flask db upgrade                    # apply pending migrations
uv run flask db downgrade -1               # roll back one migration
```

Migration files live in `migrations/versions/`. After changing a model, always run `migrate` then `upgrade`.

---

## Architecture

### App Factory

`app/__init__.py` has `create_app(config_name)`. It initializes extensions (`app/extensions.py`: SQLAlchemy, Migrate, Login, CSRFProtect, Limiter), registers one blueprint per feature area, wires error handlers, CLI commands (`seed`, `run-checks`), template filters, and the optional in-process scheduler.

### Blueprints (`app/routes/`)

One blueprint per feature area, matching the nav structure: `auth`, `dashboard`, `licenses` (License CRUD, allocations, categories), `imports` (CSV upload/preview/commit), `vendors`, `schools`, `contracts`, `reports`, `users`, `settings`, `notifications`, `audit`, `api`.

`licenses.py` covers what the original spec called "software" and "license" — in this data model a `License` row *is* the license pool for that title (see Models below), so there's one blueprint rather than two nearly-identical ones. The app was originally scaffolded with a `Software` model; it was fully renamed to `License` (table, columns, routes, URLs) — don't reintroduce "software" naming anywhere in new code.

### RBAC (`app/utils/decorators.py`)

Every mutating or sensitive route is guarded with `@permission_required("<permission>")`, which checks `current_user.has_role(...)` against the `PERMISSIONS` dict — the single source of truth for which of the five roles (Administrator, IT Administrator, Curriculum Administrator, School Administrator, Viewer) can do what. Add a new permission there before using it in a route; don't inline role checks in views. School Administrators are further scoped to their own school's data via `scope_to_school()` and manual `school_id` filters in list/detail views — this is enforced in the route/query layer, never left to the template to hide.

### License Allocation Invariant (`app/services/allocation.py`)

The rule "a license's per-school allocations can never exceed its district license count" lives in `allocation.set_allocation()`, not in a form validator. Every write path — the web UI, CSV import (`app/integrations/csv_import.py`), and any future API/integration — must go through this function so the invariant can't be bypassed. See `tests/test_licenses.py::test_allocation_cannot_exceed_district_total`.

### License Status (`app/services/status.py`)

Expired/Critical/Warning/Upcoming/Active is computed from `expiration_date` and admin-configurable thresholds stored in the `Setting` table (`app/routes/settings.py`), not hardcoded. `compute_expiration_status()` is the one place this logic lives; badge colors come from `status_badge_class()`/`status_label()`, registered as Jinja globals — never hardcode a Bootstrap color class for a status in a template.

### Automated Checks (`app/services/checks.py`)

`run_all_checks()` is scheduler-agnostic: it's called identically by `flask run-checks`, the optional APScheduler job (`app/services/scheduler.py`, gated by `SCHEDULER_ENABLED`), or an external cron/Task Scheduler/Celery job. It creates `Notification` rows for expirations, contract deadlines, high/over utilization, and unused licenses, de-duplicating same-day repeats per object.

Note: because `allocation.py` hard-caps allocations at `license_count`, utilization can only exceed 100% if `license_count` was *reduced* after allocations were already made — the `over_allocated` check uses strict `>`, not `>=`, so a title sitting at exactly 100% (fully but validly subscribed) doesn't get flagged as a problem.

### Models (`app/models.py`)

| Model | Notes |
|---|---|
| `License` | `__tablename__ = "licenses"` — one row is one license title's pool (`license_count` seats total). `assigned_licenses`, `available_licenses`, `utilization_pct`, `cost_per_license`, `unused_license_cost` are computed `@property`s from `license_count` and its `allocations`, not stored columns. `annual_cost`, `vendor_contact` are also computed properties, sourced from the license's current `Contract` (see below) — don't add columns for any of these; don't filter SQL on them. |
| `LicenseAllocation` | Per-school breakdown of a `License`'s `license_count`. FK column is `license_id` (not `software_id`). One row per (license, school) pair, enforced by the `uq_allocation_license_school` unique constraint. Never insert/update directly — use `app/services/allocation.py`. |
| `User` | `role` (FK to `Role`), `school_id` (only meaningful for School Administrator). `api_key` is a bearer token for the JSON API, separate from the session cookie. |
| `Setting` | Generic key/value store for admin-configurable thresholds (`critical_days`, `warning_days`, `upcoming_days`, `high_utilization_pct`, `over_allocated_pct`). Read via `Setting.get_int(key, default)`. |
| `Contract` | FK column is `license_id`. `po_number` is the one identifying number for a contract (no separate contract number). `license_type` doesn't exist — the feature was removed entirely, not just relocated. Vendor is derived from `license.vendor_id` at creation, never picked separately. |
| `AuditLog` | `changes_json` holds a `{field: {"from": x, "to": y}}` diff, written via `app/services/audit.py::diff_changes()`. |
| Datetime columns | Stored as **naive UTC** everywhere (`app.models.utcnow()` strips tzinfo before returning). SQLite round-trips `DateTime(timezone=True)` values as naive regardless of how they were written, so comparing against an aware `datetime.now(timezone.utc)` raises `TypeError`. Keep every new datetime column plain `db.DateTime` and every comparison against naive `utcnow()`. |

### JSON API (`app/routes/api.py`, `app/utils/api_auth.py`)

GET requests accept either the normal session cookie or a bearer token. Any state-changing request (POST/PUT/DELETE) *requires* `Authorization: Bearer <User.api_key>` — a logged-in browser session alone is never sufficient for a write, so the API blueprint can safely be CSRF-exempted (`csrf.exempt(api_bp)` in `app/__init__.py`) without opening a cross-site-write hole. Use `api_user()` inside API views to get the effective caller, not `current_user` directly.

### CSRF

Flask-WTF's `CSRFProtect` is applied globally, so **every** raw `<form method="post">` needs a token even outside a WTForms `form.hidden_tag()` — add `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` by hand to any form built without a WTForms object (see `licenses/detail.html`'s delete/allocation-removal forms for the pattern). Missing this produces a 400, not a redirect, so it's easy to miss in manual testing if you don't click the actual button.

### Templates (`app/templates/`)

- `base.html` — full app shell (sidebar + topbar), used by all authenticated pages.
- `base_bare.html` — centered card layout with no nav, used by `login.html`, password reset, and `errors/*.html` (so a 403/404 renders sensibly for a logged-out visitor).
- `includes/macros.html` — `field()` macro renders one Bootstrap-styled WTForms field with error display; use it in every form template instead of hand-rolling `<input>` markup.
- `includes/pagination.html` / `includes/export_buttons.html` — build merged query-arg dicts for `url_for()`. Jinja's expression grammar rejects `dict(a, **b, key=c)` (positional arg + `**kwargs` + another kwarg together) — build the merged dict in a `{% set %}` first, then pass it as `**dict(that, key=c)`.

### CSS

`app/static/css/style.css` follows the AnalyticsK12 token convention: `--bs-main-color-*`, `--color-*`, `--status-*` custom properties defined once under `:root, [data-bs-theme=light]`. Status badge colors come only from the `.status-active/.status-warning/.status-critical/.status-expired/.status-upcoming` classes — never hardcode a hex color for status in a template or inline style.

---

## Key Conventions

- **Don't add a `status` column meaning for the countdown to expiration.** `License.status` is the *administrative* lifecycle field (Active/Suspended/Pending Renewal/Cancelled), independent from the *computed* expiration status (Active/Upcoming/Warning/Critical/Expired) from `app/services/status.py`. Both appear in the UI but are different concepts — check which one a given badge/filter is supposed to reflect.
- **The model is `License`, not `Software`.** Table `licenses`, FK columns `license_id` everywhere (`Contract.license_id`, `LicenseAllocation.license_id`), routes under `/licenses/*`, blueprint functions `list_licenses`/`add_license`/`view_license`/`edit_license`/`delete_license`. The app went through a full rename from an original `Software` model — if you see "software" in a diff or a new file, that's almost certainly a mistake to fix, not a pattern to follow. The one place "license" would collide awkwardly is naming a local Python variable `license` (shadows the builtin `license()`); this codebase uses `lic` in templates and `license_` in Python (services, fixtures) instead.
- **School-scoping is a query filter, not a template `{% if %}`.** Every list/detail view that a School Administrator can reach must filter at the SQLAlchemy query level (`join(LicenseAllocation).filter(LicenseAllocation.school_id == current_user.school_id)`), matching the pattern already in `licenses.py`, `dashboard.py`, and `reports.py`.
- **CSV import never partially trusts a row.** `app/integrations/csv_import.py` splits into `validate_csv()` (read-only, safe to call repeatedly for a preview) and `commit_import()` (the only function that writes, and it re-validates allocation limits against live DB state via `allocation.py` rather than trusting the preview). Don't add a code path that writes without going through both.
- **Integrations are opt-in stubs.** `app/integrations/{synergy,clever,canvas}.py` implement `IntegrationBase` and no-op unless their `*_ENABLED` config flag and credentials are all set. Don't call a vendor API directly from a route — go through the integration class.
