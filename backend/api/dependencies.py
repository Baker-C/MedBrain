"""Per-request dependencies."""

from collections.abc import Iterator

import psycopg
from fastapi import Request
from psycopg.rows import TupleRow

from api.state import app_clients


def db_connection(request: Request) -> Iterator[psycopg.Connection[TupleRow]]:
    """One connection per request, opened and closed with the request.

    Deliberately no pool: at demo scale the connection churn is small, and Supabase's
    own pooler sits in front of Postgres and absorbs it.
    """
    with psycopg.connect(app_clients(request).settings.database_url) as conn:
        yield conn
