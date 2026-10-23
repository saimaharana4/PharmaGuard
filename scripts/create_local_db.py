import psycopg
from pharmaguard.config import load_settings
from psycopg import sql

settings = load_settings()
with psycopg.connect(
    host=settings.db_host,
    port=settings.db_port,
    user=settings.db_user,
    password=settings.db_password.get_secret_value(),
    dbname="postgres",
    autocommit=True,
    connect_timeout=5,
) as connection:
    exists = connection.execute(
        "SELECT 1 FROM pg_database WHERE datname=%s", (settings.db_name,)
    ).fetchone()
    if not exists:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(settings.db_name)))
print("Local PostgreSQL database is ready")
