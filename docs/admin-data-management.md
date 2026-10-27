# CSV, datasets and template management

The admin now has separate **Participants**, **CSV Management**, **Templates**, **Generate certificate**, **Compose email** and **Send history** pages. Old email/certificate template URLs redirect to the relevant tab in Templates. Authentication, cookie/session management and role checks are unchanged.

## CSV Management

Upload a named UTF-8 CSV with name/email columns; team/college are optional. Other columns, their order and cell values stay in the dataset. Limits are 5 MB, 5,000 rows, 100 columns and 10,000 characters per cell. Malformed quoting, extra columns, duplicate/ambiguous headers, NULs and unsupported encoding are rejected. Short rows are padded with empty cells so required-field errors can be corrected.

The workspace supports:

- Paginated cell editing with Save/Cancel and immediate error/warning indicators; saves perform full server validation.
- Exact whole-cell replacements in one column, with optional case-insensitive matching. Every bulk edit/removal shows affected rows and requires Apply; Cancel makes no changes.
- Ascending/descending sorting that moves whole rows while retaining stable original row IDs.
- Exact-row, normalized name-and-email and shared-email duplicate groups with explanations. Bulk deduplication removes only identical rows, after preview; group review can keep selected records.
- Whitespace, email formatting/internal spaces, missing names/emails, department case/spacing and likely abbreviation/full-name variants, empty rows and suspicious spacing warnings. Suggested corrections require acceptance; rejected suggestions leave the underlying validation intact. Semantic department expansions use explicit bulk replacement, not guessed aliases or email domains.
- Ten local undo steps, including edits already saved during the current editing session. Undo history and rejected-suggestion dismissals reset when a dataset is reopened.
- An import review with total, valid, invalid, repeated, approval-needed, modified, removed and ready counts. Shared-email approvals are individual. Only eligible rows enter the import transaction.
- Immutable original downloads and formula-safe exports of saved drafts. Formula-like cells in exports receive an apostrophe prefix. Exact original bytes download as `.txt` to encourage safe inspection; the original filename is retained in the database.

Edits remain local until Save Draft or Save & Review Import. Reloading another saved dataset requires discarding unsaved edits. Optimistic revision checks reject stale saves. Search never calls the API on each keystroke. A request-size limit also bounds JSON/multipart bodies before parsing.

## Dataset and participant identity

`datasets` stores immutable upload bytes/filename, original rows, headers and a mutable JSON draft. `dataset_participants` is a many-to-many collection membership table. A participant can be reused by multiple datasets without being copied or renumbered. The existing normalized name+email uniqueness rule is retained; email alone is not an identity. When a matching participant already exists, imports link its ID and retain its existing name/email/team/college. The import preview explains reuse. Use Participants to deliberately edit those fields.

Imports are additive: removing a draft row does not remove a previously linked participant. Dataset switching does not clear anyone. Dataset rename, archive/restore, creation dates, linked counts, filtering in Participants/Compose and reuse in another campaign are supported. There is no hard-delete dataset operation. Campaigns optionally reference a dataset with a restrictive foreign key. Participants referenced by any delivery cannot be deleted or cleared. The old CSV import path also saves its upload and memberships in the same transaction.

The migration creates an **Existing participants** collection for pre-upgrade records, retaining their IDs. Its CSV is a reconstruction from stored participant values; old transient upload bytes cannot be recovered. Historical delivery keys, names, emails, statuses and campaign recipient associations are preserved.

## Templates and campaigns

Email and certificate templates retain separate models and API routes. Templates has distinct tabs for both. Certificate generation remains available independently.

Previously the certificate screen's Template Name field named a **new upload** only; it did not rename the selected saved configuration. A separate Saved Certificate Name control now PATCHes that template's ID. Email templates have an explicit name-only PATCH and rename control, rather than requiring content replacement. Both paths trim/validate names, reject case-insensitive conflicts, persist changes and refresh their displayed data without creating another template. PostgreSQL advisory locks serialize conflicting name writes without a destructive uniqueness migration over any pre-existing duplicate names. Existing content/placement edits continue to work even when old duplicate names exist.

