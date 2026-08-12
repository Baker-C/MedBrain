"""Document reads: the parent rows a retrieved chunk set needs, fetched in one query."""

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow

from persistence.db import fetch_rows
from persistence.rows import DocumentRow

# Selected from the row model itself, so a query can never drift from what
# DocumentRow expects to validate.
DOCUMENT_COLUMNS = sql.SQL(", ").join(sql.Identifier(name) for name in DocumentRow.model_fields)

DOCUMENTS_BY_ID = sql.SQL("select {columns} from documents where id = any(%s)").format(
    columns=DOCUMENT_COLUMNS
)


def fetch_documents(conn: psycopg.Connection[TupleRow], ids: set[str]) -> dict[str, DocumentRow]:
    """The named documents, keyed by id, in one round trip.

    `any(%s)` takes the ids as a single list parameter, so the number of documents
    asked for never changes the shape of the query.
    """
    rows = fetch_rows(conn, DOCUMENTS_BY_ID, (list(ids),), DocumentRow)
    return {row.id: row for row in rows}
