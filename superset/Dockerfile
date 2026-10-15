FROM apache/superset:3.0.3
USER root
RUN pip install --no-cache-dir psycopg2-binary==2.9.9
COPY bootstrap.sh /app/bootstrap.sh
COPY bootstrap_assets.py /app/bootstrap_assets.py
COPY manage_admin.py /app/manage_admin.py
RUN chmod 0755 /app/bootstrap.sh
USER superset