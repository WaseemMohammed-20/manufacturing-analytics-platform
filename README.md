# Manufacturing Analytics & Alerting Platform

A local MVP for manufacturing KPIs, equipment health, quality losses, downtime, and explainable threshold alerts. The dashboard reads live API responses; PostgreSQL is the source of truth. The seed creates 20 machines and 10,000 hourly production records, with corresponding defect and downtime facts.

## Start on Windows

Requirements: Docker Desktop with the Compose plugin, and PowerShell.

```powershell
Set-Location C:\Users\wasee\Downloads\manufacturing-analytics-platform
if (-not (Test-Path .env)) { .\scripts\init-env.ps1 -ExistingDatabase }
docker compose up --build -d
docker compose ps
Push-Location frontend
npm ci
npm run build
Pop-Location
Push-Location backend
python -m unittest discover -s tests -v
Pop-Location
.\scripts\smoke-test.ps1
```

For an existing PostgreSQL data volume, `-ExistingDatabase` securely prompts for its current database password and preserves it; Superset's signing key and admin password are generated randomly without printing them. Omit `-ExistingDatabase` only for a brand-new empty data volume. If `.env` already exists, the script preserves it; rotate earlier demo credentials manually before restarting. Compose publishes ports only on `127.0.0.1`. Wait for all four containers to report `healthy`.

- Dashboard: http://localhost:8080
- FastAPI docs: http://localhost:8000/docs
- API health: http://localhost:8000/health
- Superset: http://localhost:8088 (username and generated password are stored in local `.env`)
- PostgreSQL: `localhost:5432`, database `manufacturing`

`.env` is ignored by Git. Superset creates the configured administrator only if it does not already exist; restarts preserve an existing administrator password. Change it through Superset's account UI when rotating an existing account. Do not expose this MVP directly to the public internet.

The fresh-install username is `admin` (`SUPERSET_ADMIN_USERNAME` in `.env.example`). Check whether it actually exists and has the Admin role without reading its password:

```powershell
docker compose exec -T superset python /app/manage_admin.py check
```

Only if the output says `admin: not found`, create it with hidden password prompts (no password is placed in command history or process arguments):

```powershell
docker compose exec -it superset python /app/manage_admin.py create
```

The utility refuses to modify an existing non-admin account. For a newly bootstrapped Superset metadata database, the startup script creates the configured `admin` account from `.env`; the interactive command is a recovery path.

To stop services while preserving data:

```powershell
docker compose down
```

The named `postgres_data` and `superset_home` volumes persist across restarts. The initialization SQL runs only when the PostgreSQL data volume is first created.

Do not use `docker compose down -v` for routine cleanup; that removes persistent data.

## Architecture

The React/TypeScript dashboard is served by Nginx on `localhost:8080`; Nginx forwards `/api` requests to FastAPI on port 8000. FastAPI reads PostgreSQL's `manufacturing` database and owns additive alert-table/view migrations plus the single-process alert scheduler. Superset 3.0.3 uses a separate `superset_meta` database in the same PostgreSQL server and reads the manufacturing SQL views through its registered `Manufacturing` connection. PostgreSQL data and Superset home use named Docker volumes.

## Features and API

- `GET /health`: database connectivity check; returns HTTP 503 if PostgreSQL is unavailable.
- `GET /api/dashboard/kpis`: seven-day OEE components, output, defects, and a 14-day daily trend.
- `GET /api/dashboard/downtime`: downtime minutes and event counts by cause for seven days.
- `GET /api/dashboard/defects`: defect rate and sorted Pareto counts/cumulative share for seven days.
- `GET /api/machines`: per-machine production, defects, availability, and health for 24 hours.
- `GET /api/alerts`: explainable anomaly records with machine ID, metric, observed value, threshold, severity, and timestamp.
- `GET /api/alert-thresholds`: current persisted warning/critical thresholds.
- `PUT /api/alert-thresholds/{availability|defect_rate}`: update thresholds with JSON `{"warning_threshold":0.75,"critical_threshold":0.60}` for availability, or `{"warning_threshold":0.04,"critical_threshold":0.08}` for defect rate.

