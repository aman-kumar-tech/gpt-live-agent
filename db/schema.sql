-- Schema for the AI voice receptionist demo.
-- Deliberately flat for v1: no dedicated slots/capacity table, no soft-delete columns.
-- Catalog/lab tables are shaped to load directly from data.json (see db/seed.py).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS patients (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name       text NOT NULL,
    phone_number    text NOT NULL,
    date_of_birth   date,
    gender          text,
    email           text,
    address         text,
    created_at      timestamp NOT NULL DEFAULT now(),
    updated_at      timestamp NOT NULL DEFAULT now()
);
-- Households share phone numbers, so this is an index, not a unique constraint.
CREATE INDEX IF NOT EXISTS idx_patients_phone ON patients (phone_number);

CREATE TABLE IF NOT EXISTS tests (
    id                          serial PRIMARY KEY,
    code                        text UNIQUE NOT NULL,
    name                        text NOT NULL,
    aliases                     jsonb NOT NULL DEFAULT '[]',
    description                 text,
    category                    text,
    price                       numeric(10, 2) NOT NULL,
    sample_type                 text,
    home_collection_available   boolean NOT NULL DEFAULT true,
    turnaround_time_hours       integer,
    fasting_required            boolean NOT NULL DEFAULT false,
    fasting_instructions        text,
    active                      boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS packages (
    id                      serial PRIMARY KEY,
    code                    text UNIQUE,
    name                    text NOT NULL,
    category                text,
    description             text,
    value_proposition       text,
    price                   numeric(10, 2) NOT NULL,
    fasting_required        boolean NOT NULL DEFAULT false,
    fasting_instructions    text,
    active                  boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS package_tests (
    package_id   integer NOT NULL REFERENCES packages (id) ON DELETE CASCADE,
    test_id      integer NOT NULL REFERENCES tests (id) ON DELETE CASCADE,
    PRIMARY KEY (package_id, test_id)
);

CREATE TABLE IF NOT EXISTS offers (
    id                serial PRIMARY KEY,
    title             text NOT NULL,
    description       text,
    -- 'other' covers real-world offers with no single computable discount
    -- (e.g. a "book 2, get a bundle price" family offer) -- format_note and
    -- eligibility_note carry the human-readable terms for those.
    discount_type     text NOT NULL CHECK (discount_type IN ('percent', 'flat', 'other')),
    discount_value    numeric(10, 2),
    format_note       text,
    eligibility_note  text,
    applies_to_type   text NOT NULL CHECK (applies_to_type IN ('test', 'package', 'all')),
    applies_to_id     integer,
    start_date        date NOT NULL,
    end_date          date NOT NULL,
    active            boolean NOT NULL DEFAULT true,
    CONSTRAINT offers_discount_value_set
        CHECK (discount_type = 'other' OR discount_value IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS reports (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id            uuid NOT NULL REFERENCES patients (id) ON DELETE CASCADE,
    test_id               integer REFERENCES tests (id),
    package_id            integer REFERENCES packages (id),
    status                text NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'processing', 'ready', 'delivered')),
    sample_collected_at   timestamp,
    ready_at              timestamp,
    report_url            text,
    created_at            timestamp NOT NULL DEFAULT now(),
    CONSTRAINT reports_test_or_package_set
        CHECK (test_id IS NOT NULL OR package_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_reports_patient ON reports (patient_id);

CREATE TABLE IF NOT EXISTS appointments (
    id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    reference_code            text UNIQUE NOT NULL,
    patient_id                uuid NOT NULL REFERENCES patients (id) ON DELETE CASCADE,
    type                      text NOT NULL CHECK (type IN ('lab_visit', 'home_collection')),
    status                    text NOT NULL DEFAULT 'booked'
                              CHECK (status IN ('booked', 'rescheduled', 'cancelled', 'completed')),
    scheduled_at              timestamp NOT NULL,
    address                   text,
    home_collection_fee       numeric(10, 2) NOT NULL DEFAULT 0,
    notes                     text,
    previous_appointment_id   uuid REFERENCES appointments (id),
    created_at                timestamp NOT NULL DEFAULT now(),
    updated_at                timestamp NOT NULL DEFAULT now(),
    CONSTRAINT appointments_home_collection_address
        CHECK (type <> 'home_collection' OR address IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_appointments_patient ON appointments (patient_id);
CREATE INDEX IF NOT EXISTS idx_appointments_scheduled_at ON appointments (scheduled_at);

CREATE TABLE IF NOT EXISTS appointment_items (
    id               serial PRIMARY KEY,
    appointment_id   uuid NOT NULL REFERENCES appointments (id) ON DELETE CASCADE,
    test_id          integer REFERENCES tests (id),
    package_id       integer REFERENCES packages (id),
    CONSTRAINT appointment_items_test_or_package_set
        CHECK (test_id IS NOT NULL OR package_id IS NOT NULL)
);

-- Singleton row (id = 1): the lab's own identity/logistics, never hardcoded
-- in prompts or the frontend. `metadata` and `operational_rules` carry the
-- rest of data.json's lab_metadata / operational_rules verbatim, for fields
-- that don't need their own column to be queried by the tools layer.
CREATE TABLE IF NOT EXISTS lab_info (
    id                  integer PRIMARY KEY DEFAULT 1,
    name                text NOT NULL,
    address             text NOT NULL,
    phone_number        text NOT NULL,
    hours               jsonb NOT NULL,
    email               text,
    metadata            jsonb NOT NULL DEFAULT '{}',
    operational_rules   jsonb NOT NULL DEFAULT '{}',
    updated_at          timestamp NOT NULL DEFAULT now(),
    CONSTRAINT lab_info_singleton CHECK (id = 1)
);

-- Symptom -> test/package routing (data.json's symptoms_and_conditions_routing).
-- Informational only: the matching tool must frame this as "callers with
-- these symptoms often get tested for X", never as a diagnosis.
CREATE TABLE IF NOT EXISTS symptom_routes (
    id                        serial PRIMARY KEY,
    condition_keyword         text NOT NULL,
    symptoms                  jsonb NOT NULL DEFAULT '[]',
    recommended_test_codes    jsonb NOT NULL DEFAULT '[]',
    recommended_package_codes jsonb NOT NULL DEFAULT '[]',
    voice_script_hint         text
);

-- Observability: one row per usage/latency/error/close event emitted by
-- AgentSession during a call (see receptionist/observability.py). Kept as a
-- raw event log rather than pre-aggregated so any report can be built later
-- with a SQL query against it.
CREATE TABLE IF NOT EXISTS call_events (
    id                serial PRIMARY KEY,
    call_session_id   text NOT NULL,
    event_type        text NOT NULL CHECK (event_type IN ('usage', 'latency', 'error', 'close')),
    payload           jsonb NOT NULL,
    created_at        timestamp NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_call_events_session ON call_events (call_session_id);
CREATE INDEX IF NOT EXISTS idx_call_events_type_created ON call_events (event_type, created_at);

-- Structural guardrail: every write-capable tool proposes here first; only a
-- confirm resume (see the LangGraph graphs) is allowed to act on it.
CREATE TABLE IF NOT EXISTS pending_actions (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    call_session_id  text NOT NULL,
    action_type      text NOT NULL
                     CHECK (action_type IN (
                         'register_patient', 'book_appointment',
                         'reschedule_appointment', 'cancel_appointment'
                     )),
    payload          jsonb NOT NULL,
    status           text NOT NULL DEFAULT 'proposed'
                     CHECK (status IN ('proposed', 'confirmed', 'rejected', 'expired')),
    created_at       timestamp NOT NULL DEFAULT now(),
    expires_at       timestamp NOT NULL DEFAULT (now() + interval '10 minutes'),
    resolved_at      timestamp
);
CREATE INDEX IF NOT EXISTS idx_pending_actions_session ON pending_actions (call_session_id, status);
