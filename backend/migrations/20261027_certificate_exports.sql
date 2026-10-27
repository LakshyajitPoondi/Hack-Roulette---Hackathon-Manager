-- New feature only: short-lived, private inputs for bulk certificate downloads.
BEGIN;
CREATE TABLE IF NOT EXISTS public.certificate_exports (
    id VARCHAR(36) PRIMARY KEY,
    created_by INTEGER NOT NULL REFERENCES public.users(id),
    expires_at TIMESTAMPTZ NOT NULL,
    template_id INTEGER NOT NULL,
    template_snapshot JSON NOT NULL,
    file_data BYTEA NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_certificate_exports_created_by ON public.certificate_exports(created_by);
CREATE INDEX IF NOT EXISTS ix_certificate_exports_expires_at ON public.certificate_exports(expires_at);
CREATE TABLE IF NOT EXISTS public.certificate_export_recipients (
    export_id VARCHAR(36) NOT NULL REFERENCES public.certificate_exports(id) ON DELETE CASCADE,
    participant_id INTEGER NOT NULL,
    name VARCHAR(160) NOT NULL,
    college VARCHAR(160),
    team_name VARCHAR(160),
    filename VARCHAR(220) NOT NULL,
    PRIMARY KEY (export_id, participant_id)
);
-- These inputs contain participant details/artwork; expose them only through the authenticated API.
ALTER TABLE public.certificate_exports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.certificate_export_recipients ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.certificate_exports, public.certificate_export_recipients FROM PUBLIC;
COMMIT;
