import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from app.analytics import calculate_defect_rate, calculate_oee, evaluate_threshold

if os.getenv("DATABASE_URL"):
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
else:
    engine = create_engine(URL.create(
        "postgresql+psycopg",
        username=os.getenv("POSTGRES_USER", "manufacturing"),
        password=os.getenv("POSTGRES_PASSWORD", "manufacturing_dev_only"),
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        database=os.getenv("POSTGRES_DB", "manufacturing"),
    ), pool_pre_ping=True)
logger = logging.getLogger(__name__)


def ensure_alert_schema() -> None:
    statements = [
        """CREATE TABLE IF NOT EXISTS alert_thresholds (
            metric TEXT PRIMARY KEY CHECK (metric IN ('availability', 'defect_rate')),
            warning_threshold NUMERIC NOT NULL CHECK (warning_threshold BETWEEN 0 AND 1),
            critical_threshold NUMERIC NOT NULL CHECK (critical_threshold BETWEEN 0 AND 1),
            comparison TEXT NOT NULL CHECK (comparison IN ('below', 'above')),
            enabled BOOLEAN NOT NULL DEFAULT TRUE
        )""",
        """CREATE TABLE IF NOT EXISTS alert_records (
            id BIGSERIAL PRIMARY KEY,
            machine_id INTEGER NOT NULL REFERENCES machines(id),
            metric TEXT NOT NULL,
            observed_value NUMERIC NOT NULL,
            threshold NUMERIC NOT NULL,
            severity TEXT NOT NULL CHECK (severity IN ('warning', 'critical')),
            window_start TIMESTAMPTZ NOT NULL,
            first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at TIMESTAMPTZ,
            UNIQUE (machine_id, metric, window_start)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_alert_records_active ON alert_records(resolved_at, last_seen DESC)",
        "CREATE INDEX IF NOT EXISTS idx_defect_record ON defect_events(production_record_id)",
        """INSERT INTO alert_thresholds (metric, warning_threshold, critical_threshold, comparison)
            VALUES ('availability', 0.75, 0.60, 'below'), ('defect_rate', 0.04, 0.08, 'above')
            ON CONFLICT (metric) DO NOTHING""",
        """CREATE OR REPLACE VIEW vw_oee_daily AS
            WITH daily AS (
                SELECT DATE_TRUNC('day', recorded_at)::DATE AS day,
                       SUM(operating_minutes) AS operating_minutes,
                       SUM(planned_minutes) AS planned_minutes,
                       SUM(total_count * ideal_cycle_seconds) AS ideal_output_seconds,
                       SUM(good_count) AS good_count,
                       SUM(total_count) AS total_count
                FROM production_records
                GROUP BY DATE_TRUNC('day', recorded_at)::DATE
            )
            SELECT day,
                   operating_minutes / NULLIF(planned_minutes, 0) AS availability,
                   ideal_output_seconds / NULLIF(operating_minutes * 60, 0) AS performance,
                   good_count::NUMERIC / NULLIF(total_count, 0) AS quality,
                   COALESCE(operating_minutes / NULLIF(planned_minutes, 0), 0) *
                   COALESCE(ideal_output_seconds / NULLIF(operating_minutes * 60, 0), 0) *
                   COALESCE(good_count::NUMERIC / NULLIF(total_count, 0), 0) AS oee
            FROM daily""",
        """CREATE OR REPLACE VIEW vw_defect_pareto AS
            WITH counts AS (
                SELECT cause.name AS cause, SUM(event.quantity) AS defect_count
                FROM defect_events AS event
                JOIN defect_causes AS cause ON cause.id = event.cause_id
                JOIN production_records AS production ON production.id = event.production_record_id
                WHERE production.recorded_at >= NOW() - INTERVAL '7 days'
                GROUP BY cause.name
            )
            SELECT cause, defect_count,
                   defect_count::NUMERIC / NULLIF(SUM(defect_count) OVER (), 0) AS percent,
                   SUM(defect_count) OVER (ORDER BY defect_count DESC, cause)::NUMERIC /
                       NULLIF(SUM(defect_count) OVER (), 0) AS cumulative_percent
            FROM counts""",
        """CREATE OR REPLACE VIEW vw_downtime_by_cause AS
            SELECT cause.name AS cause, SUM(event.duration_minutes) AS downtime_minutes,
                   COUNT(*) AS event_count
            FROM downtime_events AS event
            JOIN downtime_causes AS cause ON cause.id = event.cause_id
            WHERE event.started_at >= NOW() - INTERVAL '7 days'
            GROUP BY cause.name""",
        """CREATE OR REPLACE VIEW vw_machine_health AS
            SELECT machine.id AS machine_id, machine.name AS machine_name,
                   machine.production_line, machine.model,
                   COALESCE(SUM(production.total_count), 0) AS produced,
                   COALESCE(SUM(production.total_count - production.good_count), 0) AS defects,
                   COALESCE(SUM(production.operating_minutes) /
                       NULLIF(SUM(production.planned_minutes), 0), 0) AS availability,
                   MAX(production.recorded_at) AS last_seen
            FROM machines AS machine
            LEFT JOIN production_records AS production
              ON production.machine_id = machine.id
             AND production.recorded_at >= NOW() - INTERVAL '24 hours'
            GROUP BY machine.id""",
    ]
    try:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    except SQLAlchemyError as error:
        logger.exception("Unable to initialize alert tables")
        raise RuntimeError("Unable to initialize alert tables") from error


class AlertThresholdUpdate(BaseModel):
    warning_threshold: float = Field(ge=0, le=1)
    critical_threshold: float = Field(ge=0, le=1)


class AlertThresholdResponse(AlertThresholdUpdate):
    metric: Literal["availability", "defect_rate"]
    comparison: Literal["below", "above"]
    enabled: bool


def process_alerts() -> None:
    try:
        thresholds = fetch_all("SELECT * FROM alert_thresholds WHERE enabled")
        machines = fetch_all("""
            SELECT machine_id,
                   COALESCE(SUM(operating_minutes) / NULLIF(SUM(planned_minutes), 0), 0) AS availability,
                   COALESCE(SUM(total_count - good_count)::NUMERIC / NULLIF(SUM(total_count), 0), 0) AS defect_rate,
                   MAX(recorded_at) AS observed_at
            FROM production_records
            WHERE recorded_at >= NOW() - INTERVAL '24 hours'
            GROUP BY machine_id
        """)
        upsert = text("""
            INSERT INTO alert_records (
                machine_id, metric, observed_value, threshold, severity, window_start, first_seen, last_seen
            ) VALUES (
                :machine_id, :metric, :observed_value, :threshold, :severity, :window_start, NOW(), NOW()
            )
            ON CONFLICT (machine_id, metric, window_start) DO UPDATE SET
                observed_value = EXCLUDED.observed_value,
                threshold = EXCLUDED.threshold,
                severity = EXCLUDED.severity,
                last_seen = NOW(),
                resolved_at = NULL
        """)
        with engine.begin() as connection:
            for machine in machines:
                for threshold in thresholds:
                    observed = float(machine[threshold["metric"]])
                    warning = float(threshold["warning_threshold"])
                    critical = float(threshold["critical_threshold"])
                    evaluation = evaluate_threshold(
                        observed, warning, critical, threshold["comparison"]
                    )
                    if evaluation is None:
                        continue
                    severity, breached_threshold = evaluation
                    timestamp = machine["observed_at"]
                    window_start = timestamp.replace(minute=0, second=0, microsecond=0)
                    connection.execute(upsert, {
                        "machine_id": machine["machine_id"],
                        "metric": threshold["metric"],
                        "observed_value": observed,
                        "threshold": breached_threshold,
                        "severity": severity,
                        "window_start": window_start,
                    })
            connection.execute(text("""
                UPDATE alert_records SET resolved_at = NOW()
                WHERE resolved_at IS NULL AND last_seen < NOW() - INTERVAL '2 minutes'
            """))
    except (SQLAlchemyError, HTTPException):
        logger.exception("Alert processing failed")


async def alert_processing_loop() -> None:
    while True:
        await asyncio.sleep(60)
        await asyncio.to_thread(process_alerts)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(ensure_alert_schema)
    await asyncio.to_thread(process_alerts)
    task = asyncio.create_task(alert_processing_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

app = FastAPI(title="Manufacturing Analytics API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["GET", "PUT"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str
    database: str


class TrendPoint(BaseModel):
    date: date
    oee: float


class KpiResponse(BaseModel):
    oee: float
    availability: float
    performance: float
    quality: float
    total_produced: int
    total_defects: int
    trend: list[TrendPoint]


class DowntimeSummary(BaseModel):
    cause: str
    minutes: float
    events: int


class ParetoCause(BaseModel):
    cause: str
    count: int
    percent: float
    cumulative_percent: float


class DefectSummary(BaseModel):
    total_defects: int
    defect_rate: float
    pareto: list[ParetoCause]


class MachineSummary(BaseModel):
    id: int
    name: str
    production_line: str
    model: str
    produced: int
    defects: int
    availability: float
    last_seen: datetime | None
    status: Literal["healthy", "attention"]


class Alert(BaseModel):
    machine_id: int
    metric: str
    observed_value: float
    threshold: float
    severity: str
    timestamp: datetime


def fetch_all(query: str, **params: Any) -> list[dict[str, Any]]:
    try:
        with engine.connect() as connection:
            return [dict(row) for row in connection.execute(text(query), params).mappings()]
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Manufacturing database is unavailable") from error


@app.get("/health", response_model=HealthResponse)
def health() -> dict[str, str]:
    fetch_all("SELECT 1 AS ready")
    return {"status": "ok", "database": "connected"}


@app.get("/api/dashboard/kpis", response_model=KpiResponse)
def dashboard_kpis() -> dict[str, Any]:
    rows = fetch_all("""
        SELECT SUM(operating_minutes) AS operating_minutes,
               SUM(planned_minutes) AS planned_minutes,
               SUM(total_count * ideal_cycle_seconds) AS ideal_output_seconds,
               SUM(good_count) AS good_count,
               SUM(total_count) AS total_count
        FROM production_records
        WHERE recorded_at >= NOW() - INTERVAL '7 days'
    """)
    trend = fetch_all("""
        SELECT DATE_TRUNC('day', recorded_at)::DATE AS date,
               COALESCE(
                   SUM(operating_minutes) / NULLIF(SUM(planned_minutes), 0) *
                   SUM(total_count * ideal_cycle_seconds) / NULLIF(SUM(operating_minutes * 60), 0) *
                   SUM(good_count)::NUMERIC / NULLIF(SUM(total_count), 0), 0
               ) AS oee
        FROM production_records
        WHERE recorded_at >= NOW() - INTERVAL '14 days'
        GROUP BY DATE_TRUNC('day', recorded_at)
        ORDER BY date
    """)
    result = rows[0]
    total_produced = int(result["total_count"] or 0)
    total_defects = total_produced - int(result["good_count"] or 0)
    result.update(calculate_oee(
        float(result["operating_minutes"] or 0),
        float(result["planned_minutes"] or 0),
        float(result["ideal_output_seconds"] or 0),
        float(result["good_count"] or 0),
        float(result["total_count"] or 0),
    ))
    result["total_produced"] = total_produced
    result["total_defects"] = total_defects
    result["trend"] = [{"date": str(row["date"]), "oee": float(row["oee"])} for row in trend]
    return result


@app.get("/api/dashboard/downtime", response_model=list[DowntimeSummary])
def dashboard_downtime() -> list[dict[str, Any]]:
    rows = fetch_all("""
        SELECT cause.name AS cause, SUM(event.duration_minutes) AS minutes,
               COUNT(*) AS events
        FROM downtime_events AS event
        JOIN downtime_causes AS cause ON cause.id = event.cause_id
        WHERE event.started_at >= NOW() - INTERVAL '7 days'
        GROUP BY cause.name
        ORDER BY minutes DESC
    """)
    return [{**row, "minutes": float(row["minutes"]), "events": int(row["events"])} for row in rows]


@app.get("/api/dashboard/defects", response_model=DefectSummary)
def dashboard_defects() -> dict[str, Any]:
    rows = fetch_all("""
        SELECT cause.name AS cause, SUM(event.quantity) AS count
        FROM defect_events AS event
        JOIN defect_causes AS cause ON cause.id = event.cause_id
        JOIN production_records AS production ON production.id = event.production_record_id
        WHERE production.recorded_at >= NOW() - INTERVAL '7 days'
        GROUP BY cause.name
        ORDER BY count DESC
    """)
    total = sum(int(row["count"]) for row in rows)
    running = 0
    pareto = []
    for row in rows:
        count = int(row["count"])
        running += count
        pareto.append({
            "cause": row["cause"], "count": count,
            "percent": count / total if total else 0,
            "cumulative_percent": running / total if total else 0,
        })
    totals = fetch_all("""
        SELECT COALESCE(SUM(total_count - good_count), 0) AS defects,
               COALESCE(SUM(total_count), 0) AS produced
        FROM production_records
        WHERE recorded_at >= NOW() - INTERVAL '7 days'
    """)[0]
    return {
        "total_defects": int(totals["defects"]),
        "defect_rate": calculate_defect_rate(int(totals["defects"]), int(totals["produced"])),
        "pareto": pareto,
    }


@app.get("/api/machines", response_model=list[MachineSummary])
def machines() -> list[dict[str, Any]]:
    rows = fetch_all("""
        SELECT machine.id, machine.name, machine.production_line, machine.model,
               COALESCE(SUM(production.total_count), 0) AS produced,
               COALESCE(SUM(production.total_count - production.good_count), 0) AS defects,
               COALESCE(SUM(production.operating_minutes) / NULLIF(SUM(production.planned_minutes), 0), 0) AS availability,
               MAX(production.recorded_at) AS last_seen
        FROM machines AS machine
        LEFT JOIN production_records AS production
          ON production.machine_id = machine.id
         AND production.recorded_at >= NOW() - INTERVAL '24 hours'
        GROUP BY machine.id
        ORDER BY machine.id
    """)
    for row in rows:
        row["produced"] = int(row["produced"])
        row["defects"] = int(row["defects"])
        row["availability"] = float(row["availability"])
        row["status"] = "attention" if row["availability"] < 0.75 else "healthy"
        row["last_seen"] = row["last_seen"].isoformat() if row["last_seen"] else None
    return rows


@app.get("/api/alert-thresholds", response_model=list[AlertThresholdResponse])
def get_alert_thresholds() -> list[dict[str, Any]]:
    return fetch_all("SELECT * FROM alert_thresholds ORDER BY metric")


@app.put("/api/alert-thresholds/{metric}", response_model=AlertThresholdResponse)
def update_alert_threshold(metric: Literal["availability", "defect_rate"], body: AlertThresholdUpdate) -> dict[str, Any]:
    valid_order = (
        body.critical_threshold <= body.warning_threshold
        if metric == "availability"
        else body.critical_threshold >= body.warning_threshold
    )
    if not valid_order:
        raise HTTPException(status_code=422, detail="Critical threshold must be more severe than warning threshold")
    try:
        with engine.begin() as connection:
            row = connection.execute(text("""
                UPDATE alert_thresholds
                SET warning_threshold = :warning, critical_threshold = :critical
                WHERE metric = :metric
                RETURNING metric, warning_threshold, critical_threshold, comparison, enabled
            """), {
                "warning": body.warning_threshold,
                "critical": body.critical_threshold,
                "metric": metric,
            }).mappings().one_or_none()
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Manufacturing database is unavailable") from error
    if row is None:
        raise HTTPException(status_code=404, detail="Alert threshold not found")
    return dict(row)


@app.get("/api/alerts", response_model=list[Alert])
def alerts() -> list[dict[str, Any]]:
    return fetch_all("""
        SELECT machine_id, metric, observed_value, threshold, severity, last_seen AS timestamp
        FROM alert_records
        WHERE resolved_at IS NULL
        ORDER BY CASE severity WHEN 'critical' THEN 0 ELSE 1 END, last_seen DESC
    """)