Certificate activation retains the existing single-active-template database index and serializes activation writes. Compose loads the active certificate by default and permits another selection or no attachment. The same explicit selection flows through email preview, test requests and campaign creation. Send history shows the saved certificate name.

Each new certificate campaign saves the selected template ID, all rendering settings/name and a copy of its original artwork. Subsequent rename, background replacement, activation or placement/font edits cannot alter that campaign's remaining batches or retries. Snapshot artwork is loaded only when rendering, not in campaign lists. Referenced certificate templates cannot be deleted. Storing artwork once per campaign increases database storage proportionally to campaign/template size.

Each delivery is keyed by participant ID, including when email addresses are shared. Name, email, college and team always resolve from that one ID before rendering. The existing behavior that an admin can correct a pending participant's details is preserved. Sent delivery snapshots are not refreshed. Team is also retained as a fallback snapshot. Legacy history matching, resend protections, foreground batches, retry behavior, placeholders, on-demand PDF generation and provider idempotency keys remain in place.

## Files and migration

- `backend/app/models/dataset.py`, `api/datasets.py`, `services/datasets.py`: dataset storage, draft operations, analysis, export and import.
- `backend/app/api/participants.py`, `services/csv_participants.py`, `services/db_participants.py`: collection filtering, saved legacy imports and protected history.
- `backend/app/models/email.py`, `api/emails.py`, `services/email_campaigns.py`, `services/campaign_processor.py`: campaign selection, certificate snapshots and recipient associations.
- `backend/app/api/certificates.py`, `services/certificates.py`, `services/template_names.py`: durable naming, activation and rendering snapshots.
- `frontend/src/pages/CsvManagementPage.tsx`, `TemplatesPage.tsx`, `services/csvEditor.ts`, `types/dataset.ts`: CSV editor and unified template workspace.
- Existing participants, composer, certificate/email templates, send history, navigation, API types/client and styles integrate those modules.
- `backend/migrations/20261026_datasets_and_certificate_snapshots.sql`: additive, transactional upgrade; the same upgrade is included in `supabase_schema.sql` for fresh installs/repeated bootstrap.

## Validation

Focused backend regressions: 46 passed (44 in the initial focused run; all 11 dataset/template checks passed after the final limit/department additions) across participants, certificate rendering/fonts, campaign batches/history, datasets and template management. These include original-byte preservation, validation/size/malformed-input checks, revision/digest conflicts, shared-email approval, identity reuse, archive/RBAC, campaign collection filtering, certificate selection/snapshot stability and name-only rename persistence/content preservation.

CSV editor tests: 5 passed, including exact replacements without substring changes, case matching, sorting/row identity, duplicate detection, updated validation and a 5,000-row edit/undo case. Frontend TypeScript checking passed. Tests use SQLite and simulated/mocked providers; no actual email is sent. No production build or comprehensive browser automation was run.

The standalone `backend/tests/check_postgres_migration.py` passed against PostgreSQL 18.4 and validates legacy upgrades, repeated execution, snapshots, shared-email memberships, restrictive deletion and fresh bootstrap against its own temporary local PostgreSQL cluster. It never reads `DATABASE_URL` or connects to an existing server.

## Deployment

1. Before starting the updated backend, apply `backend/migrations/20261026_datasets_and_certificate_snapshots.sql` to an existing current-schema database. For a fresh database, apply `supabase_schema.sql` instead. Neither application startup nor tests apply migrations to production.
2. Deploy the backend and frontend together. No environment variable or authentication changes are needed.
3. Check the recovered dataset, saved template names, active certificate and import previews. Existing campaigns whose template was previously edited are frozen to its version **at migration time**; the original historical artwork/settings cannot be reconstructed. Campaigns whose template had already been deleted retain their delivery history but cannot regain a missing attachment.

No actual emails, deployments, live environment changes or production data modifications were performed during implementation.
