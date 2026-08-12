"""How both search legs read chunks: the columns they select, and the reader that
validates every row at the database boundary."""

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow, dict_row

from persistence.rows import ChunkRow

# Selected from the row model itself, so a query can never drift from what
# ChunkRow expects to validate.
CHUNK_COLUMNS = sql.SQL(", ").join(sql.Identifier(name) for name in ChunkRow.model_fields)


def fetch_chunks(
    conn: psycopg.Connection[TupleRow], query: sql.Composed, params: tuple[object, ...]
) -> list[ChunkRow]:
    """Run a chunk query and validate every row into the typed model.

    The cursor takes its own `dict_row` factory so validation is by column name,
    independent of how the connection was opened.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return [ChunkRow.model_validate(row) for row in cursor]
