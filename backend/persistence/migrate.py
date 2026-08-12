"""Versioned SQL migrations, applied in filename order against DATABASE_URL.

Run with: python -m persistence.migrate
"""

from pathlib import Path

import psycopg
from psycopg.rows import TupleRow

from config import load_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def pending_migrations(available: list[str], applied: set[str]) -> list[str]:
    """Return the migration filenames not yet applied, in filename order."""
    missing = applied - set(available)
    if missing:
        raise ValueError(f"applied migrations missing from {MIGRATIONS_DIR}: {sorted(missing)}")
    return sorted(set(available) - applied)


def applied_migrations(conn: psycopg.Connection[TupleRow]) -> set[str]:
    """Read the applied migration filenames, creating the tracking table on first run."""
    conn.execute(
        "create table if not exists schema_migrations ("
        " filename text primary key,"
        " applied_at timestamptz not null default now())"
    )
    rows = conn.execute("select filename from schema_migrations").fetchall()
    return {row[0] for row in rows}


def apply_migration(conn: psycopg.Connection[TupleRow], filename: str) -> None:
    """Run one migration file and record it, in one transaction."""
    sql = (MIGRATIONS_DIR / filename).read_text(encoding="utf-8")
    with conn.transaction():
        conn.execute(sql)
        conn.execute("insert into schema_migrations (filename) values (%s)", (filename,))


def main() -> None:
    available = [path.name for path in MIGRATIONS_DIR.glob("*.sql")]
    with psycopg.connect(load_settings().database_url, autocommit=True) as conn:
        for filename in pending_migrations(available, applied_migrations(conn)):
            apply_migration(conn, filename)
            print(f"applied {filename}")
    print("schema is up to date")


if __name__ == "__main__":
    main()
