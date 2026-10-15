import os
from sqlalchemy.engine import URL

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = URL.create(
	"postgresql+psycopg2",
	username=os.environ["POSTGRES_USER"],
	password=os.environ["POSTGRES_PASSWORD"],
	host="postgres",
	port=5432,
	database="superset_meta",
).render_as_string(hide_password=False)
WTF_CSRF_ENABLED = True