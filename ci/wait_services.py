import time

import httpx
import psycopg
from pharmaguard.config import Settings

settings = Settings()
for attempt in range(20):
    try:
        with psycopg.connect(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password.get_secret_value(),
            connect_timeout=2,
        ):
            pass
        httpx.get(f"{settings.qdrant_url}/readyz", timeout=2).raise_for_status()
        break
    except (psycopg.OperationalError, httpx.HTTPError):
        if attempt == 19:
            raise SystemExit("PostgreSQL/Qdrant did not become available") from None
        time.sleep(2)
