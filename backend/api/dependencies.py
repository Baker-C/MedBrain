"""Per-request dependencies."""

from collections.abc import Iterator
from typing import cast

import psycopg
from fastapi import Request
from psycopg.rows import TupleRow

from clients import AppClients


def app_clients(request: Request) -> AppClients:
    """The one place `app.state`'s untyped attributes are narrowed, so no `Any` reaches
    a caller's signature."""
    return cast(AppClients, request.app.state.clients)


def db_connection(request: Request) -> Iterator[psycopg.Connection[TupleRow]]:
    """One connection per request, opened and closed with the request.

    Deliberately no pool: at demo scale the connection churn is small, and Supabase's
    own pooler sits in front of Postgres and absorbs it.
    """
    with psycopg.connect(app_clients(request).settings.database_url) as conn:
        yield conn
