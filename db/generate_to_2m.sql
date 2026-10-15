-- Run with psql -v target_rows=2000000 -f db/generate_to_2m.sql.
CREATE TEMP TABLE scale_batch AS
SELECT n::BIGINT AS id,
       ((n - 1) % 20 + 1)::INTEGER AS machine_id,
       DATE_TRUNC('hour', NOW()) - (((n - 1) / 20) * INTERVAL '1 hour') AS recorded_at,
       (42 + n % 19)::NUMERIC(6, 2) AS operating_minutes,
       60::NUMERIC(6, 2) AS planned_minutes,
       5::NUMERIC(6, 2) AS ideal_cycle_seconds,
       (280 + n % 120)::INTEGER AS total_count,
       (n % 9)::INTEGER AS defect_count
FROM generate_series(
    (SELECT COALESCE(MAX(id), 0) + 1 FROM production_records),
    :target_rows::BIGINT
) AS n;

INSERT INTO production_records (
    id, machine_id, recorded_at, planned_minutes, operating_minutes,
    ideal_cycle_seconds, total_count, good_count
)
SELECT id, machine_id, recorded_at, planned_minutes, operating_minutes,
       ideal_cycle_seconds, total_count, total_count - defect_count
FROM scale_batch
ON CONFLICT (id) DO NOTHING;

INSERT INTO defect_events (id, production_record_id, cause_id, quantity)
SELECT id, id, ((id - 1) % 5 + 1)::INTEGER, defect_count
FROM scale_batch
WHERE defect_count > 0
ON CONFLICT (id) DO NOTHING;

INSERT INTO downtime_events (id, machine_id, cause_id, started_at, duration_minutes)
SELECT id, machine_id, ((id - 1) % 5 + 1)::INTEGER,
       recorded_at, planned_minutes - operating_minutes
FROM scale_batch
WHERE operating_minutes < planned_minutes
ON CONFLICT (id) DO NOTHING;

DROP TABLE scale_batch;