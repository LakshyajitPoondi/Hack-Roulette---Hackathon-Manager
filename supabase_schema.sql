-- Tech Roulette: current FastAPI/SQLAlchemy schema for Supabase Postgres.
-- Creates the current schema on a fresh project and adds the CSV participant
-- table, allow_resend, optional participant team/college, and certificate
-- team-line and font settings to an existing database. Safe to run more than once.
-- CSV-imported participants live in Postgres; personalized certificates are rendered in memory.
-- Run in the Supabase SQL Editor before starting or deploying the backend.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_type AS t
        JOIN pg_namespace AS n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public' AND t.typname = 'user_role'
    ) THEN
        CREATE TYPE public.user_role AS ENUM ('SUPER_ADMIN', 'ADMIN', 'STAFF');
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS public.users (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(120) NOT NULL,
    email           VARCHAR(320) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    role            public.user_role NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email
    ON public.users (email);

CREATE TABLE IF NOT EXISTS public.participants (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(160) NOT NULL,
    email       VARCHAR(320) NOT NULL,
    team_name   VARCHAR(160),
    college     VARCHAR(160),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_participants_email ON public.participants (email);

-- Manually added participants may omit team and college. CSV import still requires both.
ALTER TABLE public.participants ALTER COLUMN team_name DROP NOT NULL;
ALTER TABLE public.participants ALTER COLUMN college DROP NOT NULL;

CREATE TABLE IF NOT EXISTS public.certificate_templates (
    id                  SERIAL PRIMARY KEY,
    name                VARCHAR(160) NOT NULL,
    file_data           BYTEA,
    file_type           VARCHAR(10) NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    name_x              DOUBLE PRECISION NOT NULL DEFAULT 50.0,
    name_y              DOUBLE PRECISION NOT NULL DEFAULT 50.0,
    name_font_size      INTEGER NOT NULL DEFAULT 36,
    name_alignment      VARCHAR(10) NOT NULL DEFAULT 'center',
    name_color          VARCHAR(7) NOT NULL DEFAULT '#171717',
    college_x           DOUBLE PRECISION NOT NULL DEFAULT 50.0,
    college_y           DOUBLE PRECISION NOT NULL DEFAULT 62.0,
    college_font_size   INTEGER NOT NULL DEFAULT 22,
    college_alignment   VARCHAR(10) NOT NULL DEFAULT 'center',
    college_color       VARCHAR(7) NOT NULL DEFAULT '#171717',
    team_x              DOUBLE PRECISION NOT NULL DEFAULT 50.0,
    team_y              DOUBLE PRECISION NOT NULL DEFAULT 74.0,
    team_font_size      INTEGER NOT NULL DEFAULT 22,
    team_alignment      VARCHAR(10) NOT NULL DEFAULT 'center',
    team_color          VARCHAR(7) NOT NULL DEFAULT '#171717',
    include_college     BOOLEAN NOT NULL DEFAULT TRUE,
    include_team        BOOLEAN NOT NULL DEFAULT FALSE,
    name_font_family    VARCHAR(40) NOT NULL DEFAULT 'helvetica',
    name_bold           BOOLEAN NOT NULL DEFAULT TRUE,
    name_italic         BOOLEAN NOT NULL DEFAULT FALSE,
    college_font_family VARCHAR(40) NOT NULL DEFAULT 'helvetica',
    college_bold        BOOLEAN NOT NULL DEFAULT FALSE,
    college_italic      BOOLEAN NOT NULL DEFAULT FALSE,
    team_font_family    VARCHAR(40) NOT NULL DEFAULT 'helvetica',
    team_bold           BOOLEAN NOT NULL DEFAULT FALSE,
    team_italic         BOOLEAN NOT NULL DEFAULT FALSE,
    created_by          INTEGER NOT NULL REFERENCES public.users (id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Existing templates keep printing college and do not print team.
ALTER TABLE public.certificate_templates
    ADD COLUMN IF NOT EXISTS team_x DOUBLE PRECISION NOT NULL DEFAULT 50.0,
    ADD COLUMN IF NOT EXISTS team_y DOUBLE PRECISION NOT NULL DEFAULT 74.0,
    ADD COLUMN IF NOT EXISTS team_font_size INTEGER NOT NULL DEFAULT 22,
    ADD COLUMN IF NOT EXISTS team_alignment VARCHAR(10) NOT NULL DEFAULT 'center',
    ADD COLUMN IF NOT EXISTS team_color VARCHAR(7) NOT NULL DEFAULT '#171717',
    ADD COLUMN IF NOT EXISTS include_college BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS include_team BOOLEAN NOT NULL DEFAULT FALSE;

-- Per-field fonts. Defaults match the original look: Helvetica Bold name, Helvetica college and team.
ALTER TABLE public.certificate_templates
    ADD COLUMN IF NOT EXISTS name_font_family VARCHAR(40) NOT NULL DEFAULT 'helvetica',
    ADD COLUMN IF NOT EXISTS name_bold BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS name_italic BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS college_font_family VARCHAR(40) NOT NULL DEFAULT 'helvetica',
    ADD COLUMN IF NOT EXISTS college_bold BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS college_italic BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS team_font_family VARCHAR(40) NOT NULL DEFAULT 'helvetica',
    ADD COLUMN IF NOT EXISTS team_bold BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS team_italic BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_certificate_template_active
    ON public.certificate_templates (is_active)
    WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS public.email_templates (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(160) NOT NULL,
    subject      VARCHAR(300) NOT NULL,
    body         TEXT NOT NULL,
    created_by   INTEGER NOT NULL REFERENCES public.users (id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.email_campaigns (
    id                       SERIAL PRIMARY KEY,
    name                     VARCHAR(160) NOT NULL,
    email_template_id        INTEGER REFERENCES public.email_templates (id) ON DELETE SET NULL,
    certificate_template_id  INTEGER REFERENCES public.certificate_templates (id) ON DELETE SET NULL,
    sender_name              VARCHAR(160) NOT NULL,
    reply_to                 VARCHAR(320),
    subject                  VARCHAR(300) NOT NULL,
    body                     TEXT NOT NULL,
    attach_certificate       BOOLEAN NOT NULL DEFAULT TRUE,
    allow_resend              BOOLEAN NOT NULL DEFAULT FALSE,
    certificate_include_college BOOLEAN NOT NULL DEFAULT TRUE,
    certificate_include_team    BOOLEAN NOT NULL DEFAULT FALSE,
    status                  VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
    created_by               INTEGER NOT NULL REFERENCES public.users (id),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at               TIMESTAMPTZ,
    completed_at             TIMESTAMPTZ
);

-- CREATE TABLE IF NOT EXISTS does not update an existing table. This keeps
-- existing campaign rows when adding the current resend authorization field.
ALTER TABLE public.email_campaigns
    ADD COLUMN IF NOT EXISTS allow_resend BOOLEAN NOT NULL DEFAULT FALSE;

-- Each campaign keeps the certificate include settings it started with.
ALTER TABLE public.email_campaigns
    ADD COLUMN IF NOT EXISTS certificate_include_college BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS certificate_include_team BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS public.email_deliveries (
    id                   SERIAL PRIMARY KEY,
    campaign_id          INTEGER NOT NULL REFERENCES public.email_campaigns (id) ON DELETE CASCADE,
    -- Older deliveries may hold Google Sheet row IDs. Snapshots remain valid after CSV migration.
    participant_id       INTEGER NOT NULL,
    participant_key      VARCHAR(320) NOT NULL,
    participant_name     VARCHAR(160) NOT NULL,
    college              VARCHAR(160),
    email                VARCHAR(320) NOT NULL,
    status               VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    provider_message_id  VARCHAR(255),
    attempt_count        INTEGER NOT NULL DEFAULT 0,
    sent_at              TIMESTAMPTZ,
    failed_at            TIMESTAMPTZ,
    failure_reason       TEXT,
    CONSTRAINT uq_email_delivery_campaign_participant_key
        UNIQUE (campaign_id, participant_key)
);

CREATE INDEX IF NOT EXISTS ix_email_deliveries_campaign_id
    ON public.email_deliveries (campaign_id);

COMMIT;

-- Other defaults above mirror SQLAlchemy's Python-side insert defaults. SQLAlchemy
-- still sets updated_at itself on ORM updates; there is no database update trigger.
-- This bootstrap does not insert an admin. Seed one with `python -m app.db.seed`.
