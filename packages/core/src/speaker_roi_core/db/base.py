"""Declarative base, shared column mixins and the tenant-isolation contract.

Every table in this product falls into exactly one of three categories, and the
category decides which mixin it uses:

``PlatformTable``
    Not owned by any tenant (``core.tenants`` itself, currency reference data,
    platform audit). No ``tenant_id``, no row-level-security policy.

``TenantOwnedTable``
    Owned by exactly one tenant. Carries a non-null ``tenant_id`` FK, a
    row-level-security policy keyed on ``current_setting('app.tenant_id')`` and a
    composite index that *starts* with ``tenant_id`` (plan.md §8.1.1).

``AppendOnlyTable``
    Tenant-owned but never updated or deleted through the application role -
    audit events, AI interactions and published analytical results. Enforced by
    grants in the migration, not by convention.

Policy generation keys off the **presence of a ``tenant_id`` column**, not off a
class attribute. That is deliberate: an attribute can be forgotten, shadowed by
MRO order or copy-pasted wrong, and a tenant table that silently has no policy is
the one defect this product genuinely cannot ship. ``__rls__`` therefore carries
only the *extra* intent - ``"append_only"`` to also revoke UPDATE/DELETE, or
``"exempt"`` to opt a ``tenant_id``-bearing table out loudly and on purpose.
``tests/security/test_rls.py`` walks the metadata against the live database and
fails on any tenant-owned table whose policy is missing.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    DefaultClause,
    ForeignKey,
    Index,
    MetaData,
    String,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# ---------------------------------------------------------------------------
# Naming convention.
#
# Explicit names make migrations reviewable and let `alembic --autogenerate`
# produce stable diffs instead of renaming constraints on every run.
# ---------------------------------------------------------------------------
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

SCHEMAS: tuple[str, ...] = ("auth", "core", "ingestion", "analytics", "ml", "audit")

metadata_obj = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Root declarative base for every mapped class."""

    metadata = metadata_obj

    #: Extra row-level-security intent, on top of the automatic policy that any
    #: table with a ``tenant_id`` column receives.
    #:
    #: ``None``
    #:     Nothing extra. A ``tenant_id`` column still produces a policy.
    #: ``"append_only"``
    #:     Also revoke UPDATE and DELETE from the application role, so history
    #:     cannot be rewritten through the API under any code path.
    #: ``"exempt"``
    #:     Suppress the policy on a table that *has* ``tenant_id``. Requires a
    #:     comment saying why; nothing currently uses it.
    #:
    #: A table whose ``tenant_id`` is *nullable* (``audit.audit_events``,
    #: ``auth.login_attempts``) gets a two-policy form instead of one: reads see
    #: only this tenant's rows unless ``app.platform_scope`` is on, while writes
    #: may still insert a ``NULL``-tenant row. A failed login against an unknown
    #: email genuinely belongs to no tenant, and inventing one would make the
    #: tenant filter lie. The generator picks the form by inspecting nullability.
    __rls__: ClassVar[str | None] = None

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


