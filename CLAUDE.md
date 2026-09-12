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

One blueprint per feature area, matching the nav structure: `auth`, `dashboard`, `licenses` (License CRUD, allocations, categories), `imports` (CSV upload/preview/commit for licenses), `user_imports` (bulk user provisioning — manual CSV or scheduled FTP, see below), `school_imports` (bulk school provisioning via CSV, see below), `bulk_imports` (combined users+schools import page, the linked-to entry point for both — see below), `vendors`, `schools`, `contracts`, `reports`, `users`, `settings`, `notifications`, `audit`, `api`.

`licenses.py` covers what the original spec called "software" and "license" — in this data model a `License` row *is* the license pool for that title (see Models below), so there's one blueprint rather than two nearly-identical ones. The app was originally scaffolded with a `Software` model; it was fully renamed to `License` (table, columns, routes, URLs) — don't reintroduce "software" naming anywhere in new code.

### RBAC (`app/utils/decorators.py`)

Every mutating or sensitive route is guarded with `@permission_required("<permission>")`, which checks `current_user.has_role(...)` against the `PERMISSIONS` dict — the single source of truth for which of the five roles (Administrator, IT Administrator, Curriculum Administrator, School Administrator, Viewer) can do what. Add a new permission there before using it in a route; don't inline role checks in views. School Administrators are further scoped to their own school's data via `scope_to_school()` and manual `school_id` filters in list/detail views — this is enforced in the route/query layer, never left to the template to hide.

School Administrator has narrower `add_vendors`/`add_contracts`/`add_licenses` permissions distinct from the broader `manage_vendors`/`manage_contracts`/`manage_licenses` (which stay Administrator/IT [/Curriculum for licenses] only) — they can create a new vendor, contract, or license, but can't edit or delete any of them. `licenses.add_license()` auto-allocates a School Administrator's newly created license entirely to their own school (`allocation_service.set_allocation`) since they have no access to the manual allocation routes to allocate it themselves or to any other school. When adding a template button/link for one of these add-only actions, gate it on `current_user.has_role(..., 'School Administrator')` to match — the edit/delete buttons next to it should NOT include School Administrator.

### License Allocation Invariant (`app/services/allocation.py`)

The rule "a license's per-school allocations can never exceed its district license count" lives in `allocation.set_allocation()`, not in a form validator. Every write path — the web UI, CSV import (`app/integrations/csv_import.py`), and any future API/integration — must go through this function so the invariant can't be bypassed. See `tests/test_licenses.py::test_allocation_cannot_exceed_district_total`.

### License Status (`app/services/status.py`)

Expired/Critical/Warning/Upcoming/Active is computed from `expiration_date` and admin-configurable thresholds stored in the `Setting` table (`app/routes/settings.py`), not hardcoded. `compute_expiration_status()` is the one place this logic lives; badge colors come from `status_badge_class()`/`status_label()`, registered as Jinja globals — never hardcode a Bootstrap color class for a status in a template.

### Automated Checks (`app/services/checks.py`)

`run_all_checks()` is scheduler-agnostic: it's called identically by `flask run-checks`, the optional APScheduler job (`app/services/scheduler.py`, gated by `SCHEDULER_ENABLED`), or an external cron/Task Scheduler/Celery job. It creates `Notification` rows for expirations, contract deadlines, high/over utilization, and unused licenses, de-duplicating same-day repeats per object.

Note: because `allocation.py` hard-caps allocations at `license_count`, utilization can only exceed 100% if `license_count` was *reduced* after allocations were already made — the `over_allocated` check uses strict `>`, not `>=`, so a title sitting at exactly 100% (fully but validly subscribed) doesn't get flagged as a problem.

### Notification categories (`app/services/notifications.py`, Settings > Notification Settings)

Every call to `notify(type_, ...)` is gated by `NOTIFICATION_CATEGORIES` — a registry mapping each raw `type_` string (`license_expiration`, `contract_expiration`, `unused_licenses`, ...) to one admin-facing on/off toggle (a `Setting` row, default enabled). This is the single choke point: `checks.py`'s check functions never need their own enabled/disabled logic, and neither does any other caller — add a new notification type by adding one entry to `NOTIFICATION_CATEGORIES`, not by special-casing it at each call site. `license_added` fires from all three places a `License` can be created (`licenses.add_license`, `csv_import.py::commit_import`, `api.create_license`) — add the same `notifications.notify("license_added", ...)` call to any new license-creation path, or it'll silently be invisible to this toggle. `NotificationSettingsForm` in `app/forms.py` has one `BooleanField` per category, named to match `NOTIFICATION_CATEGORIES`' `key` exactly — the settings route iterates the registry rather than listing each field twice.

