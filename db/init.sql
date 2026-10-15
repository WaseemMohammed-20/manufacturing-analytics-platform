CREATE TABLE IF NOT EXISTS machines (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    production_line TEXT NOT NULL,
    model TEXT NOT NULL,
    installed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS defect_causes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS downtime_causes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS production_records (
    id BIGINT PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES machines(id),
    recorded_at TIMESTAMPTZ NOT NULL,
    planned_minutes NUMERIC(6, 2) NOT NULL,
    operating_minutes NUMERIC(6, 2) NOT NULL,
    ideal_cycle_seconds NUMERIC(6, 2) NOT NULL,
    total_count INTEGER NOT NULL,
    good_count INTEGER NOT NULL,
    CHECK (planned_minutes > 0),
    CHECK (operating_minutes >= 0 AND operating_minutes <= planned_minutes),
    CHECK (good_count >= 0 AND good_count <= total_count)
);

CREATE TABLE IF NOT EXISTS defect_events (
    id BIGINT PRIMARY KEY,
    production_record_id BIGINT NOT NULL REFERENCES production_records(id),
    cause_id INTEGER NOT NULL REFERENCES defect_causes(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0)
);

CREATE TABLE IF NOT EXISTS downtime_events (
    id BIGINT PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES machines(id),
    cause_id INTEGER NOT NULL REFERENCES downtime_causes(id),
    started_at TIMESTAMPTZ NOT NULL,
    duration_minutes NUMERIC(7, 2) NOT NULL CHECK (duration_minutes > 0)
);

CREATE INDEX IF NOT EXISTS idx_production_recorded_at ON production_records(recorded_at);
CREATE INDEX IF NOT EXISTS idx_production_machine_time ON production_records(machine_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_defect_record ON defect_events(production_record_id);
CREATE INDEX IF NOT EXISTS idx_defect_cause ON defect_events(cause_id);
CREATE INDEX IF NOT EXISTS idx_downtime_machine_time ON downtime_events(machine_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_downtime_cause ON downtime_events(cause_id);

INSERT INTO machines (id, name, production_line, model, installed_at)
SELECT machine_id, 'CNC-' || LPAD(machine_id::TEXT, 2, '0'),
       'Line ' || ((machine_id - 1) / 5 + 1),
       CASE machine_id % 3 WHEN 0 THEN 'M-500' WHEN 1 THEN 'MX-220' ELSE 'A-410' END,
       NOW() - ((machine_id % 8) * INTERVAL '180 days')
FROM generate_series(1, 20) AS machine_id
ON CONFLICT (id) DO NOTHING;

INSERT INTO defect_causes (id, name) VALUES
    (1, 'Surface finish'), (2, 'Dimensional'), (3, 'Material'),
    (4, 'Assembly'), (5, 'Other')
ON CONFLICT (id) DO NOTHING;

INSERT INTO downtime_causes (id, name) VALUES
    (1, 'Changeover'), (2, 'Mechanical'), (3, 'Material shortage'),
    (4, 'Quality hold'), (5, 'Unplanned maintenance')
ON CONFLICT (id) DO NOTHING;

-- 20 machines x 500 hourly observations = 10,000 fact rows (about 21 days).
WITH generated AS (
    SELECT n,
           ((n - 1) % 20 + 1)::INTEGER AS machine_id,
           DATE_TRUNC('hour', NOW()) - (((n - 1) / 20) * INTERVAL '1 hour') AS recorded_at,
         CASE WHEN (n - 1) % 20 + 1 = 20 AND n <= 480
             THEN 24 ELSE (42 + n % 19)::NUMERIC(6, 2) END AS operating_minutes,
           (280 + n % 120)::INTEGER AS total_count,
         CASE WHEN (n - 1) % 20 + 1 = 20 AND n <= 480
             THEN 45 ELSE (n % 9)::INTEGER END AS defect_count
    FROM generate_series(1, 10000) AS n
)
INSERT INTO production_records (
    id, machine_id, recorded_at, planned_minutes, operating_minutes,
    ideal_cycle_seconds, total_count, good_count
)
SELECT n, machine_id, recorded_at, 60, operating_minutes, 5,
       total_count, total_count - defect_count
FROM generated
ON CONFLICT (id) DO NOTHING;

WITH generated AS (
    SELECT n,
           CASE WHEN (n - 1) % 20 + 1 = 20 AND n <= 480
                THEN 45 ELSE (n % 9)::INTEGER END AS defect_count
    FROM generate_series(1, 10000) AS n
)
INSERT INTO defect_events (id, production_record_id, cause_id, quantity)
SELECT n, n, ((n - 1) % 5 + 1)::INTEGER, defect_count
FROM generated
WHERE defect_count > 0
ON CONFLICT (id) DO NOTHING;

WITH generated AS (
    SELECT n,
           ((n - 1) % 20 + 1)::INTEGER AS machine_id,
           DATE_TRUNC('hour', NOW()) - (((n - 1) / 20) * INTERVAL '1 hour') AS recorded_at,
         CASE WHEN (n - 1) % 20 + 1 = 20 AND n <= 480
             THEN 24 ELSE (42 + n % 19)::NUMERIC END AS operating_minutes
    FROM generate_series(1, 10000) AS n
)
INSERT INTO downtime_events (id, machine_id, cause_id, started_at, duration_minutes)
SELECT n, machine_id, ((n - 1) % 5 + 1)::INTEGER,
       recorded_at, 60 - operating_minutes
FROM generated
WHERE operating_minutes < 60
ON CONFLICT (id) DO NOTHING;