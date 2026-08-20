"""Security and physical-layout DDL: roles, grants, RLS policies, partitions.

This module is the single definition of what "tenant isolation" means in SQL. It
produces statement *text*; it never executes anything. Two callers use it:

* ``scripts/devtools/gen_initial_migration.py`` bakes the output into a committed
  Alembic revision, so the migration is frozen literal DDL rather than something
  that silently changes meaning as the models evolve.
* ``tests/security/test_rls.py`` compares what this module says *should* exist
  against what the live database actually has.

Three things here are load-bearing and should not be "simplified" later.

**Policies are generated from the ``tenant_id`` column, not from a marker.**
Forgetting a marker is silent and catastrophic; forgetting a column is not
possible, because nothing else in the codebase can find the tenant without it.

**The application role is not the table owner.** ``app_migrator`` owns the schema
and therefore bypasses RLS - that is how migrations and backfills touch every
tenant. ``app_rw`` owns nothing, holds no ``BYPASSRLS``, and is the only role the
API ever connects as. If those two ever collapse into one role, tenant isolation
is gone and every test here still passes, so the split is checked explicitly by
``tests/security/test_rls.py::test_app_role_is_not_an_owner``.

**An unset ``app.tenant_id`` is an error, not an empty result.** The strict
``current_setting('app.tenant_id')`` form raises ``undefined_object`` when the
GUC was never set in the session. The alternative - ``missing_ok`` returning
NULL - turns a missing tenant context into "this customer has no data", which
looks like a product bug and reads like a support ticket instead of a stack
trace.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy import MetaData, Table

# ---------------------------------------------------------------------------
# Roles and GUCs
# ---------------------------------------------------------------------------

#: Owns the schemas and runs migrations. Bypasses RLS by ownership. Never used
#: by the API.
MIGRATOR_ROLE = "app_migrator"

#: The only role the API and worker connect as. Read/write, subject to RLS.
APP_ROLE = "app_rw"

#: Narrow reader for the governed AI semantic layer. Granted on published views
#: only - never on prescriber-grain tables (docs/PLAN_REVIEW.md F-6).
READONLY_ROLE = "app_ro"

ALL_ROLES: tuple[str, ...] = (MIGRATOR_ROLE, APP_ROLE, READONLY_ROLE)

#: Transaction-local tenant context, set by the session dependency on every
#: request. Never read from request data (plan.md §5.5).
TENANT_GUC = "app.tenant_id"

#: Set to ``'on'`` only for platform-level operations (pre-authentication login
#: bookkeeping, platform admin console, retention jobs). It widens reads to rows
#: that belong to *no* tenant. It never widens reads to *another* tenant's rows.
PLATFORM_GUC = "app.platform_scope"

#: Set to the authenticated user's id during sign-in, and only then. It widens
#: reads on ``auth.memberships`` to *that one user's* rows across tenants, which
#: is the query "which organisations do I belong to" - unanswerable before a
#: tenant is chosen, and the reason a tenant can be chosen at all.
#:
#: This is the one cross-tenant read the application role can perform, and its
#: blast radius is one user's own membership list, which the login response hands
#: back to them anyway. It is deliberately *not* folded into the platform scope
#: flag: widening the tenant policy for platform scope would open every tenant's
#: memberships to every pre-authentication code path, a failed login included.
IDENTITY_GUC = "app.identity_user_id"

#: Strict form: raises if the GUC was never set. Used for NOT NULL tenant_id.
_TENANT_STRICT = f"current_setting('{TENANT_GUC}')::uuid"

#: Tolerant form: NULL if unset. Used only where a NULL-tenant row is legitimate
#: and the predicate already has to cope with NULL on the left-hand side.
_TENANT_LOOSE = f"nullif(current_setting('{TENANT_GUC}', true), '')::uuid"

_PLATFORM_ON = f"current_setting('{PLATFORM_GUC}', true) = 'on'"

#: Tolerant, so an unset identity yields NULL and the comparison is NULL rather
#: than true. A policy that opened up when its GUC was missing would be a policy
#: that opened up everywhere it was forgotten to be set.
_IDENTITY_LOOSE = f"nullif(current_setting('{IDENTITY_GUC}', true), '')::uuid"

#: Tables carrying the additive self-identity read policy. Exactly one, and it
#: should stay that way: every entry is a table whose rows become readable
#: outside a tenant, so each one needs its own argument.
IDENTITY_READ_TABLES: frozenset[str] = frozenset({"auth.memberships"})


class RlsIntent(StrEnum):
    """What kind of protection a table gets."""

    #: No ``tenant_id`` column, or an explicit, justified exemption.
    NONE = "NONE"
    #: Standard policy on a non-null ``tenant_id``.
    TENANT = "TENANT"
    #: Split read/write policies because ``tenant_id`` is nullable.
    TENANT_NULLABLE = "TENANT_NULLABLE"
    #: Either tenant form, plus UPDATE/DELETE revoked from the app role.
    APPEND_ONLY = "APPEND_ONLY"


@dataclass(frozen=True, slots=True)
class TableSecurity:
    """The resolved security posture of one table."""

    schema: str
    name: str
    intent: RlsIntent
    tenant_nullable: bool
    append_only: bool

    @property
    def fullname(self) -> str:
        return f"{self.schema}.{self.name}"


# ---------------------------------------------------------------------------
# Tables that legitimately have no tenant column
# ---------------------------------------------------------------------------

#: Platform tables. Listed explicitly so that a *new* table without ``tenant_id``
#: fails the invariant test instead of quietly joining this set. Adding a name
#: here is a deliberate, reviewable act.
PLATFORM_TABLES: frozenset[str] = frozenset(
    {
        # A user is one human across many customers; membership carries the tenant.
        "auth.users",
        "auth.sessions",
        "auth.password_reset_tokens",
        # The tenant registry itself cannot be filtered by tenant.
        "core.tenants",
        # Reference data, identical for every customer, read-only to all of them.
        "core.currencies",
        "core.fx_rates",
        # Dataset contracts are product definitions shipped with the platform.
        "ingestion.dataset_contracts",
    }
)


def resolve_security(table: Table, declared: str | None) -> TableSecurity:
    """Decide a table's posture from its columns, with ``__rls__`` as a modifier.

    ``declared`` is the model's ``__rls__``. It can only *add* restriction
    (``"append_only"``) or remove it loudly and on purpose (``"exempt"``); it
    cannot be the thing that grants a policy, because that failure mode is
    silent.
    """
    schema = table.schema or "public"
    column = table.columns.get("tenant_id")

    if column is None or declared == "exempt":
        return TableSecurity(schema, table.name, RlsIntent.NONE, False, False)

    append_only = declared == "append_only"
    nullable = bool(column.nullable)
    intent = RlsIntent.TENANT_NULLABLE if nullable else RlsIntent.TENANT
    return TableSecurity(schema, table.name, intent, nullable, append_only)


def security_plan(metadata: MetaData, declared: dict[str, str | None]) -> list[TableSecurity]:
    """Resolve every table in ``metadata``, sorted for stable generated output."""
    plan = [resolve_security(t, declared.get(t.fullname)) for t in metadata.tables.values()]
    return sorted(plan, key=lambda s: s.fullname)


def unprotected_tables(plan: Iterable[TableSecurity]) -> list[str]:
    """Tables with no policy that are not on the platform allowlist.

    An empty list is the invariant. Anything else means somebody added a table
    without deciding whether it is tenant data.
    """
    return sorted(
        s.fullname for s in plan if s.intent is RlsIntent.NONE and s.fullname not in PLATFORM_TABLES
    )


# ---------------------------------------------------------------------------
# Statement builders
# ---------------------------------------------------------------------------


def create_roles_sql() -> list[str]:
    """Create the three roles if the environment has not provisioned them.

    Deployment provisions these with passwords and ``LOGIN``. A developer
    running ``alembic upgrade head`` against a bare database has not, and grants
    against a missing role abort the whole migration. Creating them ``NOLOGIN``
    here is inert where they already exist and makes the grants below
    deterministic everywhere.
    """
    statements = []
    for role in ALL_ROLES:
        # `to_regrole` rather than a lookup in `pg_roles`: it answers the same
        # question without a query, so the generated DDL carries no SELECT with an
        # interpolated literal for a reader - or a linter - to have to vet.
        statements.append(
            f"DO $$ BEGIN\n"
            f"    IF to_regrole('{role}') IS NULL THEN\n"
            f"        EXECUTE 'CREATE ROLE {role} NOLOGIN';\n"
            f"    END IF;\n"
            f"END $$;"
        )
    return statements


def guc_defaults_sql() -> list[str]:
    """Give ``app.platform_scope`` a database-level default of ``off``.

    Postgres accepts any dotted custom setting at runtime, but ``current_setting``
    on one that nothing has ever set returns NULL. A default makes the tolerant
    reads below evaluate to a real ``off`` on a fresh connection, which is easier
    to reason about in an incident than a three-valued predicate.

    ``app.tenant_id`` is deliberately *not* given a default: its absence must
    stay loud.

    Wrapped in an exception handler because ``ALTER DATABASE`` needs ownership,
    and this is a convenience rather than a control - the policies are already
    correct when the GUC is unset.
    """
    return [
        "DO $$ BEGIN\n"
        "    EXECUTE format('ALTER DATABASE %I SET " + PLATFORM_GUC + " = ''off''',\n"
        "                   current_database());\n"
        "EXCEPTION WHEN insufficient_privilege THEN\n"
        "    RAISE NOTICE 'skipped ALTER DATABASE SET " + PLATFORM_GUC + "'\n"
        "                 ' (migration role does not own the database)';\n"
        "END $$;"
    ]


def enable_rls_sql(sec: TableSecurity) -> list[str]:
    """``ENABLE ROW LEVEL SECURITY`` plus the policy or policies for one table.

    Note the absence of ``FORCE ROW LEVEL SECURITY``. Forcing would apply the
    policy to the table owner too, and the owner is ``app_migrator`` - the role
    that has to run cross-tenant backfills and retention jobs. Isolation comes
    from ``app_rw`` not being an owner, which is checked directly.
    """
    if sec.intent is RlsIntent.NONE:
        return []

    fq = f"{sec.schema}.{sec.name}"
    out = [f"ALTER TABLE {fq} ENABLE ROW LEVEL SECURITY;"]

    if sec.tenant_nullable:
        # Reads: this tenant's rows, plus tenant-less platform rows only when the
        # caller has explicitly claimed platform scope.
        out.append(
            f"CREATE POLICY tenant_read ON {fq}\n"
            f"    FOR SELECT\n"
            f"    USING (tenant_id = {_TENANT_LOOSE}\n"
            f"           OR (tenant_id IS NULL AND {_PLATFORM_ON}));"
        )
        # Writes: a NULL tenant is legitimate (a failed login against an unknown
        # email belongs to nobody). Any non-null value must be the caller's own.
        out.append(
            f"CREATE POLICY tenant_write ON {fq}\n"
            f"    FOR INSERT\n"
            f"    WITH CHECK (tenant_id IS NULL OR tenant_id = {_TENANT_LOOSE});"
        )
        if not sec.append_only:
            out.append(
                f"CREATE POLICY tenant_modify ON {fq}\n"
                f"    FOR UPDATE\n"
                f"    USING (tenant_id = {_TENANT_LOOSE})\n"
                f"    WITH CHECK (tenant_id = {_TENANT_LOOSE});"
            )
            out.append(
                f"CREATE POLICY tenant_delete ON {fq}\n"
                f"    FOR DELETE\n"
                f"    USING (tenant_id = {_TENANT_LOOSE});"
            )
    elif fq in IDENTITY_READ_TABLES:
        # The read side is one policy rather than two, and it has to be. Permissive
        # policies are ORed, but OR does not rescue a predicate that *raises*:
        # the strict form errors outright when ``app.tenant_id`` is unset, and it
        # is evaluated for every row the identity clause does not already match.
        # So the tolerant comparison and the identity comparison live in the same
        # expression, and this one table gives up the loud failure on an unbound
        # read in exchange for being readable during sign-in at all.
        #
        # Writes keep the strict form. That is the half that matters: creating,
        # changing or removing a membership still requires a bound tenant and
        # still cannot cross one, so proving who you are buys a view of your own
        # memberships and nothing else.
        out.append(
            f"CREATE POLICY identity_read ON {fq}\n"
            f"    FOR SELECT\n"
            f"    USING (tenant_id = {_TENANT_LOOSE}\n"
            f"           OR user_id = {_IDENTITY_LOOSE});"
        )
        out.append(
            f"CREATE POLICY tenant_insert ON {fq}\n"
            f"    FOR INSERT\n"
            f"    WITH CHECK (tenant_id = {_TENANT_STRICT});"
        )
        out.append(
            f"CREATE POLICY tenant_modify ON {fq}\n"
            f"    FOR UPDATE\n"
            f"    USING (tenant_id = {_TENANT_STRICT})\n"
            f"    WITH CHECK (tenant_id = {_TENANT_STRICT});"
        )
        out.append(
            f"CREATE POLICY tenant_delete ON {fq}\n"
            f"    FOR DELETE\n"
            f"    USING (tenant_id = {_TENANT_STRICT});"
        )
    else:
        out.append(
            f"CREATE POLICY tenant_isolation ON {fq}\n"
            f"    USING (tenant_id = {_TENANT_STRICT})\n"
            f"    WITH CHECK (tenant_id = {_TENANT_STRICT});"
        )
    return out


def grants_sql(plan: Sequence[TableSecurity], schemas: Sequence[str]) -> list[str]:
    """Schema usage and per-table privileges for the application roles.

    ``app_ro`` is granted nothing here on purpose. The governed AI layer reads
    published views only, and those grants are issued where the views are
    created - so a new table is never readable by the assistant by accident.
    """
    out: list[str] = []
    for schema in schemas:
        out.append(f"GRANT USAGE ON SCHEMA {schema} TO {APP_ROLE}, {READONLY_ROLE};")

    for sec in plan:
        fq = f"{sec.schema}.{sec.name}"
        if sec.append_only:
            out.append(f"GRANT SELECT, INSERT ON {fq} TO {APP_ROLE};")
        else:
            out.append(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {fq} TO {APP_ROLE};")
    return out


def revoke_public_sql(schemas: Sequence[str]) -> list[str]:
    """Close the default-open doors Postgres leaves ajar.

    ``PUBLIC`` can create objects in the ``public`` schema by default, which is
    the kind of finding that surfaces in a security review long after anyone
    remembers why it was left open. Database-level ``CONNECT`` is revoked from
    ``PUBLIC`` and re-granted to the three named roles, so a future role added by
    someone else does not inherit access to customer data by existing.
    """
    out = ["REVOKE ALL ON SCHEMA public FROM PUBLIC;"]
    out.extend(f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC;" for schema in schemas)
    out.append(
        "DO $$ BEGIN\n"
        "    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());\n"
        "    EXECUTE format('GRANT CONNECT ON DATABASE %I TO " + ", ".join(ALL_ROLES) + "',\n"
        "                   current_database());\n"
        "EXCEPTION WHEN insufficient_privilege THEN\n"
        "    RAISE WARNING 'could not revoke PUBLIC access to the database;'\n"
        "                  ' grant ownership to " + MIGRATOR_ROLE + " and re-run';\n"
        "END $$;"
    )
    return out


#: Alembic's bookkeeping table. Lives in ``public`` because Alembic puts it there.
ALEMBIC_VERSION_TABLE = "public.alembic_version"


def migration_visibility_sql() -> list[str]:
    """Let the application read the schema version, and nothing else in ``public``.

    ``revoke_public_sql`` closes ``public`` to everyone, which is right - but it also closes
    the one table in there the application has a legitimate reason to read. At startup the API
    compares the revision the code was built against with the revision the database is
    actually at, and during a rolling deploy those differ; a service that cannot tell the
    difference between "schema is one migration behind" and "schema is fine" fails later, at a
    missing column, in a request handler, with a 500.

    ``USAGE`` on the schema and ``SELECT`` on the one table, granted narrowly. No ``INSERT``:
    only the migrator moves the version forward, and an application that can rewrite its own
    schema version can convince itself of anything.
    """
    return [
        f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}, {READONLY_ROLE};",
        f"GRANT SELECT ON {ALEMBIC_VERSION_TABLE} TO {APP_ROLE}, {READONLY_ROLE};",
    ]


# ---------------------------------------------------------------------------
# Partitioning
# ---------------------------------------------------------------------------

#: Yearly range partitions for the three high-volume tables. Yearly rather than
#: monthly because the query patterns are "this brand, these 24 months" - pruning
#: to two partitions is already the whole win, and 13 children per table stays
#: legible in ``\d+`` where 156 does not.
PARTITION_FIRST_YEAR = 2019
PARTITION_LAST_YEAR = 2032


@dataclass(frozen=True, slots=True)
class PartitionedTable:
    """A range-partitioned parent and the key it is partitioned on."""

    schema: str
    name: str
    key: str
    #: ``date`` for month columns, ``timestamptz`` for audit timestamps.
    bound_type: str

    @property
    def fullname(self) -> str:
        return f"{self.schema}.{self.name}"


#: Every range-partitioned parent in the schema.
#:
#: This list is consulted by three separate things - the initial-migration generator, the
#: ``speaker-roi db sql`` renderer, and the annual maintenance job that creates next year's
#: children - so it lives here rather than in whichever of them was written first. A
#: partitioned table missing from this tuple gets no children, and inserts for it fail at
#: runtime with "no partition of relation found for row", months after the table was added.
PARTITIONED_TABLES: tuple[PartitionedTable, ...] = (
    PartitionedTable("core", "hcp_rx_monthly", "month", "date"),
    PartitionedTable("core", "marketing_activity", "month", "date"),
    PartitionedTable("audit", "audit_events", "created_at", "timestamptz"),
)


def _bound(parent: PartitionedTable, year: int) -> str:
    """A partition bound that does not depend on the session time zone.

    ``FOR VALUES FROM ('2026-01-01')`` on a ``timestamptz`` column is resolved
    using whatever ``TimeZone`` the migration happened to run under, so the same
    migration produces different boundaries in Mumbai and in CI. Anchoring to UTC
    explicitly makes the physical layout reproducible.
    """
    day = date(year, 1, 1).isoformat()
    return f"{day} 00:00:00+00" if parent.bound_type == "timestamptz" else day


def partition_children_sql(parent: PartitionedTable) -> list[str]:
    """Yearly children plus a DEFAULT catch-all.

    The DEFAULT partition exists so a row dated outside the pre-created range is
    *stored and visible* rather than rejected at insert time. Ingesting a file
    with a typo'd year should surface as a data-quality issue on the Data Health
    page, not as a 500 that loses the whole upload. A maintenance job rolls the
    window forward; see docs/runbook.md.

    Children are deliberately left without grants. PostgreSQL checks privileges
    on the table *named in the query*, so ``app_rw`` reading the parent works
    while ``SELECT * FROM core.hcp_rx_monthly_y2026`` - which would bypass the
    parent's row-level-security policy - is refused outright. Any partition added
    later must stay ungranted for the same reason.
    """
    out: list[str] = []
    for year in range(PARTITION_FIRST_YEAR, PARTITION_LAST_YEAR + 1):
        child = f"{parent.schema}.{parent.name}_y{year}"
        out.append(
            f"CREATE TABLE {child} PARTITION OF {parent.fullname}\n"
            f"    FOR VALUES FROM ('{_bound(parent, year)}') TO ('{_bound(parent, year + 1)}');"
        )
    out.append(
        f"CREATE TABLE {parent.schema}.{parent.name}_default "
        f"PARTITION OF {parent.fullname} DEFAULT;"
    )
    return out


__all__ = [
    "ALEMBIC_VERSION_TABLE",
    "ALL_ROLES",
    "APP_ROLE",
    "MIGRATOR_ROLE",
    "PARTITIONED_TABLES",
    "PARTITION_FIRST_YEAR",
    "PARTITION_LAST_YEAR",
    "IDENTITY_GUC",
    "IDENTITY_READ_TABLES",
    "PLATFORM_GUC",
    "PLATFORM_TABLES",
    "READONLY_ROLE",
    "TENANT_GUC",
    "PartitionedTable",
    "RlsIntent",
    "TableSecurity",
    "create_roles_sql",
    "enable_rls_sql",
    "grants_sql",
    "guc_defaults_sql",
    "migration_visibility_sql",
    "partition_children_sql",
    "resolve_security",
    "revoke_public_sql",
    "security_plan",
    "unprotected_tables",
]
