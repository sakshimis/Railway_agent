-- Foundation for a future PostgreSQL-backed deployment.
-- This file defines the target production relational schema.
-- Note: The running prototype uses its bundled SQLite catalog and local JSON files.

-- 1. Identity, Authentication & Roles
CREATE TABLE app_users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('user', 'admin')),
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Railway Timetable & Fare Foundation Data
CREATE TABLE stations (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    state TEXT,
    zone TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX stations_name_idx ON stations (name);

CREATE TABLE train_routes (
    train_no TEXT PRIMARY KEY,
    train_name TEXT NOT NULL,
    origin_code TEXT NOT NULL REFERENCES stations(code),
    destination_code TEXT NOT NULL REFERENCES stations(code),
    days_of_run TEXT DEFAULT 'DAILY',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE schedule_stops (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    train_no TEXT NOT NULL REFERENCES train_routes(train_no) ON DELETE CASCADE,
    station_code TEXT NOT NULL REFERENCES stations(code),
    seq INTEGER NOT NULL,
    arrival_time TIME,
    departure_time TIME,
    halt_minutes INTEGER DEFAULT 0,
    distance_km INTEGER NOT NULL DEFAULT 0,
    day_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE (train_no, seq)
);
CREATE INDEX schedule_stops_lookup_idx ON schedule_stops (station_code, train_no);

CREATE TABLE fare_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    train_no TEXT NOT NULL REFERENCES train_routes(train_no),
    origin_code TEXT NOT NULL REFERENCES stations(code),
    destination_code TEXT NOT NULL REFERENCES stations(code),
    class_code TEXT NOT NULL CHECK (class_code IN ('SL', '3A', '2A', '1A', 'CC', '2S')),
    fare_rupees NUMERIC(10, 2) NOT NULL CHECK (fare_rupees >= 0),
    snapshot_date DATE NOT NULL,
    data_source TEXT NOT NULL DEFAULT 'Kaggle October 2023 snapshot',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (train_no, origin_code, destination_code, class_code, snapshot_date)
);
CREATE INDEX fare_snapshots_route_idx ON fare_snapshots (origin_code, destination_code, class_code);

-- 3. Passenger Journeys & Search
CREATE TABLE journeys (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT REFERENCES app_users(id) ON DELETE SET NULL,
    origin_code TEXT NOT NULL REFERENCES stations(code),
    destination_code TEXT NOT NULL REFERENCES stations(code),
    travel_date DATE NOT NULL,
    constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (origin_code <> destination_code)
);
CREATE INDEX journeys_user_created_idx ON journeys (user_id, created_at DESC);

-- 4. Multi-Agent Orchestration Logs
CREATE TABLE agent_orchestration_logs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    journey_id BIGINT REFERENCES journeys(id) ON DELETE CASCADE,
    agent_name TEXT NOT NULL CHECK (agent_name IN ('TravelPlannerAgent', 'PredictionAgent', 'SupervisorAgent', 'RescueAgent', 'GovernanceAgent')),
    action TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'standby', 'failed')),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    latency_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX agent_logs_journey_idx ON agent_orchestration_logs (journey_id, created_at);

-- 5. Predictive Model Events & Metrics
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

-- 6. Booking Boundary & Saved Itineraries
CREATE TABLE saved_itineraries (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    journey_id BIGINT NOT NULL REFERENCES journeys(id),
    reference TEXT NOT NULL UNIQUE,
    train_number TEXT NOT NULL,
    passenger_name TEXT NOT NULL,
    passenger_age INTEGER CHECK (passenger_age BETWEEN 1 AND 120),
    berth_preference TEXT,
    approved_by_user BOOLEAN NOT NULL CHECK (approved_by_user),
    status TEXT NOT NULL DEFAULT 'saved_preview_only',
    boundary_disclaimer TEXT NOT NULL DEFAULT 'Educational prototype preview. No real ticket issued.',
    saved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 7. Autonomous Governance & Model Registry
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

-- 8. Security, Fraud Triage & Audit
CREATE TABLE fraud_triage_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id BIGINT REFERENCES app_users(id) ON DELETE SET NULL,
    client_ip TEXT NOT NULL,
    risk_score INTEGER NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    detected_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommended_action TEXT NOT NULL,
    analyst_review_status TEXT DEFAULT 'pending' CHECK (analyst_review_status IN ('pending', 'reviewed', 'dismissed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX fraud_triage_risk_idx ON fraud_triage_events (risk_level, created_at DESC);

CREATE TABLE audit_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id BIGINT REFERENCES app_users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    latency_ms INTEGER,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_events_time_idx ON audit_events (occurred_at DESC);
