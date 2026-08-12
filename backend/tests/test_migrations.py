"""Proves migration ordering, skipping, and drift detection without a database."""

import pytest

from persistence.migrate import MIGRATIONS_DIR, pending_migrations


def test_orders_by_filename() -> None:
    available = ["0002_add_column.sql", "0001_initial_schema.sql"]
    assert pending_migrations(available, set()) == [
        "0001_initial_schema.sql",
        "0002_add_column.sql",
    ]


def test_skips_already_applied() -> None:
    available = ["0001_initial_schema.sql", "0002_add_column.sql"]
    assert pending_migrations(available, {"0001_initial_schema.sql"}) == ["0002_add_column.sql"]


def test_rejects_applied_migration_missing_from_disk() -> None:
    with pytest.raises(ValueError, match="0001_gone.sql"):
        pending_migrations([], {"0001_gone.sql"})


def test_shipped_migrations_have_unique_ordered_prefixes() -> None:
    names = [path.name for path in MIGRATIONS_DIR.glob("*.sql")]
    prefixes = [name.split("_", 1)[0] for name in names]
    assert names, "migrations directory must not be empty"
    assert all(len(prefix) == 4 and prefix.isdigit() for prefix in prefixes)
    assert len(set(prefixes)) == len(prefixes)
