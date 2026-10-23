"""Initialize local PostgreSQL using a password on stdin, never a password file."""

import subprocess
from pathlib import Path

from pharmaguard.config import load_settings

root = Path(__file__).resolve().parents[1]
settings = load_settings()
subprocess.run(
    [
        str(root / ".tools/postgres/pgsql/bin/initdb.exe"),
        "-D",
        str(root / ".data/postgres"),
        "-U",
        settings.db_user,
        "--encoding=UTF8",
        "--locale=C",
        "--auth=scram-sha-256",
        "--pwfile=-",
    ],
    input=settings.db_password.get_secret_value() + "\n",
    text=True,
    check=True,
)