Every notification is clickable: `Notification.link_url` (a model `@property`, only valid inside a request/app context since it calls `url_for`) maps `related_object_type`/`related_object_id` ("license"/"contract") to that object's detail page. `notifications.mark_read()` redirects there after marking read — add the matching branch to `link_url` for any new `related_object_type`, or notifications of that kind will render as a dead click that just reloads the list.

### Bulk User Import (`app/routes/user_imports.py`, `app/integrations/user_csv_import.py`, `app/integrations/ftp_users.py`)

Two ways to provision many `User` accounts at once, both Administrator-only (`manage_users` — no separate "add-only" permission, unlike vendors/contracts/licenses, because creating a login is inherently sensitive):

- **Manual CSV** (`/administration/users/import/`) — same two-phase shape as the license importer: `validate_csv()` is read-only and safe to call repeatedly for a preview; `commit_import()` is the only function that writes, and it re-checks each email against live DB state at commit time (not just the preview snapshot) so a race can't create a duplicate account. The standard district roster export has exactly `first_name,middle_name,last_name,email,site_name,status` — no `role` column at all — and any other column present is simply ignored (`csv.DictReader` never looks at keys nobody reads). **`email` is the match key**: a row whose email already exists updates that user's `first_name`/`middle_name`/`last_name`/`status`/`site_name` instead of creating a duplicate — but **`role` is never changed for an existing user**, a CSV re-upload is not a path to grant or revoke admin access. A `role` column is still accepted for creating a new user deliberately with an elevated role; when absent (or blank), a brand-new user defaults to `Role.VIEWER` (`DEFAULT_ROLE` in `user_csv_import.py`) — the least-privileged role, matching this codebase's default-to-safe posture elsewhere. `site_name` sets `User.school_id` for **any** role (it's just a "what site is this person at" fact — see the `School` model's Users-page display), except when the row is creating a new School Administrator, where a valid `site_name` is still required (that role's own scoping breaks everywhere if `school_id` is null). `commit_import()` returns `(created, updated, results)` — `ImportHistory.kind="user"` records `created`/`updated` counts, matching the schools importer's shape (not a `created`/`skipped` pair).
- **Scheduled FTP** (`/administration/users/import/ftp`, `FtpImportSettings` model) — a single-row config (host/port/username/password/remote_path/use_tls) that `FtpUsersIntegration.sync()` (an `IntegrationBase` implementation, like Synergy/Clever/Canvas) uses to pull one CSV file and run it through the *same* `validate_csv()`/`commit_import()` pair — there is exactly one user-import code path, FTP just supplies the file instead of a human uploading it. Runs on a daily APScheduler cron job (`app/services/scheduler.py`) when `SCHEDULER_ENABLED` and `FtpImportSettings.is_configured()` are both true, or on demand via the "Run import now" button.

Security invariants specific to this feature — don't relax either without a good reason:
- **No temporary password is ever generated, stored, or shown.** A bulk-created user gets `set_password(secrets.token_urlsafe(32))` (a value nobody, including the admin, ever sees) plus an immediate `reset_token` (7-day expiry, same mechanism as "forgot password" in `auth.py`). The only way into the account is for the person to set their own password via that link. Don't switch this to a visible/emailed temporary password.
- **`FtpImportSettings.password` is Fernet-encrypted at rest** (`app/utils/crypto.py`, key derived from `SECRET_KEY`) via a `password`/`password_encrypted` property pair — never add a plaintext password column, and never populate the FTP settings form's password field from storage (even decrypted) when rendering the edit page; leaving it blank means "keep the current password" (see the `GET` branch in `ftp_settings()`).
- Saving FTP settings with `use_tls` off flashes an explicit cleartext-transmission warning. Don't remove it.
- `ImportHistory.kind` (`"license"` default, or `"user"`) discriminates which importer wrote a row — one history table, not a near-duplicate per import type.

### Bulk School Import (`app/routes/school_imports.py`, `app/integrations/school_csv_import.py`)