Alerts use simple thresholds over the latest 24-hour aggregate. The API creates additive `alert_thresholds` and `alert_records` tables on startup. A background asyncio processor runs immediately and every 60 seconds, upserts one record per machine/metric/hour, and resolves stale records after two minutes. `GET /api/alerts` returns unresolved records. Thresholds are configurable through the API; availability warning/critical values are lower-is-worse, and defect-rate values are higher-is-worse. The seed intentionally gives CNC-20 a degraded latest-day window. This in-process processor is appropriate for a single local API instance, not a multi-replica production queue.

## Analytics model

`machines`, `defect_causes`, and `downtime_causes` are dimensions. `production_records`, `defect_events`, and `downtime_events` are facts, with foreign keys and time/machine/cause indexes. Hourly records are the grain of production facts.

OEE is calculated as:

```text
Availability = SUM(operating_minutes) / SUM(planned_minutes)
Performance  = SUM(total_count * ideal_cycle_seconds) / SUM(operating_minutes * 60)
Quality      = SUM(good_count) / SUM(total_count)
OEE          = Availability * Performance * Quality
```

All SQL ratios use `NULLIF` and `COALESCE` to avoid division-by-zero and null results. Aggregated components are computed from summed numerators/denominators rather than averaging row-level percentages. OEE is not artificially capped; investigate cycle-time or count calibration if it exceeds 100% on real data.

The backend unit tests use known component values and verify zero denominators and threshold boundaries:

```powershell
Set-Location backend
python -m unittest discover -s tests -v
Set-Location ..
.\scripts\smoke-test.ps1
```

## Apache Superset 3.0

Superset 3.0.3 runs at port 8088. On first start, it creates a separate `superset_meta` database in PostgreSQL, runs metadata migrations, synchronizes roles, creates the configured admin if absent, registers the manufacturing PostgreSQL connection, imports four datasets from SQL views, and provisions charts in the **Manufacturing Analytics** dashboard. Superset's files remain in the existing `superset_home` volume; any old SQLite metadata file is left untouched but is no longer used. The manufacturing host is `postgres` (the Compose service name), not `localhost`.

The provisioned charts are **OEE trend**, **Defect Pareto**, **Downtime by cause**, and **Machine health**. They use `vw_oee_daily`, `vw_defect_pareto`, `vw_downtime_by_cause`, and `vw_machine_health`, which the API creates idempotently. The defect Pareto chart is a table containing sorted counts and cumulative share; the application's own Pareto view is graphical.

To verify the generated dashboard after startup, log in at http://localhost:8088 and open **Dashboards > Manufacturing Analytics**. Startup fails visibly rather than suppressing migration, connection, or chart-provisioning errors.

## Scale and query measurement

The initial seed uses PostgreSQL `generate_series` for 10,000 production rows. To grow the production fact table to two million rows (and insert matching defect/downtime facts), run this from PowerShell:

```powershell
Get-Content -Raw db/generate_to_2m.sql | docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v target_rows=2000000'
```

The SQL script's target is a maximum production-record ID, not a guaranteed final count when IDs contain gaps. It appends production rows and their corresponding defect/downtime facts. Run growth against a disposable/local database and allow for additional storage and index maintenance; actual size and runtime depend on the host and must be measured there. No performance-improvement claim is made.

To measure a query on your own machine, use `EXPLAIN (ANALYZE, BUFFERS)` in `psql` or Superset SQL Lab, record the plan and execution time before and after scale-up, and compare the same query and data volume. `ANALYZE` executes the query, so use care with expensive statements.

## Development notes

## Backups

Create separate PostgreSQL logical backups without printing database credentials:

```powershell
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > .\manufacturing.sql
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" superset_meta' > .\superset-meta.sql
```

Store backups outside the workspace and test restore into a separate database before relying on them. No automated backup schedule is included.

## Production boundary

This is local development infrastructure, not a production deployment. Production needs TLS/reverse-proxy termination, authentication and authorization for the API (including threshold writes), secret-manager injection and rotation, separate least-privilege credentials for the application and Superset, private database networking, managed PostgreSQL backups/PITR, monitoring, and a multi-worker alert queue if the API is replicated. The in-process alert scheduler can run once per API replica, so do not horizontally scale it without moving processing behind a single worker/queue. Redis/Celery were intentionally omitted until that deployment requirement exists.

For local frontend-only development, run `npm ci; npm run dev` in `frontend`; Vite proxies `/api` and `/health` to `localhost:8000`. The FastAPI application can be run with `uvicorn app.main:app --reload` from `backend` after installing `requirements.txt` and setting PG environment variables.