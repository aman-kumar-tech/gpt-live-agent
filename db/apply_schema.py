"""Apply db/schema.sql against DATABASE_URL. Safe to re-run (all statements are
CREATE ... IF NOT EXISTS / idempotent CHECKs)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _psycopg_dsn(database_url: str) -> str:
    # Accept either the asyncpg-style DSN (postgresql+asyncpg://...) or a
    # plain psycopg-style one; normalize to what psycopg expects.
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


def main() -> int:
    load_dotenv()
    database_url = os.environ.get("CHECKPOINTER_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        print("Set DATABASE_URL (or CHECKPOINTER_DATABASE_URL) before running.", file=sys.stderr)
        return 2

    sql = SCHEMA_PATH.read_text(encoding="utf-8")

    with psycopg.connect(_psycopg_dsn(database_url), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)

    print("Schema applied successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
