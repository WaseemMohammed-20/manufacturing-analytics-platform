#!/bin/sh
set -eu

if [ "${#SUPERSET_SECRET_KEY}" -lt 32 ] || [ "${#SUPERSET_ADMIN_PASSWORD}" -lt 16 ]; then
    echo "SUPERSET_SECRET_KEY must be at least 32 characters and SUPERSET_ADMIN_PASSWORD at least 16 characters" >&2
    exit 1
fi

python - <<'PY'
import os
import psycopg2

connection = psycopg2.connect(
    dbname="postgres",
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
    host="postgres",
)
connection.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
with connection, connection.cursor() as cursor:
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", ("superset_meta",))
    if cursor.fetchone() is None:
        cursor.execute('CREATE DATABASE "superset_meta"')
connection.close()
PY

superset db upgrade
superset init
python /app/bootstrap_assets.py
exec /usr/bin/run-server.sh