Same two-phase shape again, at `/administration/schools/import/`, gated by `manage_schools` (Administrator/IT Administrator). Expected columns match the district's sites.csv export format: `site_name,site_acronyms,site_cds,site_code,site_address,sitecity,sitestate,sitezip,prnfirstn,prnlastn,email,phone,site_type` (`site_name`/`site_code`/`site_type` required; `grades`/`student_count` are also accepted if present but aren't part of the standard export). These map onto `School` columns `name`/`acronym`/`cds_code`/`code`/`address`/`city`/`state`/`zip_code`/`school_type`, with `prnfirstn`+`prnlastn` combined into the single `principal` column — the CSV header names are the external/import-only vocabulary, not the model's field names. `site_type` also accepts the shorthand `ES`/`MS`/`HS` (case-insensitive), normalized to `School.TYPES`' `Elementary`/`Middle School`/`High School` by `_normalize_school_type()` before validation — add any new shorthand there, not as a special case elsewhere. Unlike the user importer, **`site_code` is a match key, not a duplicate check that skips the row** — a row whose code already exists in the DB updates that school's fields (matching how the license CSV importer treats a repeat `license` name), so re-uploading a refreshed school directory naturally syncs it rather than erroring out. `ImportHistory.kind="school"` records `created`/`updated` counts, the same shape the user importer uses. There is no FTP variant for schools (only users/FTP exists) — add one the same way as `ftp_users.py` if that's ever needed, rather than bolting FTP support onto the user importer's integration class. This standalone page still exists and is fully functional, but the combined Bulk Import page below is the linked-to entry point.

### Combined Bulk Import page (`app/routes/bulk_imports.py`)

`/administration/import/` is the primary entry point for both CSV importers above (linked from Settings, the Users list, and the Schools list) — a single page where an admin can upload a users CSV and/or a schools ("sites") CSV in one submission via one drag-and-drop dropzone, review one combined preview, and commit both together. It's a thin orchestration layer, not a third importer: `_sniff_kind()` figures out which uploaded file is which (by filename first, falling back to header-column sniffing), then delegates to the exact same `validate_csv()`/`commit_import()` functions from `school_csv_import.py`/`user_csv_import.py` used by the standalone pages — there is still only one code path per entity type. **Schools are always committed before users** in `commit()` (a fixed loop order, `for kind in ("school", "user")`), so a user row referencing a school from the *same* upload batch can already resolve it - don't reorder that loop. Since `manage_schools` and `manage_users` are different permissions (IT Administrator has the former but not the latter), this page checks per-file/per-kind permissions (`_KIND_PERMISSIONS`) rather than gating the whole page behind one decorator — a partial upload (e.g. sites only) is valid for a user who can't import users. The FTP tab embeds the existing user-FTP feature's form via `includes/ftp_settings_panel.html`, a shared partial also used by the standalone `users/ftp_settings.html` — there's still only one FTP settings form/route (`user_imports.ftp_settings`), just included in two places.

### Models (`app/models.py`)

