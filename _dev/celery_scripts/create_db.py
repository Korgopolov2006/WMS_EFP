from __future__ import annotations

import os

import psycopg


def main() -> int:
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "1")
    dbname = os.getenv("POSTGRES_DB", "wms_autoparts")

    conn = psycopg.connect(f"host={host} port={port} user={user} password={password} dbname=postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (dbname,))
    exists = cur.fetchone() is not None
    if not exists:
        cur.execute(f'CREATE DATABASE "{dbname}" ENCODING "UTF8"')
        print(f"created database: {dbname}")
    else:
        print(f"database already exists: {dbname}")
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

