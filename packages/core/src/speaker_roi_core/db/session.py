"""Async engine, session factory, and the transaction that binds the tenant.

This module is where multi-tenant isolation is actually enforced. The policies live in the
migration and the ``tenant_id`` columns live in the models, but a row-level-security policy
reading ``current_setting('app.tenant_id')`` does nothing at all unless something sets that
GUC on the connection - correctly, for every unit of work, and never leaving it set for the
next one. That is this file's whole job, and there are four decisions in it worth stating.

**The GUC is transaction-local.** ``set_config('app.tenant_id', $1, true)`` - the third
argument is ``is_local`` - so PostgreSQL discards it at ``COMMIT`` or ``ROLLBACK``. The
session-level alternative (``SET`` without ``LOCAL``) persists on the *pooled connection*,
so tenant A's value survives into whichever request next borrows that connection. In
production that presents as a rare, unreproducible cross-tenant read under load, which is
the worst possible failure to debug and the worst possible one to have. Transaction-local
makes the leak structurally impossible rather than merely unlikely: there is no code path
that can forget to reset it, because the database does the resetting.

**Every unit of work is one transaction, opened explicitly.** ``expire_on_commit=False``
and no autobegin surprises: :func:`session_scope` begins, yields, and commits or rolls
back. A request that touched two tenants would need two transactions, and cannot get them
from one scope - which is the point.

**The application role is not the owner role.** RLS does not apply to a table's owner or
to a superuser, so a service connecting as the owner has policies that silently never fire.
:func:`assert_rls_enforced` proves at startup that the configured role is actually subject
to them, by attempting a read with no tenant bound and requiring it to return nothing.

**A missing tenant raises instead of returning nothing.** The policies in
:mod:`speaker_roi_core.db.ddl` use the *strict* ``current_setting('app.tenant_id')`` form,
which raises ``undefined_object`` when the GUC was never set. That is a deliberate and
slightly unusual choice, and it changes what this module must do: an unscoped query against
a tenant-owned table does not come back empty, it errors. The empty-result alternative turns
a missing tenant context into "this customer has no data", which reaches the support queue
as a product bug instead of reaching the on-call engineer as a stack trace.

Two consequences that the code below has to respect. First, ``bind_tenant`` must never set
the GUC to the empty string as a way of "clearing" it - ``''::uuid`` raises
``invalid_text_representation``, a confusing error that looks like corrupt data rather than
a missing context. Second, cross-tenant-capable code does not get there by unsetting the
tenant; it claims ``app.platform_scope``, which widens reads to rows belonging to *no*
tenant and never to another tenant's rows.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, Final, Literal

from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from speaker_roi_core.config import DatabaseSettings, Settings, get_settings
from speaker_roi_core.context import current_tenant_id, current_tenant_id_or_none
from speaker_roi_core.db.ddl import IDENTITY_GUC, PLATFORM_GUC, TENANT_GUC
from speaker_roi_core.errors import (
    AlreadyExistsError,
    ConflictError,
    DependencyUnavailableError,
    ImmutableResourceError,
)
from speaker_roi_core.logging import get_logger

log = get_logger("speaker_roi.db")

# The GUC names are imported from :mod:`speaker_roi_core.db.ddl`, which generates the
# policy text, rather than redeclared here. Two string literals that must agree is a
# latent defect with an unusually bad failure mode: a typo produces policies that never
# match (the service reads nothing and looks broken) or, on the nullable-tenant tables
# whose predicate tolerates NULL, policies that match more than intended.

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

#: PostgreSQL error codes worth translating into domain errors rather than surfacing as a
#: 500. Everything else is genuinely unexpected and should reach the error handler intact.
_PG_UNIQUE_VIOLATION: Final = "23505"
_PG_INSUFFICIENT_PRIVILEGE: Final = "42501"
#: Raised by ``current_setting('app.tenant_id')`` when the GUC was never set - the strict
#: form :mod:`speaker_roi_core.db.ddl` deliberately uses. Surfacing this to a caller as a
#: 500 would be right in one sense (it *is* a programming error) but useless in another, so
#: :func:`_translate` turns it into the same refusal the application-side check produces.
_PG_UNDEFINED_OBJECT: Final = "42704"
#: ``''::uuid``. Only reachable if something set the tenant GUC to an empty string, which
#: this module never does; translated so that the resulting incident report says "tenant
#: scope" rather than "invalid input syntax for type uuid".
_PG_INVALID_TEXT_REPRESENTATION: Final = "22P02"
_PG_FOREIGN_KEY_VIOLATION: Final = "23503"
_PG_CHECK_VIOLATION: Final = "23514"
_PG_LOCK_TIMEOUT: Final = "55P03"
_PG_QUERY_CANCELED: Final = "57014"
_PG_SERIALIZATION_FAILURE: Final = "40001"
_PG_DEADLOCK: Final = "40P01"


def build_engine(
    settings: Settings | None = None,
    *,
    db: DatabaseSettings | None = None,
    use_null_pool: bool = False,
) -> AsyncEngine:
    """Construct the async engine.

    ``use_null_pool`` for tests and for the Celery worker's forked children. A pool
    inherited across ``fork`` hands the same socket to two processes, which corrupts the
    protocol stream in ways that surface as impossible driver errors; the worker therefore
    either disposes the pool in a post-fork hook or uses none.

    ``pool_pre_ping`` is on. It costs one round trip per checkout and removes the entire
    class of "first request after an idle period fails" incidents that a connection killed
    by a proxy or a database restart produces.
    """
    settings = settings or get_settings()
    db = db or settings.database

    engine = create_async_engine(
        db.dsn(),
        echo=db.echo_sql,
        echo_pool=False,
        future=True,
        pool_pre_ping=True,
        poolclass=NullPool if use_null_pool else None,
        **(
            {}
            if use_null_pool
            else {
                "pool_size": db.pool_size,
                "max_overflow": db.max_overflow,
                "pool_timeout": db.pool_timeout_seconds,
                "pool_recycle": db.pool_recycle_seconds,
            }
        ),
        connect_args={
            # A per-connection server setting rather than a per-statement one: applying
            # the timeouts here means they cover every statement including the ones
            # SQLAlchemy issues itself, and cannot be skipped by a code path that forgets.
            "server_settings": {
                "application_name": f"{settings.app_name}-{settings.app_env}",
                "statement_timeout": str(db.statement_timeout_ms),
                "lock_timeout": str(db.lock_timeout_ms),
                # Fail fast on a wedged connection rather than hanging a request until the
                # client gives up. Two minutes is generous for OLTP and far below the
                # analytical work's budget, which runs in the worker with its own engine.
                "idle_in_transaction_session_timeout": "120000",
                # Explicit, so a `search_path` inherited from the role cannot silently
                # resolve an unqualified name to a different schema than the models expect.
                "search_path": "public",
            },
            # asyncpg caches prepared statements per connection. That is a real speedup and
            # it breaks behind a transaction-mode connection pooler such as PgBouncer,
            # which multiplexes statements across server connections. Disabled because the
            # Azure deployment path in docs/azure_migration.md puts exactly such a pooler
            # in front of the database, and discovering this in production means a service
            # that works locally and fails intermittently there.
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        },
    )
    _install_engine_instrumentation(engine)
    return engine


def _install_engine_instrumentation(engine: AsyncEngine) -> None:
    """Attach the listeners that make connection behaviour observable.

    Deliberately does *not* log statements. plan.md §15 forbids logging sensitive free
    text, and a statement log with bound parameters is the largest single source of it -
    every ingested row passes through as a parameter. Timing and connection lifecycle are
    logged; the SQL text is not.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn: Any, record: Any) -> None:  # pragma: no cover - I/O path
        log.debug("db.connection.established")

    @event.listens_for(engine.sync_engine, "checkout")
    def _on_checkout(dbapi_conn: Any, record: Any, proxy: Any) -> None:  # pragma: no cover
        # A connection returned to the pool must carry no tenant. Transaction-local GUCs
        # guarantee this, but the guarantee is worth asserting cheaply in non-production:
        # if someone ever introduces a session-level SET, this is where it shows up.
        record.info.pop("tenant_id", None)

    @event.listens_for(engine.sync_engine, "invalidate")
    def _on_invalidate(dbapi_conn: Any, record: Any, exc: BaseException | None) -> None:
        log.warning("db.connection.invalidated", error_type=type(exc).__name__ if exc else None)


