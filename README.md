# Tech Roulette

Temporary hackathon website and certificate mailer built for Vercel: React/Vite frontend, FastAPI Vercel Function, CSV-imported PostgreSQL participants, and Brevo delivery.

## Architecture

- CSV Management saves named UTF-8 datasets, provides editing/validation/deduplication previews and imports eligible participants. `name,email` are required; `team_name,college` are optional. Extra columns remain in the saved dataset.
- Google Sheets integration remains in the repository but is currently disabled in the admin workflow.
- Compose Email defaults to the active certificate and allows another selection or no attachment. Each campaign snapshots that configuration/artwork; personalized PDFs render in memory using participant name, optional college and team.
- Admins select imported recipients and confirm SEND. Certificates are generated during small, consecutive requests started by that click; delivery status is recorded for each recipient. An interrupted send can be resumed from Send History.
- There is no Celery, Redis, worker, or always-running backend process.

The PostgreSQL schema is maintained in [supabase_schema.sql](supabase_schema.sql). Participants are identified by normalized name and email, so several people can share an address. Datasets reuse existing participant IDs without clearing earlier collections or send history. See [dataset/template implementation and migration notes](docs/admin-data-management.md).

## Local setup

Requirements: Node 20.19+ or 22+, Python 3.11+, and a Supabase Postgres project. Docker is not required.

1. Create or open the Supabase project.
2. Open its SQL Editor and run [supabase_schema.sql](supabase_schema.sql) for a fresh database. For an existing current-schema database, apply [the dataset/certificate snapshot migration](backend/migrations/20261026_datasets_and_certificate_snapshots.sql) before starting this version. Existing participant IDs and delivery records are preserved; pre-upgrade participants receive a default dataset. Review older schema differences before upgrading.
3. Set `DATABASE_URL` to the Supabase Postgres connection string in `backend/.env` for local use or in Vercel's backend environment settings for deployment.
4. Seed the initial admin from a trusted shell, then start or deploy the application.

From `backend/`:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.db.seed
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Set `DATABASE_URL`, a 32+ character `JWT_SECRET`, `FRONTEND_ORIGIN`, and initial-admin values before seeding. Passwords use Argon2 and sessions use an HttpOnly JWT cookie. Google Sheets settings are not needed for CSV imports.

The initial admin password is configured through `INITIAL_ADMIN_PASSWORD` (the setup default is `roulette@123`) and is never exposed to the frontend. To apply the configured password to an already-seeded initial admin, run `python -m app.db.seed --reset-existing` from `backend/`; the reset is hashed through the same Argon2 flow as user creation.

From `frontend/`:

```powershell
npm install
Copy-Item .env.example .env
npm run dev
```

`VITE_GOOGLE_FORM_URL` controls the public registration link. Copy `frontend/.env.example` to the Git-ignored `frontend/.env` for local development, then set the real Google Form URL there:

```env
VITE_GOOGLE_FORM_URL=https://forms.gle/...
```

Do not commit the real URL or hardcode it in React source. For local development, set `VITE_API_URL=http://127.0.0.1:8000` in the ignored `frontend/.env.development.local`. In production, leave `VITE_API_URL` unset to call same-origin `/api` routes. Remove any `VITE_API_URL=http://127.0.0.1:8000` value from Vercel project settings; Vite embeds that value in the production bundle. A configured URL ending in `/api` is also accepted without doubling the path.

## Certificates and email

Generate Certificate also supports selected/all participants in a chosen dataset or across datasets, with real generation progress and a private ZIP download that sends no email. Existing deployments must apply [the bulk-export migration](backend/migrations/20261027_certificate_exports.sql) before using it. See [bulk download architecture, limits and validation](docs/bulk-certificate-download.md).

Admins can upload a PNG, JPG, or single-page PDF template; drag the participant name and college to their positions; preview the final PDF; and activate the template. Preview and participant downloads render on demand.

Email subjects/bodies support `{{participant_name}}` and `{{college_name}}`. Keep `EMAIL_MODE=development` for simulated sends. For real delivery set `EMAIL_MODE=production`, `BREVO_API_KEY`, and a verified `EMAIL_FROM`; `EMAIL_FROM_NAME` defaults to `Department of Artificial Intelligence & Data Science` and `EMAIL_REPLY_TO` is optional. Keep the API key in backend/Vercel server settings, never in a `VITE_` variable.

The default **Only participants not already sent** option checks successful certificate deliveries across certificate campaigns, or successful plain-email deliveries with the same campaign name. **All selected participants** still skips prior successful recipients unless the admin checks **RESEND**. Retry Failed only processes failed rows. Brevo acceptance is recorded as `SENT` with its `messageId`; a failed request is recorded as `FAILED` with a reason. A `SKIPPED` row can appear if another campaign sent to that participant after this campaign was created.

Admin selects recipients → reviews the recipient count → confirms SEND → certificates are generated and emailed in foreground batches of 10. Failed deliveries can be retried from Send History; interrupted sends can be continued there. Brevo requests use a per-attempt idempotency key. No batch runs without an admin action. Verify the first real delivery with **SEND TEST EMAIL**; its optional participant selection attaches a sample certificate.

## Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
```

Deploy the repository root to Vercel after running [supabase_schema.sql](supabase_schema.sql) in the Supabase SQL Editor. Configure `DATABASE_URL`, `JWT_SECRET`, `FRONTEND_ORIGIN` (the deployed site origin), and `COOKIE_SECURE=true`. For real delivery, add `BREVO_API_KEY`, verified `EMAIL_FROM`, optional `EMAIL_FROM_NAME` and `EMAIL_REPLY_TO`, and `EMAIL_MODE=production`. Seed the initial admin from a trusted shell and remove the seed password.
