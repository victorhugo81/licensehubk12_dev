---
title: "Bulk Import: Users & Sites"
description: "How to prepare and upload users.csv and sites.csv files to bulk-import or update accounts and schools in LicenseHubK12."
weight: 10
---

## Overview

The **Bulk Import** page (**Settings > Bulk Import**, or the "Import CSV" button on the Users or Schools list) lets you upload a `users.csv` file, a `sites.csv` file, or both at once. Each file is validated and shown in a preview — nothing is written to the database until you confirm.

If you upload both files together, **sites are always processed before users**, so a new user row referencing a school from the same upload can already resolve it.

Every upload keeps a history entry (Date/File, Uploaded By, Total Records, Result, Status) at the bottom of the Bulk Import page.

---

## `users.csv`

### How matching works

- **`email` is the match key.**
  - An email that **doesn't already exist** creates a new account.
  - An email that **already exists** updates that person's name, status, and school — it **never changes their role**. Re-uploading a roster is not a way to grant or revoke admin access; role changes are made on the Users page itself.
- A new account never gets a visible password. It gets an email with a link to set its own password (valid 7 days).
- Any column not listed below is simply ignored, so your file can include extra columns from another system's export without causing an error.

### Columns

| Column | Required? | Description |
|---|---|---|
| `first_name` | **Required** | First name. |
| `middle_name` | Optional | Middle name. |
| `last_name` | **Required** | Last name. |
| `email` | **Required** | The match key — see above. |
| `site_name` | Optional | The exact school name as it appears in LicenseHubK12. Recorded for any role (shown on the Users page); **required** only when a *new* row is being created with the role School Administrator. |
| `status` | Optional | `Active` or `Inactive`. New accounts default to Active if left blank. For an existing account, leaving it blank leaves the current status unchanged. |
| `role` | Optional, not part of the standard roster export | `Administrator`, `IT Administrator`, `Curriculum Administrator`, `School Administrator`, or `Viewer`. Only used when **creating** a new account — a new account with no role column defaults to **Viewer**, the least-privileged role. Ignored for an existing account. |

### Template

```csv
first_name,middle_name,last_name,email,site_name,status
Jane,,Doe,jane.doe@example.org,Calexico High School,Active
John,A,Smith,john.smith@example.org,Rockwood Elementary,Active
```

A downloadable copy of this template is available from the "Users Template" button on the Bulk Import page.

---

## `sites.csv`

### How matching works

- **`site_code` is the match key.** A code that already exists **updates** that school's fields; a new code **creates** a new school. Re-uploading a refreshed site directory naturally syncs it — it will never error out on a duplicate code.

### Columns

| Column | Required? | Description |
|---|---|---|
| `site_name` | **Required** | School name. |
| `site_acronyms` | Optional | Short nickname/abbreviation, e.g. `CHS`. |
| `site_cds` | Optional | State-assigned identifier (e.g. California's County-District-School code). |
| `site_code` | **Required** | Unique code — the match key described above. |
| `site_address` | Optional | Street address. |
| `sitecity` | Optional | City. |
| `sitestate` | Optional | 2-letter state code. |
| `sitezip` | Optional | ZIP code. |
| `prnfirstn` | Optional | Principal's first name. |
| `prnlastn` | Optional | Principal's last name. |
| `email` | Optional | School office email. |
| `phone` | Optional | School office phone. |
| `site_type` | **Required** | One of: `Elementary`, `Middle School`, `High School`, `Alternative`, `District Office`, `Other` — or the shorthand `ES`, `MS`, `HS` (case-insensitive; normalized automatically). |
| `grades` | Optional, not part of the standard export | Comma-separated grades served, e.g. `9,10,11,12`. |
| `student_count` | Optional, not part of the standard export | Enrollment count. |

### Template

```csv
site_name,site_acronyms,site_cds,site_code,site_address,sitecity,sitestate,sitezip,prnfirstn,prnlastn,email,phone,site_type
Calexico High School,CHS,12345670123456,CHS-01,123 Main St,Calexico,CA,92231,Jane,Rivera,chs@example.org,7605551234,HS
Rockwood Elementary,RES,12345670654321,RES-02,456 Oak Ave,Calexico,CA,92231,Sam,Torres,res@example.org,7605555678,ES
```

A downloadable copy of this template is available from the "Sites Template" button on the Bulk Import page.

---

## Uploading

1. Go to **Settings > Bulk Import** (or click "Import CSV" from the Users or Schools list).
2. Drag and drop `users.csv` and/or `sites.csv` onto the upload area — or click it to browse for the file(s). You can upload one file or both together.
3. Review the preview. Each row is marked **valid**, **warning** (imported, but flagged for review), or **error** (never imported).
4. Click **Confirm import**. Rows with errors are skipped; everything else is written to the database.

If anything looks wrong at the preview step, click **Cancel** — nothing is written until you confirm.

## Common errors and warnings

| Message | What it means |
|---|---|
| "Missing required column(s): …" | The file's header row is missing a required column name. Column names must match exactly (case-sensitive). |
| "'…' is not a valid role. Must be one of: …" | The `role` column has a value that doesn't match one of the five role names exactly (only checked when creating a new account). |
| "site_name is required for role School Administrator." / "School '…' does not exist in LicenseHubK12." | A *new* School Administrator account needs a valid, exact, existing school name in `site_name`. |
| "A user with email '…' already exists and will be updated (its role is never changed by import)." | Informational — this row will update the existing account's name/status/school only. |
| "'…' keeps its current role (…) - the role column is ignored for existing users." | Informational — the `role` value in this row doesn't match the account's actual current role, but it's ignored either way. |
| "School '…' does not exist and will be ignored." | The site name/code didn't match anything in the system, so that field was skipped for this row. |
| "Duplicate email/code '…' elsewhere in this file." | The same email or site code appears twice in your file — only the first occurrence is kept. |
