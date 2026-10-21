"""Opt-in database isolation shared by the connector and forward-paper suites."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text

from tradingbot.db import models  # noqa: F401 — register every mapped table
from tradingbot.db.base import Base
from tradingbot.db.session import get_engine

LOCK_TIMEOUT = "60s"


@pytest.fixture(scope="session")
def paper_test_database():
    """Keep every connection, including seed()/SessionLocal(), off public rows.

    Adjust the cached engine itself so already-imported get_engine aliases and
    session factories share the same schema. ORM schema translation preserves
    foreign keys; the connection search_path also isolates raw/unqualified SQL.
    No public fallback is allowed. Production runs in separate processes and
    never sees this process-local engine configuration.

    Once requested, the redirect lasts for the rest of the pytest session,
    including later directories. A test that needs real public rows, its own
    schema or TimescaleDB functions must use a private ``create_engine(url)``.
    """
    engine = get_engine()
    previous_map = engine.get_execution_options().get("schema_translate_map")
    schema = "test_paper_" + uuid4().hex
    admin = create_engine(engine.url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    def search_path(dbapi_connection, _record, _proxy):
        previous = dbapi_connection.autocommit
        try:
            dbapi_connection.autocommit = True
            with dbapi_connection.cursor() as cursor:
                cursor.execute(f'SET SESSION search_path TO "{schema}"')
                # A leaked fixture transaction must fail later tests, not hang the run.
                cursor.execute(f"SET SESSION lock_timeout = '{LOCK_TIMEOUT}'")
        finally:
            dbapi_connection.autocommit = previous

    engine.dispose()
    event.listen(engine, "checkout", search_path)
    engine.update_execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(engine)
        yield SimpleNamespace(engine=engine, admin=admin, schema=schema)
    finally:
        engine.dispose()
        event.remove(engine, "checkout", search_path)
        engine.update_execution_options(schema_translate_map=previous_map)
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
