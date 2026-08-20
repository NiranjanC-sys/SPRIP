"""Generate the initial Alembic revision as frozen, literal SQL.

Why generate instead of hand-writing, and why freeze instead of deriving?

Hand-writing 76 tables of DDL is a transcription-error factory, and the errors it
produces are the quiet kind - a missing ``NOT NULL``, an index on the wrong
column order. So the DDL is generated from ``Base.metadata``.

But a migration that *calls* ``metadata.create_all()`` at runtime is worse than
either. Revision 0001 would then mean "whatever the models say today", so a
database migrated from scratch would get today's schema at revision 0001 and then
try to apply revision 0002's ``ALTER``s on top of columns that already exist.
Generating once and committing the literal output gives both: no transcription
errors, and a revision whose meaning is fixed the moment it is committed.

Run it once. After that the file is an ordinary reviewed migration and this
script is only useful for regenerating from scratch during development.

    python scripts/devtools/gen_initial_migration.py

``tests/integration/test_migrations.py`` is what keeps the committed output
honest: it runs ``alembic upgrade head`` against a real database and asserts that
autogenerate then finds nothing to do.
"""

from __future__ import annotations

import pathlib
import sys

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import speaker_roi_core.models  # noqa: F401  - registers every table
from speaker_roi_core.db import ddl
from speaker_roi_core.db.base import SCHEMAS, Base, declared_rls
from speaker_roi_core.db.types import ENUM_SCHEMA
from speaker_roi_core.enums import PG_ENUMS

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "migrations" / "versions" / "20260101_0000_0001_initial_schema.py"

REVISION = "0001_initial_schema"

DIALECT = postgresql.dialect()

#: Trusted extensions, so ``app_migrator`` can install them without superuser.
EXTENSIONS = (
    # gen_random_uuid() for primary keys, digest() for the erasure crypto-shred.
    "pgcrypto",
    # Equality operators for GiST, which is what makes the effective-dated
    # ``EXCLUDE ... USING gist (tenant_id WITH =, ... daterange WITH &&)``
    # constraints possible at all.
    "btree_gist",
    # Trigram indexes for HCP and event name search in the pickers.
    "pg_trgm",
)

#: Imported, not redeclared. Two copies of this list drift, and the drift is silent until
#: an insert lands in a year with no partition.
PARTITIONED = ddl.PARTITIONED_TABLES


def _create_type(enum_cls: type) -> str:
    name = _type_name(enum_cls)
    values = ",\n    ".join(f"'{member.value}'" for member in enum_cls)
    return f"CREATE TYPE {ENUM_SCHEMA}.{name} AS ENUM (\n    {values}\n);"


def _type_name(enum_cls: type) -> str:
    from speaker_roi_core.db.types import _type_name as impl

    return impl(enum_cls)  # type: ignore[arg-type]


def _compile(element: object) -> str:
    """Compile one DDL element to text, with per-line trailing whitespace removed.

    SQLAlchemy renders ``CREATE TABLE`` with a space after each column's trailing comma. The
    SQL is unaffected, but the text is embedded in a committed Python file as a triple-quoted
    literal, so those become 3000 trailing-whitespace lint findings in a file nobody edits by
    hand. Normalising here keeps the generated revision lint-clean without excluding
    ``migrations/`` from the linter - which would also stop it checking ``env.py``.
    """
    raw = str(element.compile(dialect=DIALECT))  # type: ignore[attr-defined]
    return "\n".join(line.rstrip() for line in raw.splitlines()).strip()


def build_upgrade() -> list[str]:
    statements: list[str] = []

    statements.append("-- Schemas")
    statements.extend(f"CREATE SCHEMA IF NOT EXISTS {schema};" for schema in SCHEMAS)

    statements.append("-- Extensions (all trusted; no superuser required)")
    statements.extend(f"CREATE EXTENSION IF NOT EXISTS {ext};" for ext in EXTENSIONS)

    statements.append("-- Roles")
    statements.extend(ddl.create_roles_sql())

    statements.append("-- Controlled vocabularies as native enum types")
    statements.extend(_create_type(enum_cls) for enum_cls in PG_ENUMS)

    statements.append("-- Tables")
    for table in Base.metadata.sorted_tables:
        statements.append(_compile(CreateTable(table)) + ";")

    statements.append("-- Range partitions")
    for parent in PARTITIONED:
        statements.extend(ddl.partition_children_sql(parent))

    statements.append("-- Indexes")
    for table in Base.metadata.sorted_tables:
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            statements.append(_compile(CreateIndex(index)) + ";")

    plan = ddl.security_plan(Base.metadata, declared_rls())
    stray = ddl.unprotected_tables(plan)
    if stray:
        raise SystemExit(
            "Refusing to generate: these tables have no tenant_id and are not on "
            "the PLATFORM_TABLES allowlist in speaker_roi_core.db.ddl. Decide "
            "whether each is genuinely platform data, then list it there:\n  " + "\n  ".join(stray)
        )

    statements.append("-- Row-level security")
    for sec in plan:
        statements.extend(ddl.enable_rls_sql(sec))

    statements.append("-- Privileges")
    statements.extend(ddl.revoke_public_sql(SCHEMAS))
    statements.extend(ddl.grants_sql(plan, SCHEMAS))
    # Safe here: Alembic creates its version table before it runs the first revision.
    statements.extend(ddl.migration_visibility_sql())
    statements.extend(ddl.guc_defaults_sql())

    return statements


def build_downgrade() -> list[str]:
    """Drop the schemas. Enum types live in ``core`` and go with it.

    A downgrade of the initial revision is a full teardown by definition. It is
    written out rather than left as ``pass`` so that a test database can be
    recycled without a manual ``DROP SCHEMA``.
    """
    return [f"DROP SCHEMA IF EXISTS {schema} CASCADE;" for schema in reversed(SCHEMAS)]


def render(upgrade: list[str], downgrade: list[str]) -> str:
    return TEMPLATE.format(
        revision=REVISION,
        upgrade=_statement_tuple(upgrade),
        downgrade=_statement_tuple(downgrade),
    )


def _statement_tuple(statements: list[str]) -> str:
    """Render statements as tuple entries: one SQL string, not four lines of noise."""
    chunks: list[str] = []
    for stmt in statements:
        if stmt.startswith("--"):
            chunks.append(f"    # --- {stmt.lstrip('- ')} " + "-" * max(4, 66 - len(stmt)))
            continue
        body = stmt.replace("\\", "\\\\").replace('"""', r"\"\"\"")
        if "\n" in body:
            chunks.append('    """\\\n' + body + '\n    """,')
        else:
            chunks.append(f'    "{body}",')
    return "\n".join(chunks)


TEMPLATE = '''"""Initial schema.

Creates the six schemas, the native enum types, all tables and indexes, the range
partitions, and the row-level-security policies and grants that make the
application role tenant-scoped.

This revision is generated from ``Base.metadata`` by
``scripts/devtools/gen_initial_migration.py`` and then frozen. Do not "refresh"
it - later schema changes belong in later revisions, or a database built from
scratch will silently disagree with one built incrementally.

Revision ID: {revision}
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "{revision}"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPGRADE_SQL: tuple[str, ...] = (
{upgrade}
)

DOWNGRADE_SQL: tuple[str, ...] = (
{downgrade}
)


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
'''


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = render(build_upgrade(), build_downgrade())
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