| Model | Notes |
|---|---|
| `License` | `__tablename__ = "licenses"` — one row is one license title's pool (`license_count` seats total). Belongs to exactly one `Contract` (`contract_id`, required — see below); `vendor_id` is its own column but is derived from `contract.vendor_id` at creation, not picked separately. Has **no** `start_date`/`expiration_date`/`renewal_date`/`annual_cost` columns of its own — all four are computed `@property`s (with setters that forward to `self.contract`) reading `self.contract.start_date`/`end_date`/`renewal_date`/`annual_cost`, so a license's dates and cost are just its contract's terms; don't add these back as columns or filter SQL on them directly (join `License.contract` and filter `Contract.end_date` etc. instead — see `list_licenses()` in `app/routes/licenses.py`). `assigned_licenses`, `available_licenses`, `utilization_pct` stay computed from `license_count`/`allocations`. `cost_per_license`/`unused_license_cost` were removed entirely (not reapportioned) once cost moved to Contract-only. `vendor_contact` is a computed passthrough to `self.contract.vendor_contact`. |
| `School` | `code` is unique and is the match key for the schools CSV importer (see below). `city`/`state`/`zip_code`/`email`/`phone`/`acronym`/`cds_code` are optional contact/identifier fields added for that importer — set via CSV import only for now, not yet exposed on the manual Add/Edit School form. |
| `LicenseAllocation` | Per-school breakdown of a `License`'s `license_count`. FK column is `license_id` (not `software_id`). One row per (license, school) pair, enforced by the `uq_allocation_license_school` unique constraint. Never insert/update directly — use `app/services/allocation.py`. |
| `User` | `role` (FK to `Role`), `school_id` (the school this person is associated with — every role can have one, but it only *restricts* a query for School Administrator, via `scope_to_school()`; for any other role it's informational, e.g. shown on the Users page or set by the bulk user CSV importer's `site_name` column). `middle_name` is optional, editable on the manual Add/Edit User form (`UserForm.middle_name`) and shown as its own column on the Users list — not included in `full_name`, which stays first+last only. No separate API bearer token — the JSON API authenticates via the same session cookie as everything else (see below). |
| `Setting` | Generic key/value store for admin-configurable thresholds (`critical_days`, `warning_days`, `upcoming_days`, `high_utilization_pct`, `over_allocated_pct`). Read via `Setting.get_int(key, default)`. |
| `Contract` | Belongs to a `Vendor` (`vendor_id`); has many `License`s (`Contract.licenses`, back-populated by `License.contract_id`) — one contract can bundle several license titles under a single PO. Owns the only copies of `start_date`/`end_date`/`renewal_date` and `annual_cost` for everything under it (see `License` above) — a contract's total cost isn't split per license. `po_number` is the one identifying number for a contract (no separate contract number). `license_type` doesn't exist — the feature was removed entirely, not just relocated. `vendor_contact` stays here (a fact about the specific agreement, not an individual license). `contract_file_name`/`contract_file_path` hold one optional uploaded document (see Contract file upload below) — never set directly, go through `_save_contract_file()`/`_delete_contract_file()`. |
| `AuditLog` | `changes_json` holds a `{field: {"from": x, "to": y}}` diff, written via `app/services/audit.py::diff_changes()`. |
| `ImportHistory` | `kind` (`"license"` default, `"user"`, or `"school"`) discriminates which importer wrote a row — see Bulk User Import / Bulk School Import above. `imported_by_id` is null for an FTP-triggered row (no human initiated it). |
| `FtpImportSettings` | Single-row config (id=1, via `get_or_create()`) for the optional scheduled FTP user import. `password_encrypted` — set/read only through the `password` property, never directly. |
| Datetime columns | Stored as **naive UTC** everywhere (`app.models.utcnow()` strips tzinfo before returning). SQLite round-trips `DateTime(timezone=True)` values as naive regardless of how they were written, so comparing against an aware `datetime.now(timezone.utc)` raises `TypeError`. Keep every new datetime column plain `db.DateTime` and every comparison against naive `utcnow()`. |

### JSON API (`app/routes/api.py`, `app/utils/api_auth.py`)

Authenticates purely via the normal Flask-Login session cookie — there is no separate per-user bearer token (the earlier `User.api_key` bearer-token mechanism was removed). Because of that, the API blueprint is **not** CSRF-exempt: any state-changing request (POST/PUT/DELETE) needs a valid CSRF token like every other form-based route, which in practice means writes are only reachable from an authenticated same-origin request, not a bare external API client. Don't reintroduce `csrf.exempt(api_bp)` without also reintroducing an equivalent non-cookie auth mechanism for writes — the exemption is only safe when a browser session alone can't drive a write. Use `api_user()` inside API views to get the effective caller, not `current_user` directly.

### Contract file upload (`app/routes/contracts.py`)

A `Contract` can carry one uploaded document (`contract_file_name`/`contract_file_path`), stored under `UPLOAD_FOLDER/contracts/` — same security shape as CSV import: `contract_file_path` is always a `secrets.token_hex(16)`-based filename, never the uploaded filename, so there's no path-traversal surface even though it's built from a user-controlled upload; `contract_file_name` is the original name, kept only for display and as the download's `Content-Disposition` name. Extension allowlist is `ALLOWED_CONTRACT_FILE_EXTENSIONS` (pdf/doc/docx) in `config.py`. `_save_contract_file()` deletes the previous file before writing a new one (replace, not accumulate) — any new call site that lets a contract's file be set must go through it and `_delete_contract_file()`, not touch `contract_file_path`/the filesystem directly. Uploading and removing require `manage_contracts` (Administrator/IT Administrator); downloading only requires being logged in, matching `view_contract`'s own access level (contracts aren't school-scoped).

### CSRF