def uuid_pk() -> Mapped[uuid.UUID]:
    """Primary key column. UUIDv4 generated in the database.

    plan.md §9 requires UUID primary keys internally with human-readable codes
    as the tenant-scoped business key. Generating server-side means a row
    inserted by a migration, a worker or a psql session all look the same.
    """
    return mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """``created_at`` / ``updated_at``, both timezone-aware UTC (plan.md §8.1.1).

    ``created_at`` is deliberately **not** indexed here. A bare ``(created_at)``
    index cannot serve a single query this application issues: row-level security
    puts ``tenant_id = current_setting('app.tenant_id')`` into the predicate of
    every read, so the planner needs ``tenant_id`` as the *leading* column and
    ignores a timestamp-only index. Indexing it in the mixin would therefore buy
    76 indexes that are written on every INSERT and never read - including on the
    partition children of ``hcp_rx_monthly``, ``marketing_activity`` and
    ``audit_events``, which is exactly where bulk-ingest throughput is decided.

    Tables that genuinely order by recency use :func:`recency_index` instead,
    which puts ``tenant_id`` first and ``created_at DESC`` last.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ActorMixin:
    """``created_by`` / ``updated_by``, populated from the request principal.

    Deliberately *not* a hard FK to ``auth.users``: a user row may be
    tombstoned under a deletion request (see docs/PLAN_REVIEW.md F-15) while the
    audit trail that references it must survive.
    """

    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class VersionMixin:
    """Optimistic-concurrency token for editable configuration (plan.md §8.1.1).

    SQLAlchemy increments this on flush and adds it to the UPDATE ... WHERE
    clause, so a stale editor gets ``StaleDataError`` instead of silently
    overwriting a colleague's change.

    The API surfaces that as ``412``, not ``409``. The distinction is the client's recovery
    path: ``409`` says the request can never succeed as written, while ``412`` says the
    caller's copy is out of date and the identical request will succeed after a re-read. A
    stale row version is always the second case, so the frontend re-fetches and re-applies
    rather than showing an unresolvable conflict.
    """

    row_version: Mapped[int] = mapped_column(nullable=False, default=1)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.__table__.c.row_version}


class EffectiveDatedMixin:
    """``effective_from`` / ``effective_to`` for slowly-changing reference data.

    ``effective_to IS NULL`` means "currently in force". The half-open interval
    convention is ``[from, to)`` everywhere, which is what makes the
    ``daterange`` overlap exclusion constraints in the migration correct.

    The range check is *not* attached via ``declared_attr.__table_args__``: any
    subclass declaring its own ``__table_args__`` would silently shadow it, and a
    quietly-missing constraint on effective-dated finance data is precisely the
    defect this product cannot afford. Subclasses call ``effective_range_check()``
    in their own ``__table_args__``; ``tests/unit/test_model_invariants.py``
    asserts every effective-dated table actually has it.
    """

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)


def effective_range_check() -> CheckConstraint:
    """Half-open ``[from, to)`` validity for an :class:`EffectiveDatedMixin` table."""
    return CheckConstraint(
        "effective_to IS NULL OR effective_to > effective_from",
        name="effective_range_valid",
    )


class TenantMixin:
    """Non-null ``tenant_id``, which is by itself the row-level-security opt-in.

    plan.md §5.5: *"Every business record must contain tenant_id"*. Tenant
    context is resolved from the authenticated membership and pushed into the
    transaction as ``app.tenant_id``; it is never read from request data.

    There is deliberately no ``__rls__ = "tenant"`` here. It would sit *after*
    :class:`Base` in the MRO of every model (``class Foo(Base, TenantMixin)``)
    and so would never win the attribute lookup - a policy marker that quietly
    does nothing. Policies are generated from the column instead.

    The column is also **not** indexed on its own. A B-tree answers queries on any
    *leading subset* of its key, so the ``(tenant_id, brand_id, event_date)`` index
    a table already declares serves bare ``WHERE tenant_id = $1`` just as well as a
    single-column index would. Adding one here bought 60 extra indexes that were
    written on every INSERT and never chosen by the planner. What actually matters
    is that every tenant table has *some* tenant-leading index, and that is checked
    directly by ``scripts/devtools/check_schema.py`` rather than assumed.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            PGUUID(as_uuid=True),
            ForeignKey("core.tenants.id", ondelete="RESTRICT"),
            nullable=False,
        )


def tenant_code_unique(table_name: str, *code_columns: str) -> Index:
    """Tenant-scoped uniqueness for a human-readable business code.

    plan.md §9 requires "human-readable codes as tenant-scoped unique business
    keys" - uniqueness is always *within* a tenant, never global, so two
    customers can both have a brand coded ``CARDIOMAX``.
    """
    return Index(
        f"uq_{table_name}_tenant_{'_'.join(code_columns)}",
        "tenant_id",
        *code_columns,
        unique=True,
    )


def tenant_lookup_index(table_name: str, *columns: str, name: str | None = None) -> Index:
    """Composite index whose leading column is ``tenant_id`` (plan.md §8.1.1)."""
    suffix = name or "_".join(columns)
    return Index(f"ix_{table_name}_tenant_{suffix}", "tenant_id", *columns)


