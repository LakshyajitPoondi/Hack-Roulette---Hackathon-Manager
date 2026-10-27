# Bulk certificate download

The existing Generate Certificate page now includes a bulk ZIP download above its unchanged manual PDF preview/download controls. This feature does not call an email provider, create a campaign, change delivery status or update participants/datasets.

## Using the feature

Choose a dataset or **All datasets — all participants**, then select individual records or use **Select All**. Select All covers the complete chosen scope, including other pages and rows hidden by search. Changing scope clears selection. Shared-email participants remain separate because selection and rendering use participant IDs.

Choose a saved certificate (the active one is the default), review the participant count and template name, and select **Generate & Download ZIP**. The UI reports actual processed/total counts, successfully generated PDFs and per-participant failures, then separately reports ZIP preparation/readiness. An automatic download is requested when ready; a persistent download link provides a fallback. Filenames retain readable Unicode and include participant IDs to prevent collisions. Template formatting, uppercase options and optional college/team rendering reuse the existing PDF renderer. Unicode text is passed unchanged to it; glyph coverage still depends on the chosen existing font.

Partial results are explicitly named `tech-roulette-certificates-partial.zip`, and the page lists every failed/not-attempted participant with its reason. Only successful PDFs enter the ZIP. If every certificate fails, no ZIP is downloaded. A network/session interruption or archive-size limit stops further requests; progress stays at the actual number processed instead of reporting a false 100%.

## Architecture and limits

Vercel function payloads are limited to 4.5 MB ([official limits](https://vercel.com/docs/functions/limitations)). A whole server-generated ZIP could exceed that limit. This feature therefore makes one bounded, authenticated PDF request at a time and assembles the ZIP privately in browser memory using `fflate` 0.8.2. It is a small ZIP utility dependency, not a UI library. Store-mode ZIP entries avoid recompressing already compressed PDF content and avoid worker/setup requirements.

- At most 5,000 participants per run, with pagination for selection and failure review.
- At most 3 MiB per PDF, keeping binary/base64 response overhead below the Vercel limit. A larger rendered PDF fails individually with instructions to use a smaller background.
- At most 100 MiB per ZIP, including a conservative allowance for ZIP headers, to bound browser memory. Larger sets need smaller selections. No ZIP64 or persistent large-file storage is added.
- At most 2 MiB of recipient manifest data. Very long Unicode names can therefore require fewer than 5,000 recipients.
- At most three active export snapshots per administrator; each expires after two hours. Completed/interrupted in-page runs request immediate cleanup. Expired runs become inaccessible immediately and are physically pruned, up to 50 at a time, when a new run is successfully started. A closed/crashed browser cannot guarantee immediate server cleanup; there is no new background worker.

`certificate_exports` stores a short-lived copy of the template name/configuration and artwork. `certificate_export_recipients` stores the selected participant IDs, names, college/team and safe filenames. These immutable inputs survive independent serverless invocations. Changes to the active template, its content/artwork or participant details cannot change PDFs within an existing run. These IDs intentionally have no foreign key to mutable participants/templates, so the export continues to use its private snapshot without affecting their deletion or campaign rules.

The server validates selection scope, IDs, counts, template availability and limits before creating the snapshot transaction. A request UUID makes creation retries idempotent; a per-admin PostgreSQL advisory lock bounds simultaneous snapshots. The existing administrator dependency protects every export operation; only the creator can fetch PDFs or delete their run. Responses use `private, no-store`. New tables enable RLS with no public policies, so direct Supabase browser API access is denied; the existing server database connection must have owner/bypass privileges for these tables. Generated PDFs are not stored on the server or in public object storage.

## Changed files

- `backend/app/models/certificate_export.py`: temporary input models.
- `backend/app/api/certificate_exports.py`: creation, per-participant PDF generation, authorization, limits, expiry and cleanup.
- `backend/app/main.py`, `models/__init__.py`: route/model registration.
- `frontend/src/components/admin/BulkCertificateDownload.tsx`: scope, template and participant selection, progress, results and download UI.
- `frontend/src/services/certificateExport.ts`, `types/certificateExport.ts`: bounded generation and ZIP assembly/progress contracts.
- Existing `AdminCertificatesPage.tsx`, `services/api.ts`, styles and package/lock files integrate the feature.
- `backend/migrations/20261027_certificate_exports.sql`: only the two new tables/indexes/privacy settings. The fresh-install schema also includes this addition.
- `backend/tests/test_certificate_exports.py`, `frontend/tests/certificateExport.test.cjs`: focused regressions. The isolated PostgreSQL checker also covers the new migration's repeatability, RLS and cascading cleanup.

## Validation and deployment

Focused validation covers dataset/all/individual selection, out-of-scope IDs, shared emails, duplicate names, Unicode PDF content and ZIP filenames, template/artwork/participant snapshot stability, existing manual rendering, idempotency, ownership, expiry and cleanup, limits, actual progress, ZIP extraction, partial/all failures and interruption behavior. Commands:

Results: all 7 export backend tests passed, all 8 existing certificate tests passed, all 7 browser ZIP/selection/progress unit tests passed, and frontend TypeScript checking passed. The isolated PostgreSQL migration checker passed for upgrades, repeated execution, fresh bootstrap, row-level security and cascading cleanup. No browser interaction automation or production build was performed for this feature.

```powershell
# From backend:
../.venv/Scripts/python.exe -m pytest tests/test_certificate_exports.py tests/test_certificates.py -q -p no:cacheprovider
# From frontend:
npm run test:certificate-export
node_modules/.bin/tsc -p tsconfig.app.json --noEmit
# From repository root, if local PostgreSQL binaries are available:
.venv/Scripts/python.exe backend/tests/check_postgres_migration.py --postgres-bin 'C:\Program Files\PostgreSQL\18\bin'
```

For deployment, apply **only** `backend/migrations/20261027_certificate_exports.sql` to the current deployed schema before deploying the frontend/backend together. Do not rerun earlier feature migrations for this change. `npm ci` installs the new locked ZIP dependency. No environment variable, authentication, queue/worker or email configuration changes are required. No actual emails, deployment or production database updates are part of implementation/testing. Browser interaction and automatic-download behavior still warrant a short manual smoke check after deployment.
