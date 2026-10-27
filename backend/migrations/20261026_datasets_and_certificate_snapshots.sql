-- Run after the existing schema, before deploying this version. Transactional and repeatable.
BEGIN;

CREATE TABLE IF NOT EXISTS public.datasets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    original_data BYTEA NOT NULL,
    headers JSON NOT NULL,
    original_rows JSON NOT NULL,
    rows JSON NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    is_legacy BOOLEAN NOT NULL DEFAULT FALSE,
    created_by INTEGER REFERENCES public.users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_datasets_legacy ON public.datasets(is_legacy) WHERE is_legacy = TRUE;
CREATE TABLE IF NOT EXISTS public.dataset_participants (
    dataset_id INTEGER NOT NULL REFERENCES public.datasets(id) ON DELETE RESTRICT,
    participant_id INTEGER NOT NULL REFERENCES public.participants(id) ON DELETE CASCADE,
    PRIMARY KEY (dataset_id, participant_id)
);
CREATE INDEX IF NOT EXISTS ix_dataset_participants_participant ON public.dataset_participants(participant_id);

-- Existing participant IDs and delivery keys are never reassigned. A participant may belong to many datasets.
INSERT INTO public.datasets(name, original_filename, original_data, headers, original_rows, rows, is_legacy)
SELECT 'Existing participants', 'existing-participants.csv',
       convert_to('name,email,team_name,college' || E'\r\n' || coalesce(string_agg(
           '"' || replace(name, '"', '""') || '","' || replace(email, '"', '""') || '","' ||
           replace(coalesce(team_name,''), '"', '""') || '","' || replace(coalesce(college,''), '"', '""') || '"', E'\r\n' ORDER BY id), ''), 'UTF8'),
       '["name","email","team_name","college"]'::json,
       coalesce(json_agg(json_build_object('id', ordinal, 'cells', json_build_array(name,email,coalesce(team_name,''),coalesce(college,''))) ORDER BY id), '[]'),
       coalesce(json_agg(json_build_object('id', ordinal, 'cells', json_build_array(name,email,coalesce(team_name,''),coalesce(college,''))) ORDER BY id), '[]'), TRUE
FROM (SELECT *, row_number() OVER (ORDER BY id) AS ordinal FROM public.participants) p
HAVING count(*) > 0 AND NOT EXISTS (SELECT 1 FROM public.datasets WHERE is_legacy);

INSERT INTO public.dataset_participants(dataset_id, participant_id)
SELECT d.id, p.id FROM public.datasets d CROSS JOIN public.participants p
WHERE d.is_legacy AND NOT EXISTS (SELECT 1 FROM public.dataset_participants m WHERE m.participant_id = p.id)
ON CONFLICT DO NOTHING;

ALTER TABLE public.email_campaigns
    ADD COLUMN IF NOT EXISTS dataset_id INTEGER REFERENCES public.datasets(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS certificate_snapshot JSON,
    ADD COLUMN IF NOT EXISTS certificate_file_data BYTEA;
-- Backfill legacy team snapshots only on the first upgrade; repeat runs must not rewrite newer history.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'email_deliveries' AND column_name = 'team_name') THEN
        ALTER TABLE public.email_deliveries ADD COLUMN team_name VARCHAR(160);
        UPDATE public.email_deliveries d SET team_name = p.team_name
        FROM public.participants p
        WHERE d.participant_id = p.id
          AND lower(trim(d.participant_name)) = lower(trim(p.name))
          AND lower(trim(d.email)) = lower(trim(p.email));
    END IF;
END
$$;

-- The historical rendering cannot be recovered if a template was edited before this migration.
-- Freeze its current version now; never overwrite a snapshot on a later run.
UPDATE public.email_campaigns c
SET certificate_snapshot = (to_jsonb(t) - ARRAY['id','file_data','created_at','updated_at','created_by','is_active'])::json,
    certificate_file_data = t.file_data
FROM public.certificate_templates t
WHERE c.certificate_template_id = t.id AND c.attach_certificate AND c.certificate_snapshot IS NULL;


COMMIT;
