"""The shared reader every persistence adapter goes through.

Validation happens at the database boundary: a row that no longer matches its model
fails here rather than somewhere downstream. Mirrors retrieval's chunk reader, which
stays separate because it is the retrieval package's own boundary.
"""

from typing import TypeVar

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow, dict_row
from pydantic import BaseModel

R = TypeVar("R", bound=BaseModel)


def fetch_rows(
    conn: psycopg.Connection[TupleRow],
    query: sql.Composed,
    params: tuple[object, ...],
    model: type[R],
) -> list[R]:
    """Run a query and validate every row into the given model.

    The cursor takes its own `dict_row` factory so validation is by column name,
    independent of how the connection was opened.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return [model.model_validate(row) for row in cursor]
