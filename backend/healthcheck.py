"""Live health checks against the real database. Not part of CI.

Run with: python -m healthcheck
Verifies the database is reachable and that every row-model field exists in the
live schema with a compatible type and nullability.
"""

from datetime import datetime
from types import UnionType
from typing import Literal, Union, get_args, get_origin
from uuid import UUID

import psycopg
from psycopg.rows import TupleRow
from pydantic import BaseModel

from config import load_settings
from persistence.rows import ChunkRow, ConversationRow, DocumentRow, MessageRow

ROW_MODELS: dict[str, type[BaseModel]] = {
    "documents": DocumentRow,
    "chunks": ChunkRow,
    "conversations": ConversationRow,
    "messages": MessageRow,
}

PG_TYPES: dict[object, set[str]] = {
    str: {"text"},
    int: {"integer", "bigint"},
    datetime: {"timestamp with time zone"},
    UUID: {"uuid"},
}


def expected_column(annotation: object) -> tuple[set[str], bool]:
    """Map a model field annotation to (acceptable Postgres data types, nullable)."""
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        inner = [arg for arg in get_args(annotation) if arg is not type(None)]
        types, _ = expected_column(inner[0])
        return types, True
    if origin is Literal:
        return {"text"}, False
    if origin is dict:
        return {"jsonb"}, False
    return PG_TYPES[annotation], False


def schema_problems(
    table: str, model: type[BaseModel], columns: dict[str, tuple[str, bool]]
) -> list[str]:
    """Compare a row model's fields against a table's actual columns."""
    problems = []
    for name, field in model.model_fields.items():
        if name not in columns:
            problems.append(f"{table}.{name}: missing column")
            continue
        actual_type, actual_nullable = columns[name]
        wanted_types, wanted_nullable = expected_column(field.annotation)
        if actual_type not in wanted_types:
            problems.append(
                f"{table}.{name}: type is {actual_type},"
                f" model expects {'/'.join(sorted(wanted_types))}"
            )
        if actual_nullable != wanted_nullable:
            problems.append(
                f"{table}.{name}: nullable is {actual_nullable},"
                f" model expects nullable={wanted_nullable}"
            )
    return problems


def table_columns(conn: psycopg.Connection[TupleRow], table: str) -> dict[str, tuple[str, bool]]:
    """Read a table's live columns as {name: (data_type, nullable)}."""
    rows = conn.execute(
        "select column_name, data_type, is_nullable from information_schema.columns"
        " where table_schema = 'public' and table_name = %s",
        (table,),
    ).fetchall()
    return {name: (data_type, is_nullable == "YES") for name, data_type, is_nullable in rows}


def main() -> None:
    problems = []
    with psycopg.connect(load_settings().database_url) as conn:
        for table, model in ROW_MODELS.items():
            columns = table_columns(conn, table)
            if not columns:
                problems.append(f"{table}: table not found")
                continue
            problems.extend(schema_problems(table, model, columns))
    for problem in problems:
        print(problem)
    if problems:
        raise SystemExit(1)
    print("database reachable; schema matches the row models")


if __name__ == "__main__":
    main()