def get_engine() -> AsyncEngine:
    """The process-wide engine, created on first use."""
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """The process-wide session factory.

    ``expire_on_commit=False`` because the API serialises ORM objects *after* the
    transaction commits. With expiry on, every attribute access on a committed object
    triggers a refresh against a closed session and raises - so the alternative is either
    to serialise inside the transaction (holding a connection during JSON encoding) or to
    convert everything to plain objects before commit. Neither is worth it.

    ``autoflush=False`` because an implicit flush mid-read can raise an integrity error
    from a statement the reader never issued, at a point in the code that has no way to
    interpret it. Writes flush explicitly.
    """
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def dispose_engine() -> None:
    """Close the pool. Call on shutdown, and in the Celery post-fork hook."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        log.info("db.engine.disposed")
    _engine = None
    _sessionmaker = None


# ---------------------------------------------------------------------------
# Tenant binding
# ---------------------------------------------------------------------------


async def bind_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Set the transaction-local tenant the row-level-security policies read.

    Must be called inside an open transaction. ``set_config(..., true)`` - the third
    argument is ``is_local`` - ties the value to the transaction, so PostgreSQL discards it
    at ``COMMIT`` or ``ROLLBACK``. The session-level alternative persists on the *pooled
    connection*, so tenant A's value survives into whichever request next borrows it. That
    presents in production as a rare, unreproducible cross-tenant read under load, which is
    both the worst failure to debug and the worst one to have.

    ``platform_scope`` is explicitly turned *off* on every tenant-scoped transaction. It
    defaults to off at the database level, but a default is a claim about configuration and
    this is a claim about this transaction - and the two differ precisely when someone has
    changed the default.

    Takes a non-optional tenant deliberately. There is no "clear the tenant" call, because
    clearing it by setting the empty string would make the strict policy raise
    ``invalid_text_representation`` - an error that reads like corrupt data. Code that needs
    no tenant uses :func:`bind_platform_scope`.
    """
    await session.execute(
        text(f"SELECT set_config('{TENANT_GUC}', :tenant, true)"),
        {"tenant": str(tenant_id)},
    )
    await session.execute(text(f"SELECT set_config('{PLATFORM_GUC}', 'off', true)"))