Flask-WTF's `CSRFProtect` is applied globally, so **every** raw `<form method="post">` needs a token even outside a WTForms `form.hidden_tag()` — add `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` by hand to any form built without a WTForms object (see `licenses/detail.html`'s delete/allocation-removal forms for the pattern). Missing this produces a 400, not a redirect, so it's easy to miss in manual testing if you don't click the actual button.

### Environment selection & startup (`config.py`)

`get_config()` reads `APP_ENV` (not the legacy, no-longer-read-by-Flask `FLASK_ENV`) and **raises `RuntimeError` if it's unset or unrecognized** — it never silently falls back to `DevelopmentConfig`. Selecting `production` without a real `SECRET_KEY` env var also raises. Don't reintroduce a default here: a silent fallback to development config in production means `DEBUG=True` and insecure cookies, and a hardcoded `SECRET_KEY` fallback means forgeable sessions/CSRF tokens for anyone who's read this file. `main.py` mirrors this — it refuses `app.run()` (the Werkzeug dev server, with its unauthenticated interactive debugger under `DEBUG=True`) unless `app.config["DEBUG"]` is already true; production is `gunicorn`, never `python main.py`. Local dev needs `APP_ENV=development` in `.env` (already there); `installation/create_env.py` writes `APP_ENV=production` for real deployments.

### Security headers & CSP nonce (`app/__init__.py::_register_security_headers`)

