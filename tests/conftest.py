"""Fixtures for tests that need a real PostgreSQL.

Everything here runs against ``speaker_roi_test``, migrated to head once per session by
Alembic rather than by ``Base.metadata.create_all``. That distinction is the entire point of
these tests: ``create_all`` builds the tables and *nothing else* - no roles, no policies, no
grants, no partitions - so a suite built on it verifies the models and silently skips the
security layer, which is the only part of the schema that cannot be inferred from reading the
model files. It would also never catch a migration that fails to apply, which is the failure
that takes production down rather than a test.

Tests skip rather than fail when the database is unreachable, so ``pytest`` on a laptop with
nothing running still exercises the pure-Python suite. ``scripts/verify`` starts the cluster
first, so a skip in CI is a configuration error and is reported as one there.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

ROOT = Path(__file__).resolve().parents[1]

#: Deliberately not derived from ``Settings``. These tests must be able to connect as three
#: *different* roles - the migrator to build the schema, the application role to be
#: constrained by it, and the reader - and ``Settings`` models one application identity.
DEFAULT_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DEFAULT_PORT = os.environ.get("DB_PORT", "54329")
TEST_DB = os.environ.get("TEST_DB_NAME", "speaker_roi_test")

ROLE_PASSWORDS = {
    "app_migrator": os.environ.get("DB_MIGRATION_PASSWORD", "app_migrator_pw"),
    "app_rw": os.environ.get("DB_PASSWORD", "app_rw_pw"),
    "app_ro": os.environ.get("DB_READONLY_PASSWORD", "app_ro_pw"),
}


def url_for(role: str, *, driver: str = "asyncpg", database: str = TEST_DB) -> str:
    password = ROLE_PASSWORDS[role]
    return f"postgresql+{driver}://{role}:{password}@{DEFAULT_HOST}:{DEFAULT_PORT}/{database}"


def _reachable() -> bool:
    import socket

    with socket.socket() as probe:
        probe.settimeout(1.0)
        return probe.connect_ex((DEFAULT_HOST, int(DEFAULT_PORT))) == 0


@pytest.fixture(scope="session")
def database_available() -> bool:
    if not _reachable():
        pytest.skip(
            f"no PostgreSQL on {DEFAULT_HOST}:{DEFAULT_PORT}. "
            "Start one with: python scripts/devtools/pg.py start"
        )
    return True


@pytest.fixture(scope="session")
def migrated_database(database_available: bool) -> Iterator[str]:
    """Bring ``speaker_roi_test`` to head, once, for the whole session.

    Uses the synchronous ``psycopg`` driver because Alembic's runner is synchronous, and
    mixing an async driver into it means an event loop inside a fixture inside pytest-asyncio
    - three loop owners and no clear winner.
    """
    from alembic import command
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    migrator_url = url_for("app_migrator", driver="psycopg")
    # ``env.py`` reads the environment, not this object, so both are set.
    os.environ["MIGRATION_DATABASE_URL"] = migrator_url
    config.set_main_option("sqlalchemy.url", migrator_url)

    command.upgrade(config, "head")
    yield migrator_url
    # No downgrade. The database is disposable and a teardown that drops the schema turns
    # one failing test into a suite that cannot run twice.


@pytest_asyncio.fixture
async def app_engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    """An engine connected as ``app_rw`` - the role the API uses, subject to RLS.

    ``NullPool`` so each test gets a genuinely fresh connection. With a pool, a transaction-
    local GUC from a previous test would be gone but a *session-level* one would not, and the
    difference between those two is exactly what several of these tests assert.
    """
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(
        url_for("app_rw"),
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def migrator_engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    """An engine connected as the schema owner, which bypasses RLS by ownership.

    Needed to *plant* rows for more than one tenant. A test that can only write through
    ``app_rw`` cannot construct the situation it wants to prove is unreachable - there would
    be no other tenant's row for the isolation check to fail to see.
    """
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(
        url_for("app_migrator"),
        poolclass=NullPool,
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def app_session(app_engine: AsyncEngine) -> AsyncIterator[_AsyncSession]:
    factory = async_sessionmaker(bind=app_engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
