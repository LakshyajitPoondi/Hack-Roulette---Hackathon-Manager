# Current architecture

The Vite SPA and FastAPI Vercel Function share one Vercel project. FastAPI is stateless between requests except for PostgreSQL records.

CSV-imported PostgreSQL records are the participant source for the admin UI, certificate lookup, and email selection. `services/google_sheets.py` is retained but disabled in this workflow. PostgreSQL also stores authentication/RBAC, template assets, campaign definitions, and immutable delivery snapshots/status.

The current PostgreSQL schema is defined in `supabase_schema.sql` and applied through the Supabase SQL Editor. Participant rows are stored in PostgreSQL; personalized certificate PDFs are not.

The certificate template contains all static artwork and wording. `services/certificates.py` overlays participant name and optional college/team into a one-page PDF in memory. Compose selects a certificate (defaulting to the active one) or no attachment. Each certificate campaign stores the selected ID, name, rendering configuration and artwork snapshot. Campaign processing builds that PDF immediately before the Brevo call and does not persist it. Editing the live template does not change an existing campaign.

Named datasets retain immutable original CSV bytes and editable JSON rows, with revision checks on draft saves. A many-to-many membership table links datasets to existing participant IDs. Import previews revalidate data on the server, require shared-email approvals and use a digest to prevent stale imports. Imports add memberships and preserve existing participant details and historical delivery associations. Dataset archival preserves campaign references. [Admin data management](admin-data-management.md) documents the new routes, migration, limits and verification.

Admin selects recipients → reviews the count → confirms SEND → certificates are generated and emailed in foreground batches of 10. The same synchronous processor handles explicit retry of failed deliveries. Database row locking, a unique campaign/participant key, scoped sent-history checks, and Brevo idempotency keys reduce accidental duplicates. Each batch must fit within the Vercel Function duration. No queue broker or persistent worker is required.