def recency_index(table_name: str, *columns: str, name: str | None = None) -> Index:
    """``(tenant_id, *columns, created_at DESC)`` for newest-first feeds.

    Use this wherever the UI shows "most recent first" - notification bells,
    activity feeds, job lists, audit trails. The shape matters in all three
    positions: ``tenant_id`` leads so the row-level-security predicate is an index
    seek rather than a filter, the middle columns narrow to one recipient or one
    entity, and ``created_at DESC`` lets Postgres walk the index backwards and
    stop at ``LIMIT`` instead of sorting the whole partition.
    """
    suffix = name or ("_".join([*columns, "recent"]) if columns else "recent")
    return Index(
        f"ix_{table_name}_tenant_{suffix}",
        "tenant_id",
        *columns,
        desc("created_at"),
    )


#: Reusable column type for ISO-4217 currency codes. plan.md §9 is explicit that
#: money is stored as (numeric amount, ISO code) and never as a float.
CurrencyCode = String(3)


# ---------------------------------------------------------------------------
# Keeping Python defaults and SQL defaults in agreement
# ---------------------------------------------------------------------------


def _sql_default_literal(column: Any) -> str | None:
    """The SQL literal equivalent to a column's Python-side default, if any.

    Returns ``None`` for defaults that only make sense in Python - ``uuid4``,
    ``datetime.now``, anything that reads other columns - and for columns whose
    default is a sequence or a server-side function already.
    """
    default = column.default
    arg = getattr(default, "arg", None)

    if getattr(default, "is_callable", False):
        # `default=dict` / `default=list` are the JSON "empty container" idiom.
        # Every other callable computes something Postgres cannot reproduce.
        unwrapped = getattr(arg, "__wrapped__", arg)
        if unwrapped is dict:
            return "'{}'::jsonb"
        if unwrapped is list:
            return "'[]'::jsonb"
        return None

    if isinstance(arg, bool):
        return "true" if arg else "false"
    if isinstance(arg, Enum):
        return _quote(str(arg.value))
    if isinstance(arg, str):
        return _quote(arg)
    if isinstance(arg, int | float | Decimal):
        return str(arg)
    if isinstance(arg, dict | list):
        return f"{_quote(json.dumps(arg, separators=(',', ':')))}::jsonb"
    return None


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def sync_server_defaults(metadata: MetaData) -> list[str]:
    """Give every scalar Python default a matching ``DEFAULT`` in the database.

    SQLAlchemy's ``default=`` is applied by the ORM at flush time, which means a
    column declared ``NOT NULL, default=0`` is satisfied only for writers that go
    through a mapped class. Everything else produces a ``NotNullViolation``: a
    migration backfill, a ``COPY``-based bulk ingest, the synthetic data loader,
    ``psql`` during an incident. Thirty-five such columns existed here, including
    the ``row_version`` that optimistic locking depends on, so the failure mode was
    "the fast ingest path cannot write the rows the slow one can".

    Mirroring the value into ``server_default`` fixes all of them at once and keeps
    them fixed: a column added later inherits the behaviour without anyone
    remembering to. Doing it here rather than by editing ~170 declarations also
    means the two defaults cannot drift apart, because there is only one of them.

    Called from ``speaker_roi_core.models`` once every model is imported, so the
    generated migration and the live database both carry the clauses.

    Returns the ``schema.table.column`` names it touched, which
    ``scripts/devtools/check_schema.py`` prints so the count is visible rather
    than magic.
    """
    touched: list[str] = []
    for table in metadata.tables.values():
        for column in table.columns:
            if column.server_default is not None or column.default is None:
                continue
            literal = _sql_default_literal(column)
            if literal is None:
                continue
            column.server_default = DefaultClause(text(literal))
            touched.append(f"{table.fullname}.{column.name}")
    return sorted(touched)


def declared_rls() -> dict[str, str | None]:
    """``{table.fullname: __rls__}`` for every mapped class.

    Read from the mappers rather than from the tables because ``__rls__`` is a
    class attribute and inherits through the mixins, which is the whole point of
    declaring it on ``AppendOnlyTable`` once instead of on twelve models. The
    migration generator, ``scripts/devtools/probe_rls.py`` and
    ``tests/security/test_rls.py`` all need this mapping, and three copies of it
    would be three chances for the live database and the test's expectations to
    disagree about what was asked for.
    """
    return {
        mapper.class_.__table__.fullname: getattr(mapper.class_, "__rls__", None)
        for mapper in Base.registry.mappers
    }
