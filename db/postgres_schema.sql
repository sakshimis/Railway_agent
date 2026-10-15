-- Foundation for a future PostgreSQL-backed deployment.
-- This file does not migrate the current local JSON/SQLite application.
CREATE TABLE app_users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('user', 'admin')),
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE journeys (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT REFERENCES app_users(id) ON DELETE SET NULL,
    origin_code TEXT NOT NULL,
    destination_code TEXT NOT NULL,
    travel_date DATE NOT NULL,
    constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (origin_code <> destination_code)
);
CREATE INDEX journeys_user_created_idx ON journeys (user_id, created_at DESC);

CREATE TABLE prediction_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    journey_id BIGINT REFERENCES journeys(id) ON DELETE SET NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    input_features JSONB NOT NULL,
    prediction JSONB NOT NULL,
    actual_outcome JSONB,
    predicted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome_recorded_at TIMESTAMPTZ
);
CREATE INDEX prediction_model_time_idx ON prediction_events (model_name, predicted_at DESC);

CREATE TABLE recommendation_feedback (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    journey_id BIGINT REFERENCES journeys(id) ON DELETE SET NULL,
    train_number TEXT NOT NULL,
    helpful BOOLEAN NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE saved_itineraries (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    journey_id BIGINT NOT NULL REFERENCES journeys(id),
    reference TEXT NOT NULL UNIQUE,
    train_number TEXT NOT NULL,
    approved_by_user BOOLEAN NOT NULL CHECK (approved_by_user),
    status TEXT NOT NULL DEFAULT 'saved',
    saved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_versions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_name TEXT NOT NULL,
    version TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    metrics JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'retired')),
    approved_by BIGINT REFERENCES app_users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (model_name, version)
);
CREATE UNIQUE INDEX one_active_model_version_idx ON model_versions (model_name) WHERE status = 'active';

CREATE TABLE audit_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id BIGINT REFERENCES app_users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_events_time_idx ON audit_events (occurred_at DESC);