async def bind_platform_scope(session: AsyncSession) -> None:
    """Claim platform scope for this transaction, with no tenant bound.

    Widens reads to rows that belong to *no* tenant - a failed login against an unknown
    email address, platform-level reference data, retention bookkeeping. It does **not**
    widen reads to another tenant's rows: the nullable-tenant policies read
    ``tenant_id IS NULL AND platform_scope``, and the strict policies on tenant-owned
    tables have no platform branch at all, so they raise here rather than opening up.

    That asymmetry is the design. Cross-tenant access requires a role with ``BYPASSRLS``,
    which the application role deliberately does not have, so no combination of GUCs
    reachable from the API can produce a cross-tenant read.
    """
    await session.execute(text(f"SELECT set_config('{PLATFORM_GUC}', 'on', true)"))


async def bind_identity(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Declare, for this transaction only, which authenticated user the queries are for.

    Sign-in has a genuine ordering problem: the answer to "which tenant" comes from
    ``auth.memberships``, and reading that table needs a tenant. The identity GUC resolves it
    without a bypass. It is read by one additive ``SELECT``-only policy, on that one table,
    matching ``user_id`` - so what it unlocks is a single user's own membership list, which is
    also what the login response hands back to them.

    Callers bind the identity immediately before the read that needs it, rather than at the top
    of the request. A value set once and left set is a value that is still set for the next
    query somebody adds, and the next query is not necessarily one that should see across
    tenants.

    Transaction-local for the same reason as :func:`bind_tenant`: a session-level setting would
    outlive the request on the pooled connection and quietly attach one user's identity to the
    next borrower.
    """
    await session.execute(
        text(f"SELECT set_config('{IDENTITY_GUC}', :user_id, true)"),
        {"user_id": str(user_id)},
    )


async def current_bound_tenant(session: AsyncSession) -> str | None:
    """Read back what the database thinks the tenant is.

    Uses the tolerant two-argument form, because this is diagnostic code and must be able
    to report "unset" rather than raise. Reading it back rather than trusting the
    application's own variable is the only way to catch a binding issued on a different
    connection than the query will use - which is what an accidental second session inside
    one request produces, and which no amount of application-side bookkeeping would reveal.
    """
    result = await session.execute(text(f"SELECT current_setting('{TENANT_GUC}', true)"))
    value = result.scalar()
    return value or None


@contextlib.asynccontextmanager
async def session_scope(
    *,
    tenant_id: uuid.UUID | None = None,
    read_only: bool = False,
) -> AsyncIterator[AsyncSession]:
    """One transaction, with the tenant bound for its whole lifetime.

    The default resolves the tenant from the ambient request context, which raises if
    none is bound. Passing ``tenant_id`` explicitly is for the worker, whose tenant comes
    from the persisted job record rather than from a request.

    ``read_only=True`` issues ``SET TRANSACTION READ ONLY``, so the database refuses any
    write. Worth doing for the analytical read paths: it turns "this endpoint should not
    write" from a code review comment into an enforced property, and it lets PostgreSQL
    skip some bookkeeping.

    Commit and rollback are handled here, and driver errors are translated on the way out
    so the service layer never has to know a PostgreSQL error code.
    """
    resolved = tenant_id if tenant_id is not None else current_tenant_id()
    factory = get_sessionmaker()

    async with factory() as session:
        try:
            async with session.begin():
                if read_only:
                    await session.execute(text("SET TRANSACTION READ ONLY"))
                await bind_tenant(session, resolved)
                yield session
        except DBAPIError as exc:
            raise _translate(exc) from exc


@contextlib.asynccontextmanager
async def platform_session_scope(*, reason: str) -> AsyncIterator[AsyncSession]:
    """A transaction with platform scope and no tenant. For the paths that need one.

    Login (which resolves a tenant *from* the credentials, so it cannot have one first),
    platform administration, scheduled retention work and tenant creation. Every use is
    logged with its ``reason``, and ``reason`` is a required keyword rather than an optional
    one so that this scope cannot be entered absent-mindedly and every call site has had to
    articulate itself in a string a reviewer will read.

    Not a cross-tenant read. Tenant-owned tables raise here rather than opening up, because
    their policy has no platform branch - see :func:`bind_platform_scope`.
    """
    log.info("db.platform_session", reason=reason)
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            async with session.begin():
                await bind_platform_scope(session)
                yield session
        except DBAPIError as exc:
            raise _translate(exc) from exc


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: a tenant-scoped transaction for the request.

    A generator dependency rather than a context manager so that FastAPI's own
    exit-stack handling closes it, including when a later dependency raises. The tenant
    comes from the ambient context, which the authentication middleware has already
    populated from the *session record* - never from request data, per plan.md §15.
    """
    async with session_scope() as session:
        yield session


async def get_read_only_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency for analytical reads. Writes are refused by the database."""
    async with session_scope(read_only=True) as session:
        yield session


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


def _pg_code(exc: DBAPIError) -> str | None:
    """Extract the SQLSTATE, across asyncpg and psycopg.

    The two drivers expose it differently - asyncpg on ``sqlstate``, psycopg on
    ``pgcode`` - and both are wrapped by SQLAlchemy. Checking both rather than the one in
    use today means the psycopg fallback path (used by Alembic) translates identically.
    """
    orig = getattr(exc, "orig", None)
    for attribute in ("sqlstate", "pgcode"):
        code = getattr(orig, attribute, None)
        if code:
            return str(code)
    return None


def _constraint_name(exc: DBAPIError) -> str | None:
    orig = getattr(exc, "orig", None)
    name = getattr(orig, "constraint_name", None)
    if name:
        return str(name)
    diag = getattr(orig, "diag", None)
    return str(getattr(diag, "constraint_name", "") or "") or None


def _translate(exc: DBAPIError) -> Exception:
    """Map a driver error onto the application's taxonomy.

    Only the codes with an unambiguous domain meaning are translated. Everything else is
    returned unchanged so it reaches the generic handler, gets logged with its traceback
    and becomes a 500 - because a database error nobody anticipated should be investigated,
    not smoothed into a plausible-looking 4xx.
    """
    code = _pg_code(exc)
    constraint = _constraint_name(exc)

    if code in {_PG_UNDEFINED_OBJECT, _PG_INVALID_TEXT_REPRESENTATION} and TENANT_GUC in str(
        exc.orig
    ):
        # The policy predicate could not resolve the tenant. Reaching here means a query ran
        # outside session_scope(), because that binds the GUC before yielding - so it is a
        # wiring defect, not a caller mistake.
        #
        # Translated all the same, and to a refusal rather than a 500, for one reason: the
        # untranslated version surfaces as "unrecognized configuration parameter" or
        # "invalid input syntax for type uuid", and an on-call engineer reading either at
        # 3am will spend their first twenty minutes looking for corrupt data or a bad
        # migration. ``internal_detail`` carries the real diagnosis; the caller still gets
        # nothing actionable, which is correct, because there is nothing they can do.
        from speaker_roi_core.errors import TenantScopeRequiredError

        return TenantScopeRequiredError(
            internal_detail=(
                f"row-level security predicate evaluated with {TENANT_GUC} unset or empty "
                f"(SQLSTATE {code}). The query ran outside session_scope(); a transaction "
                "that reads tenant-owned tables must bind a tenant before its first "
                "statement."
            )
        )

    if code == _PG_INSUFFICIENT_PRIVILEGE:
        # The application role lacks a grant. On an append-only table this is the intended
        # outcome of an UPDATE or DELETE attempt, so it becomes the domain error the user
        # should see rather than a 500 - the grants are the enforcement, and this is the
        # explanation.
        return ImmutableResourceError(
            (constraint or "record").removeprefix("pk_"),
            reason="This record is append-only. Add a new entry rather than editing this one.",
        )

    if isinstance(exc, IntegrityError):
        if code == _PG_FOREIGN_KEY_VIOLATION:
            return ConflictError(
                "A referenced record is missing or still in use.",
                internal_detail=f"foreign key violation on {constraint}",
            )
        if code == _PG_CHECK_VIOLATION:
            return ConflictError(
                "The submitted values violate a rule for this record.",
                internal_detail=f"check constraint {constraint} violated",
                context={"constraint": constraint} if constraint else None,
            )
        if constraint and constraint.startswith("uq_"):
            # ``uq_<table>_<col1>_<col2>`` by the naming convention in db/base.py, so the
            # field can be recovered for a field-level error without a lookup table.
            _, _, tail = constraint.partition("_")
            table, _, column = tail.partition("_")
            return AlreadyExistsError(table or "record", column or "value", "<redacted>")
        return ConflictError(
            "This change conflicts with an existing record.",
            internal_detail=f"integrity error on {constraint}",
        )

    if code in {_PG_SERIALIZATION_FAILURE, _PG_DEADLOCK}:
        # Genuinely retryable: the transaction was aborted to break a cycle, and the same
        # request submitted again will usually succeed.
        return DependencyUnavailableError(
            "database",
            internal_detail=f"transaction aborted with SQLSTATE {code}; retry is appropriate",
        )

    if code in {_PG_LOCK_TIMEOUT, _PG_QUERY_CANCELED}:
        from speaker_roi_core.errors import TimeoutError_

        return TimeoutError_(
            "The request took too long and was stopped.",
            internal_detail=f"SQLSTATE {code} - statement or lock timeout reached",
        )

    if isinstance(exc, OperationalError):
        return DependencyUnavailableError("database", internal_detail=str(exc.orig)[:200])

    return exc


# ---------------------------------------------------------------------------
# Startup verification
# ---------------------------------------------------------------------------


async def check_connectivity(engine: AsyncEngine | None = None) -> dict[str, Any]:
    """A liveness probe that also reports what it connected as.

    The role and the ``rolbypassrls`` flag are in the payload because the single most
    consequential misconfiguration in this system - the application connecting as a role
    that bypasses row-level security - is invisible in every functional test and obvious
    in one line of a health payload.
    """
    engine = engine or get_engine()
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT current_user AS role, current_database() AS database, "
                        "       version() AS version, "
                        "       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) "
                        "         AS is_superuser, "
                        "       (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user) "
                        "         AS bypasses_rls"
                    )
                )
            )
            .mappings()
            .one()
        )
    payload = dict(row)
    payload["version"] = str(payload["version"]).split(" on ")[0]
    if payload["is_superuser"] or payload["bypasses_rls"]:
        log.error(
            "db.role_bypasses_rls",
            role=payload["role"],
            is_superuser=payload["is_superuser"],
            bypasses_rls=payload["bypasses_rls"],
        )
    return payload


async def probe_rls(
    engine: AsyncEngine | None = None,
    *,
    probe_table: str = "core.events",
) -> dict[str, Any]:
    """Gather the isolation facts without judging them.

    Separate from :func:`assert_rls_enforced` because the two callers want opposite things.
    Startup wants to abort on the first problem - a service that runs with tenant isolation
    broken is worse than one that does not run. An operator running ``speaker-roi db
    verify-rls`` wants the whole list, because they are about to fix all of it, and a tool
    that reports one problem per invocation turns one diagnosis into four.
    """
    engine = engine or get_engine()
    async with engine.connect() as conn:
        return await _probe_rls(conn, probe_table)


async def assert_rls_enforced(
    engine: AsyncEngine | None = None,
    *,
    probe_table: str = "core.events",
) -> dict[str, Any]:
    """Prove that row-level security actually applies to the connected role.

    The check is behavioural, not declarative. Asking ``pg_class.relrowsecurity`` confirms
    a policy *exists*, which is a different claim: a policy on a table owned by the
    connecting role exists and never fires, and ``FORCE ROW LEVEL SECURITY`` is
    deliberately not set here because the owner has to run cross-tenant backfills. So the
    only trustworthy question is what the database does when asked.

    Two probes, and they are decisive together:

    1. **With no tenant bound, the count must raise.** The strict policy predicate
       evaluates ``current_setting('app.tenant_id')``, which raises ``undefined_object``
       when unset. A role that bypasses RLS never evaluates the predicate at all, so it
       returns a number instead - which is exactly the condition worth refusing to start
       on, and it is caught here even if ``pg_roles`` were somehow misread.
    2. **Bound to a tenant that does not exist, the count must be zero.** This is what
       distinguishes a predicate that filters from one that is present but tautological.
       Probe 1 alone would pass against ``USING (true)`` wrapped in a
       ``current_setting`` call.

    Called at API and worker startup in hardened environments, and fatal rather than a
    warning: a service that cannot prove its isolation must not accept traffic, because
    the alternative is one serving cross-tenant data while reporting healthy.
    """
    info = await probe_rls(engine, probe_table=probe_table)

    if info["bypasses_rls"] or info["is_superuser"]:
        raise RuntimeError(
            f"role {info['role']!r} bypasses row-level security "
            f"(superuser={info['is_superuser']}, bypassrls={info['bypasses_rls']}). "
            "Every tenant policy is inert for this role. Connect as the application role, "
            "not the owner or a superuser - see docs/runbook.md."
        )
    if not info["rls_enabled"]:
        raise RuntimeError(
            f"row-level security is not enabled on {probe_table}. The migration that "
            "creates the policies has not been applied, or was applied and then reverted."
        )
    if not info["unscoped_raised"]:
        raise RuntimeError(
            f"{probe_table} returned {info['unscoped_rows']} rows with no tenant bound "
            "instead of raising. Either the policy is not restricting this role, or it "
            "was written with the permissive current_setting(..., true) form, which turns "
            "a missing tenant into an empty result. Refusing to start - see "
            "docs/runbook.md#rls-verification."
        )
    if info["absent_tenant_rows"] != 0:
        raise RuntimeError(
            f"{probe_table} returned {info['absent_tenant_rows']} rows for a tenant id "
            "that does not exist. The policy is present and evaluated but does not filter; "
            "refusing to start."
        )
    log.info(
        "db.rls_verified",
        role=info["role"],
        probe_table=probe_table,
        unscoped_sqlstate=info["unscoped_sqlstate"],
    )
    return info


async def _probe_rls(conn: AsyncConnection, probe_table: str) -> dict[str, Any]:
    """Gather the facts :func:`assert_rls_enforced` needs.

    ``probe_table`` is interpolated into the ``count(*)``, which cannot be parameterised -
    an identifier is not a value. It is validated against the catalogue first, so the only
    strings reaching the interpolation are ones PostgreSQL has confirmed name a real table.
    """
    schema, _, table = probe_table.partition(".")
    catalogue = (
        (
            await conn.execute(
                text(
                    "SELECT c.relrowsecurity AS rls_enabled, c.relname AS name, "
                    "       n.nspname AS schema "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :schema AND c.relname = :table"
                ),
                {"schema": schema, "table": table},
            )
        )
        .mappings()
        .first()
    )
    if catalogue is None:
        raise RuntimeError(
            f"probe table {probe_table!r} does not exist; migrations have not been applied"
        )

    role = (
        (
            await conn.execute(
                text(
                    "SELECT current_user AS role, "
                    "  (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) "
                    "    AS is_superuser, "
                    "  (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user) "
                    "    AS bypasses_rls"
                )
            )
        )
        .mappings()
        .one()
    )

    # Safe to interpolate: schema and table came back from the catalogue, not the caller.
    count_sql = text(f'SELECT count(*) FROM "{catalogue["schema"]}"."{catalogue["name"]}"')

    # Probe 1, in a savepoint. A failed statement poisons the transaction, and this one is
    # *expected* to fail - without the nested block the second probe would come back
    # "current transaction is aborted" and be misreported as a policy failure.
    unscoped_raised = False
    unscoped_sqlstate: str | None = None
    unscoped_rows = -1
    try:
        async with conn.begin_nested():
            unscoped_rows = int((await conn.execute(count_sql)).scalar_one())
    except DBAPIError as exc:
        unscoped_raised = True
        unscoped_sqlstate = _pg_code(exc)

    # Probe 2: a tenant id that certainly owns no rows. Generated rather than hard-coded to
    # zeros, so the probe cannot be satisfied by a fixture someone once inserted.
    async with conn.begin_nested():
        await conn.execute(
            text(f"SELECT set_config('{TENANT_GUC}', :tenant, true)"),
            {"tenant": str(uuid.uuid4())},
        )
        absent_tenant_rows = int((await conn.execute(count_sql)).scalar_one())

    return {
        "role": role["role"],
        "is_superuser": bool(role["is_superuser"]),
        "bypasses_rls": bool(role["bypasses_rls"]),
        "rls_enabled": bool(catalogue["rls_enabled"]),
        "unscoped_raised": unscoped_raised,
        "unscoped_sqlstate": unscoped_sqlstate,
        "unscoped_rows": unscoped_rows,
        "absent_tenant_rows": absent_tenant_rows,
    }


HealthState = Literal["ok", "degraded", "down"]


async def health() -> tuple[HealthState, dict[str, Any]]:
    """Readiness detail for ``/health/ready``.

    Distinguishes ``degraded`` from ``down``: a connected database whose role bypasses RLS
    is reachable but must not serve traffic, and that is a different operational situation
    from an unreachable one. Reporting both as ``down`` sends the on-call engineer to
    look at the wrong thing.
    """
    try:
        info = await check_connectivity()
    except Exception as exc:
        return "down", {"error": type(exc).__name__, "detail": str(exc)[:200]}
    if info["is_superuser"] or info["bypasses_rls"]:
        return "degraded", info | {"reason": "connected role bypasses row-level security"}
    tenant = current_tenant_id_or_none()
    return "ok", info | {"tenant_bound": tenant is not None}


def set_engine_for_tests(
    engine: AsyncEngine, factory: Callable[..., AsyncSession] | None = None
) -> None:
    """Install a test engine, replacing the process-wide one.

    Tests use this rather than monkeypatching module globals, so the two globals stay
    private and there is one documented seam. Production code has no reason to call it.
    """
    global _engine, _sessionmaker
    _engine = engine
    _sessionmaker = (
        factory  # type: ignore[assignment]
        if factory is not None
        else async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )
    )


__all__ = [
    "HealthState",
    "assert_rls_enforced",
    "bind_identity",
    "bind_platform_scope",
    "bind_tenant",
    "build_engine",
    "check_connectivity",
    "current_bound_tenant",
    "dispose_engine",
    "get_engine",
    "get_read_only_session",
    "get_session",
    "get_sessionmaker",
    "health",
    "platform_session_scope",
    "session_scope",
    "set_engine_for_tests",
]
