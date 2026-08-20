"""Alembic environment.

Three decisions here are worth knowing before editing this file.

**The URL comes from the environment, never from ``alembic.ini``.** That file is
committed; a URL in it eventually carries a password. ``MIGRATION_DATABASE_URL``
is preferred because migrations should connect as ``app_migrator`` (the DDL
owner), not as the application role - if they share a role, the application role
owns the tables and silently bypasses row-level security.

**Migrations run synchronously.** The application is async end to end, but
Alembic's async support buys nothing for a process that runs one statement at a
time and exits. The URL is rewritten from whatever driver the app uses to
``psycopg`` so the same ``DATABASE_URL`` works for both.

**Autogenerate ignores the physical layer.** Partition children, RLS policies,
grants and the enum types themselves are managed by hand-written DDL in the
revisions. Left unfiltered, autogenerate proposes dropping every partition child
on every run, which trains reviewers to skim migrations - the opposite of what
migrations are for.
"""

from __future__ import annotations

import os
import re
import sys
from logging.config import fileConfig
from pathlib import Path
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import speaker_roi_core.models  # noqa: E402,F401  - registers every table on Base.metadata
from speaker_roi_core.db.base import SCHEMAS, Base  # noqa: E402
from speaker_roi_core.db.ddl import PARTITION_FIRST_YEAR, PARTITION_LAST_YEAR  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

#: Schemas Alembic is allowed to look at. Anything else in the database -
#: extensions' own objects, a colleague's scratch schema - is none of its
#: business, and reflecting it produces spurious drops.
MANAGED_SCHEMAS = frozenset(SCHEMAS)

#: Where the ``alembic_version`` bookkeeping table lives. In ``public`` it would
#: be the one thing standing between a ``DROP SCHEMA public CASCADE`` and an
#: unrecoverable migration state.
VERSION_TABLE_SCHEMA = "public"

_PARTITION_CHILD = re.compile(
    rf"_(y(?:{PARTITION_FIRST_YEAR}|{PARTITION_LAST_YEAR}|\d{{4}})|default)$"
)


def _database_url() -> str:
    """Resolve the URL and normalise it onto the synchronous psycopg driver."""
    url = (
        os.environ.get("MIGRATION_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or config.get_main_option("sqlalchemy.url", "")
    )
    if not url:
        raise RuntimeError(
            "No database URL. Set MIGRATION_DATABASE_URL (preferred - the "
            "app_migrator role) or DATABASE_URL before running Alembic. "
            "For the embedded development server: "
            "python scripts/devtools/pg.py dsn"
        )
    for async_driver in ("+asyncpg", "+psycopg_async"):
        url = url.replace(async_driver, "+psycopg")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Keep autogenerate to the logical schema this repository owns."""
    schema = getattr(obj, "schema", None)

    if type_ == "table":
        if schema not in MANAGED_SCHEMAS:
            return False
        # Partition children are created by hand-written DDL and are invisible to
        # the model layer by design.
        return not (reflected and name and _PARTITION_CHILD.search(name))

    if type_ in {"index", "unique_constraint", "foreign_key_constraint"}:
        parent = getattr(obj, "table", None)
        parent_name = getattr(parent, "name", "") or ""
        if reflected and _PARTITION_CHILD.search(parent_name):
            return False

    return schema in MANAGED_SCHEMAS or schema is None


def include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
    """Restrict reflection to the managed schemas."""
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    return True


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
        include_name=include_name,
        version_table="alembic_version",
        version_table_schema=VERSION_TABLE_SCHEMA,
        compare_type=True,
        compare_server_default=True,
        # Renders enums as their bare name rather than re-declaring the type, which
        # matters because every enum is created once, up front, with create_type=False.
        render_as_batch=False,
        transaction_per_migration=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting. Used to review a release."""
    _configure(url=_database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and apply."""
    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