Every response gets `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, and a `Content-Security-Policy`; `Strict-Transport-Security` is added whenever `SESSION_COOKIE_SECURE` is on. `style-src` allows `'unsafe-inline'` (every template styles elements with inline `style="..."` attributes) but `script-src` does not — a fresh `secrets.token_urlsafe` nonce is generated per request in `before_request`, exposed to templates as `csp_nonce`, and must be added (`<script nonce="{{ csp_nonce }}">`) to any new inline `<script>` block (see `dashboard.html`'s Chart.js init) or it will be silently blocked by browsers enforcing the CSP.

**Never use an inline event-handler attribute** (`onchange="..."`, `onclick="..."`, `onsubmit="..."`, etc.) — a nonce only covers `<script>`/`<style>` *tags*, not attributes, so `script-src` without `'unsafe-inline'` silently blocks these in every CSP-enforcing browser (this was a real, previously-unnoticed bug: several auto-submitting filter dropdowns and every delete-confirmation dialog in the app did nothing on click). Wire the behavior instead, either as `addEventListener(...)` inside a nonce'd `<script>` block scoped to that page (see the filter dropdowns in `users/list.html`, `dashboard.html`, `licenses/list.html`), or — for a pattern reused across many pages — as a delegated listener in `app/static/js/app.js` (an external same-origin file, so it's allowed by `script-src 'self'` with no nonce needed) keyed off a `data-*` attribute, the way `form[data-confirm]` replaces every `onsubmit="return confirm(...)"` delete form.

### Reverse proxy IP trust (`BEHIND_PROXY`)

Flask-Limiter's per-IP rate limiting and `audit.py`'s `ip_address` column both read `request.remote_addr` directly. Behind nginx (the documented deployment) that's the proxy's own address unless `BEHIND_PROXY=true` wires up `werkzeug.middleware.proxy_fix.ProxyFix` in `create_app()`. It trusts exactly one hop (`x_for=1`) — bump that only if there's a real second proxy in the chain, never speculatively, or a client can spoof `X-Forwarded-For` and defeat both rate limiting and audit-log accuracy.

### Session invalidation on password change (`User.security_stamp`)

Flask-Login sessions here are stateless signed cookies with no server-side revocation by default. `User.get_id()` returns `"<id>.<security_stamp>"`, and `set_password()` rotates `security_stamp` every time a password changes — the `login_manager.user_loader` in `app/__init__.py` rejects any session id whose stamp doesn't match the current one. This is what makes "reset your password if you think someone has your session" actually revoke that session. Never add a code path that changes `password_hash` without going through `set_password()`.

### Templates (`app/templates/`)

- `base.html` — full app shell (sidebar + topbar), used by all authenticated pages.
- `base_bare.html` — centered card layout with no nav, used by `login.html`, password reset, and `errors/*.html` (so a 403/404 renders sensibly for a logged-out visitor).
- `includes/macros.html` — `field()` macro renders one Bootstrap-styled WTForms field with error display; use it in every form template instead of hand-rolling `<input>` markup.
- `includes/pagination.html` / `includes/export_buttons.html` — build merged query-arg dicts for `url_for()`. Jinja's expression grammar rejects `dict(a, **b, key=c)` (positional arg + `**kwargs` + another kwarg together) — build the merged dict in a `{% set %}` first, then pass it as `**dict(that, key=c)`.

### CSS

`app/static/css/style.css` `--bs-main-color-*`, `--color-*`, `--status-*` custom properties defined once under `:root, [data-bs-theme=light]`. Status badge colors come only from the `.status-active/.status-warning/.status-critical/.status-expired/.status-upcoming` classes — never hardcode a hex color for status in a template or inline style.

---

## Key Conventions

- **Don't add a `status` column meaning for the countdown to expiration.** `License.status` is the *administrative* lifecycle field (Active/Suspended/Pending Renewal/Cancelled), independent from the *computed* expiration status (Active/Upcoming/Warning/Critical/Expired) from `app/services/status.py`. Both appear in the UI but are different concepts — check which one a given badge/filter is supposed to reflect.
- **The model is `License`, not `Software`.** Table `licenses`, FK column `license_id` on `LicenseAllocation`, routes under `/licenses/*`, blueprint functions `list_licenses`/`add_license`/`view_license`/`edit_license`/`delete_license`. The app went through a full rename from an original `Software` model — if you see "software" in a diff or a new file, that's almost certainly a mistake to fix, not a pattern to follow. The one place "license" would collide awkwardly is naming a local Python variable `license` (shadows the builtin `license()`); this codebase uses `lic` in templates and `license_` in Python (services, fixtures) instead.
- **The setup order is School → Vendor → Contract → License, and the schema enforces it.** `Contract` belongs to a `Vendor`; `License.contract_id` is required, so a license can't exist without first creating (or picking) a contract. Contracts are created from a vendor's detail page (`/vendors/<id>/contracts/add`); licenses are created from a contract's detail page (`/contracts/<id>/licenses/add`) — the "Add License"/"New Contract" buttons elsewhere in the UI are just picker modals that redirect into those same routes. Don't add a code path that creates a `License` without an existing `Contract`, or a `Contract` without an existing `Vendor`.
- **School-scoping is a query filter, not a template `{% if %}`.** Every list/detail view that a School Administrator can reach must filter at the SQLAlchemy query level (`join(LicenseAllocation).filter(LicenseAllocation.school_id == current_user.school_id)`), matching the pattern already in `licenses.py`, `dashboard.py`, and `reports.py`.
- **CSV import never partially trusts a row.** `app/integrations/csv_import.py` splits into `validate_csv()` (read-only, safe to call repeatedly for a preview) and `commit_import()` (the only function that writes, and it re-validates allocation limits against live DB state via `allocation.py` rather than trusting the preview). Don't add a code path that writes without going through both. All three CSV importers (`csv_import.py`, `user_csv_import.py`, `school_csv_import.py`) reject files over `MAX_ROWS` (20,000) before doing any per-row work, regardless of the global `MAX_CONTENT_LENGTH` upload-size cap.
- **Report exports sanitize formula-prefixed cells.** `app/utils/exports.py::_sanitize_cell` prefixes any string cell starting with `= + - @ \t \r` with a `'` before writing it to CSV/XLSX, since those trigger formula/DDE execution when opened in Excel/Sheets and several exportable fields (vendor/license names, notes) are settable by non-Administrator roles. Apply the same sanitization to any new export path that writes user-supplied strings into spreadsheet cells; PDF export doesn't need it.
- **Password resets go through `app/services/mailer.py`, never straight to the logger.** `send_password_reset_email()` sends via Flask-Mail when `MAIL_SERVER` is configured, otherwise logs only that a reset was requested - **never** the token itself (the token is a live account-takeover credential for its validity window). The bulk-user-import results page is the one place a reset link is intentionally shown in-app, and only to the Administrator who ran the import.
- **Integrations are opt-in and no-op until configured.** `app/integrations/{synergy,clever,canvas}.py` are unimplemented stubs gated by an `*_ENABLED` env flag; `app/integrations/ftp_users.py` (see Bulk User Import above) is a real, working integration but follows the same shape — it implements `IntegrationBase` and is inert until `FtpImportSettings.is_configured()` is true. Don't call a vendor API (or ftplib) directly from a route — go through the integration class.
