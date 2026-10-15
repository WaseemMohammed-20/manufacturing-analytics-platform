import json
import logging
import os
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.engine import URL

from superset import app, db
from superset.connectors.sqla.models import SqlaTable, SqlMetric
from superset.models.core import Database
from superset.models.dashboard import Dashboard
from superset.models.slice import Slice

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def ensure_admin():
    security = app.appbuilder.sm
    username = os.environ["SUPERSET_ADMIN_USERNAME"]
    user = security.find_user(username=username)
    if user:
        logger.info("Superset administrator %s already exists; preserving its password", username)
        return user
    role = security.find_role("Admin")
    if role is None:
        raise RuntimeError("Superset Admin role is missing after superset init")
    user = security.add_user(
        username=username,
        first_name="Analytics",
        last_name="Admin",
        email=os.environ["SUPERSET_ADMIN_EMAIL"],
        role=role,
        password=os.environ["SUPERSET_ADMIN_PASSWORD"],
    )
    if user is None:
        raise RuntimeError("Superset administrator creation failed")
    return user


def ensure_database():
    uri = URL.create(
        "postgresql+psycopg2",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host="postgres",
        port=5432,
        database=os.environ.get("POSTGRES_DB", "manufacturing"),
    ).render_as_string(hide_password=False)
    database = db.session.query(Database).filter_by(database_name="Manufacturing").one_or_none()
    if database is None:
        database = Database(
            database_name="Manufacturing",
            verbose_name="Manufacturing",
            expose_in_sqllab=True,
            allow_run_async=False,
            allow_file_upload=False,
            allow_ctas=False,
            allow_cvas=False,
            allow_dml=False,
        )
        database.set_sqlalchemy_uri(uri)
        db.session.add(database)
    else:
        database.set_sqlalchemy_uri(uri)
    db.session.commit()
    with database.get_sqla_engine_with_context() as engine:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
    return database


CHARTS = [
    ("OEE trend", "vw_oee_daily", "echarts_timeseries_line", "oee", "AVG(oee)", "avg"),
    ("Defect Pareto", "vw_defect_pareto", "echarts_bar", "defect_count_sum", "SUM(defect_count)", "sum"),
    ("Downtime by cause", "vw_downtime_by_cause", "echarts_bar", "downtime_minutes_sum", "SUM(downtime_minutes)", "sum"),
    ("Machine health", "vw_machine_health", "table", None, None, None),
]


def ensure_charts(database, admin):
    charts = []
    for title, view_name, viz_type, metric_name, metric_expression, metric_type in CHARTS:
        dataset = db.session.query(SqlaTable).filter_by(
            database_id=database.id, schema="public", table_name=view_name
        ).one_or_none()
        if dataset is None:
            dataset = SqlaTable(
                table_name=view_name,
                schema="public",
                database_id=database.id,
            )
            db.session.add(dataset)
            db.session.commit()
        dataset.fetch_metadata()
        if metric_name:
            metric = next((item for item in dataset.metrics if item.metric_name == metric_name), None)
            if metric is None:
                metric = SqlMetric(metric_name=metric_name, table=dataset)
                dataset.metrics.append(metric)
            metric.expression = metric_expression
            metric.metric_type = metric_type
            metric.verbose_name = "Downtime minutes" if metric_name == "downtime_minutes_sum" else metric_name
        db.session.commit()

        chart = db.session.query(Slice).filter_by(slice_name=title).one_or_none()
        columns = [column.column_name for column in dataset.columns]
        params = {
            "datasource": f"{dataset.id}__table",
            "viz_type": viz_type,
            "time_range": "No filter",
            "granularity_sqla": "day" if view_name == "vw_oee_daily" else None,
            "time_grain_sqla": "P1D" if view_name == "vw_oee_daily" else None,
            "metrics": [metric_name] if metric_name else [],
            "groupby": ["cause"] if view_name in {"vw_defect_pareto", "vw_downtime_by_cause"} else [],
            "query_mode": "aggregate" if metric_name else "raw",
            "all_columns": columns if not metric_name else [],
            "row_limit": 1000,
            "show_legend": True,
            "rich_tooltip": True,
            "orientation": "horizontal",
            "order_desc": view_name in {"vw_defect_pareto", "vw_downtime_by_cause"},
        }
        if chart is None:
            chart = Slice(slice_name=title, owners=[admin])
        chart.datasource_id = dataset.id
        chart.datasource_type = "table"
        chart.datasource_name = f"public.{view_name}"
        chart.viz_type = viz_type
        chart.params = json.dumps(params)
        chart.owners = [admin]
        if chart.id is None:
            db.session.add(chart)
        db.session.commit()
        charts.append(chart)
    return charts


def ensure_dashboard(charts, admin):
    dashboard = db.session.query(Dashboard).filter_by(slug="manufacturing-analytics").one_or_none()
    if dashboard is None:
        dashboard = Dashboard(dashboard_title="Manufacturing Analytics", slug="manufacturing-analytics")
    grid_id = "GRID_ID"
    position = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": [grid_id], "meta": {}},
        grid_id: {"type": "GRID", "id": grid_id, "children": [], "meta": {}},
    }
    for index, chart in enumerate(charts):
        row_id = f"ROW-{index // 2 + 1}"
        chart_key = f"CHART-{chart.id}"
        if row_id not in position:
            position[grid_id]["children"].append(row_id)
            position[row_id] = {"type": "ROW", "id": row_id, "children": [], "meta": {}}
        position[row_id]["children"].append(chart_key)
        position[chart_key] = {
            "type": "CHART", "id": chart_key, "children": [],
            "meta": {
                "chartId": chart.id,
                "width": 6,
                "height": 50,
                "sliceName": chart.slice_name,
                "uuid": str(uuid5(NAMESPACE_URL, f"manufacturing-chart-{chart.id}")),
            },
        }
    dashboard.dashboard_title = "Manufacturing Analytics"
    dashboard.position_json = json.dumps(position)
    dashboard.json_metadata = "{}"
    dashboard.published = True
    dashboard.slices = charts
    dashboard.owners = [admin]
    if dashboard.id is None:
        db.session.add(dashboard)
    db.session.commit()
    logger.info("Superset dashboard provisioned: %s", dashboard.url)


with app.app_context():
    administrator = ensure_admin()
    manufacturing_database = ensure_database()
    chart_objects = ensure_charts(manufacturing_database, administrator)
    ensure_dashboard(chart_objects, administrator)