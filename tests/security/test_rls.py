"""Tenant isolation, verified against a real PostgreSQL.

These are the tests the whole multi-tenant design rests on, and they are written to fail
loudly if the design is quietly undone later. Three properties are checked *behaviourally* -
by planting another tenant's row and trying to read it - rather than by reading ``pg_policies``
back. Asserting that a policy exists proves the migration ran; asserting that a query cannot
see a row proves the policy *works*, and those come apart in several real ways: a policy on a
table whose owner is also the application role, a query that reaches a partition child
directly, a GUC set at session scope that leaks across a pooled connection.

The fourth property has no SQL expression at all. ``app_rw`` must not own the tables, because
an owner bypasses row-level security entirely and every policy above becomes decoration. That
one is a catalogue check, and it is the single most important assertion in this file: if it
regresses, every other test here still passes.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from speaker_roi_core.db.ddl import APP_ROLE, MIGRATOR_ROLE, PLATFORM_GUC, TENANT_GUC
from speaker_roi_core.db.session import bind_platform_scope, bind_tenant

pytestmark = [pytest.mark.security, pytest.mark.integration]

TENANT_A = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
TENANT_B = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")

#: ``undefined_object``: what ``current_setting('app.tenant_id')`` raises when nothing set it.
UNDEFINED_OBJECT = "42704"


async def _plant(engine: AsyncEngine) -> None:
    """Create two tenants and one brand each, as the schema owner.

    Committed and left behind. The rows are idempotent on ``code``, so a re-run is a no-op
    rather than a unique-violation, and leaving them means a failing test can be investigated
    against the state that produced it instead of a cleaned-up database.
    """
    async with engine.begin() as conn:
        for tenant, code in ((TENANT_A, "rlsa"), (TENANT_B, "rlsb")):
            await conn.execute(
                text(
                    "INSERT INTO core.tenants (id, code, name) VALUES (:id, :code, :name) "
                    "ON CONFLICT (code) DO NOTHING"
                ),
                {"id": str(tenant), "code": f"t-{code}", "name": f"RLS fixture {code}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO core.brands (id, tenant_id, code, name) "
                    "VALUES (:id, :tenant, :code, :name) ON CONFLICT DO NOTHING"
                ),
                {
                    "id": str(uuid.uuid5(tenant, "brand")),
                    "tenant": str(tenant),
                    "code": f"b-{code}",
                    "name": f"Brand {code}",
                },
            )


# ---------------------------------------------------------------------------
# The property that makes every other one meaningful
# ---------------------------------------------------------------------------


async def test_the_app_role_is_not_a_table_owner(migrator_engine: AsyncEngine) -> None:
    """``FORCE ROW LEVEL SECURITY`` is deliberately absent, so ownership is the whole control.

    An owner bypasses RLS. If ``app_rw`` ever becomes the owner - by someone running the
    migrations as it, or by collapsing the two roles to simplify a deployment - every policy
    in the schema stops applying and every isolation test in this file still passes, because
    they all run as ``app_rw`` and would simply be permitted. Hence a catalogue assertion.
    """
    async with migrator_engine.connect() as conn:
        owned = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relkind IN ('r', 'p') AND pg_get_userbyid(c.relowner) = :role "
                    "AND n.nspname IN ('auth','core','ingestion','analytics','ml','audit')"
                ),
                {"role": APP_ROLE},
            )
        ).scalar()
    assert owned == 0, f"{APP_ROLE} owns {owned} tables; ownership bypasses RLS"


async def test_the_app_role_cannot_bypass_rls_or_be_a_superuser(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreatedb "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
    assert row.rolsuper is False
    assert row.rolbypassrls is False
    assert row.rolcreatedb is False


async def test_the_migrator_owns_the_schema(migrator_engine: AsyncEngine) -> None:
    """The other half of the split: somebody has to be able to run cross-tenant DDL."""
    async with migrator_engine.connect() as conn:
        owned = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relkind IN ('r', 'p') AND pg_get_userbyid(c.relowner) = :role "
                    "AND n.nspname IN ('auth','core','ingestion','analytics','ml','audit')"
                ),
                {"role": MIGRATOR_ROLE},
            )
        ).scalar()
    assert owned > 50, f"expected the whole schema owned by {MIGRATOR_ROLE}, found {owned}"


# ---------------------------------------------------------------------------
# Behavioural isolation
# ---------------------------------------------------------------------------


async def test_a_bound_tenant_sees_only_its_own_rows(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    await _plant(migrator_engine)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=app_engine, expire_on_commit=False)
    for bound, expected_code in ((TENANT_A, "b-rlsa"), (TENANT_B, "b-rlsb")):
        async with factory() as session, session.begin():
            await bind_tenant(session, bound)
            codes = list(
                (await session.execute(text("SELECT code FROM core.brands ORDER BY code")))
                .scalars()
                .all()
            )
        assert codes == [expected_code], f"tenant {bound} saw {codes}"


async def test_an_unbound_read_raises_rather_than_returning_nothing(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """The design decision worth defending: no tenant bound is an *error*.

    The tempting alternative - ``current_setting(..., true)``, which returns NULL - turns a
    wiring bug into "this customer has no data". That reaches the user as an empty dashboard,
    gets reported as a data-loading problem, and is investigated by the wrong team for a day.
    A raised ``undefined_object`` reaches an engineer in seconds.
    """
    await _plant(migrator_engine)
    # Nested rather than combined: pytest.raises is a synchronous context manager, so
    # collapsing the two into one `async with` fails at the protocol level.
    async with app_engine.connect() as conn:
        with pytest.raises(DBAPIError) as caught:
            await conn.execute(text("SELECT count(*) FROM core.brands"))
    assert getattr(caught.value.orig, "sqlstate", None) == UNDEFINED_OBJECT


async def test_a_tenant_cannot_write_a_row_belonging_to_another(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """The ``WITH CHECK`` half. A policy with only ``USING`` filters reads and permits writes.

    Without it, tenant A can insert rows stamped with tenant B's id - invisible to A
    immediately afterwards, so the bug does not present until B sees data it did not create.
    """
    await _plant(migrator_engine)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=app_engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await bind_tenant(session, TENANT_A)
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO core.brands (tenant_id, code, name) "
                        "VALUES (:tenant, 'smuggled', 'Smuggled')"
                    ),
                    {"tenant": str(TENANT_B)},
                )
        # The failed statement poisoned the transaction, so the confirming read needs a new
        # one. Reusing it produces `current transaction is aborted`, which reads like the
        # isolation check failing when it is the probe that is broken.
        async with session.begin():
            await bind_tenant(session, TENANT_B)
            leaked = (
                await session.execute(
                    text("SELECT count(*) FROM core.brands WHERE code = 'smuggled'")
                )
            ).scalar()
    assert leaked == 0


async def test_the_tenant_binding_does_not_survive_the_transaction(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """``set_config(..., true)`` is transaction-local, and that is load-bearing.

    A session-level ``SET`` persists on the pooled connection, so the next request to borrow
    it inherits the previous request's tenant. In production that is a rare, load-dependent,
    unreproducible cross-tenant read - the worst class of bug this system could have - so the
    scope is asserted rather than assumed.
    """
    await _plant(migrator_engine)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=app_engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await bind_tenant(session, TENANT_A)
            assert (
                await session.execute(text(f"SELECT current_setting('{TENANT_GUC}', true)"))
            ).scalar() == str(TENANT_A)
        # Same session, same underlying connection, new transaction.
        async with session.begin():
            after = (
                await session.execute(text(f"SELECT current_setting('{TENANT_GUC}', true)"))
            ).scalar()
    assert not after, f"the tenant binding leaked across transactions: {after!r}"


async def test_platform_scope_widens_to_tenantless_rows_only(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """Platform scope is not a master key, and the asymmetry is the point.

    It opens rows belonging to *no* tenant - a failed login against an unknown address,
    platform reference data. On a table whose ``tenant_id`` is NOT NULL there is no platform
    branch in the policy at all, so the strict predicate still raises. If this ever starts
    returning rows, platform scope has become a cross-tenant read reachable from a GUC.
    """
    await _plant(migrator_engine)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=app_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await bind_platform_scope(session)
        assert (
            await session.execute(text(f"SELECT current_setting('{PLATFORM_GUC}', true)"))
        ).scalar() == "on"
        with pytest.raises(DBAPIError) as caught:
            await session.execute(text("SELECT count(*) FROM core.brands"))
    assert getattr(caught.value.orig, "sqlstate", None) == UNDEFINED_OBJECT


async def test_binding_a_tenant_turns_platform_scope_off(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """Order-independence. Otherwise a request that claimed platform scope earlier keeps it."""
    await _plant(migrator_engine)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=app_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await bind_platform_scope(session)
        await bind_tenant(session, TENANT_A)
        assert (
            await session.execute(text(f"SELECT current_setting('{PLATFORM_GUC}', true)"))
        ).scalar() == "off"


# ---------------------------------------------------------------------------
# The routes around the policy
# ---------------------------------------------------------------------------


async def test_a_partition_child_cannot_be_queried_directly(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    """Children are left ungranted on purpose, and this is why.

    PostgreSQL checks privileges on the relation *named in the query*. A partition child
    inherits its parent's policies for queries routed through the parent, but naming the child
    directly is a different relation - so the only thing standing between a curious query and
    an unfiltered read of a year of prescription data is the absent ``SELECT`` grant.
    """
    async with app_engine.connect() as conn:
        with pytest.raises(ProgrammingError) as caught:
            await conn.execute(text("SELECT count(*) FROM core.hcp_rx_monthly_y2026"))
    # 42501 insufficient_privilege - refused, not filtered.
    assert getattr(caught.value.orig, "sqlstate", None) == "42501"


async def test_the_app_role_cannot_disable_a_policy(app_engine: AsyncEngine) -> None:
    """``ALTER TABLE ... DISABLE ROW LEVEL SECURITY`` requires ownership. Confirmed, not assumed."""
    async with app_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("ALTER TABLE core.brands DISABLE ROW LEVEL SECURITY"))


async def test_the_app_role_cannot_create_objects_in_public(app_engine: AsyncEngine) -> None:
    """``REVOKE ALL ON SCHEMA public FROM PUBLIC`` is the one Postgres leaves open by default.

    A role that can create a table in ``public`` can create one without a policy and copy
    rows into it, which is a data-exfiltration route that leaves the tenant tables untouched.
    """
    async with app_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("CREATE TABLE public.rls_escape (id int)"))


async def test_the_app_role_can_read_the_schema_version(app_engine: AsyncEngine) -> None:
    """The one narrow exception to the ``public`` lockdown, and it is read-only.

    The API compares the revision it was built against with the one the database is at, so it
    can refuse to serve rather than fail later at a missing column. No ``INSERT``: an
    application that can rewrite its own schema version can convince itself of anything.
    """
    async with app_engine.connect() as conn:
        revision = (
            await conn.execute(text("SELECT version_num FROM public.alembic_version"))
        ).scalar()
        assert revision
        with pytest.raises(DBAPIError):
            await conn.execute(text("UPDATE public.alembic_version SET version_num = 'tampered'"))


async def test_every_tenant_table_has_row_level_security_enabled(
    migrator_engine: AsyncEngine,
) -> None:
    """The invariant that catches the *next* table rather than the ones already reviewed.

    A table added with a ``tenant_id`` and no policy is readable across every tenant, and
    nothing about writing it looks wrong - which is why this is checked from the catalogue
    against the live database rather than trusted to code review.
    """
    async with migrator_engine.connect() as conn:
        unprotected = list(
            (
                await conn.execute(
                    text(
                        "SELECT n.nspname || '.' || c.relname "
                        "FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' "
                        "WHERE c.relkind IN ('r','p') AND NOT c.relispartition "
                        "AND n.nspname IN ('auth','core','ingestion','analytics','ml','audit') "
                        "AND (NOT c.relrowsecurity "
                        "     OR NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid)) "
                        "ORDER BY 1"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert unprotected == [], f"tables with a tenant_id and no enforced policy: {unprotected}"


async def test_the_probe_used_by_startup_agrees_with_these_tests(app_engine: AsyncEngine) -> None:
    """``probe_rls`` is what the API runs at boot and what ``db verify-rls`` reports.

    Checked against the same database these tests use, so the operator tool and the test suite
    cannot drift into disagreeing about whether isolation is enforced.
    """
    from speaker_roi_core.db.session import probe_rls

    info = await probe_rls(app_engine, probe_table="core.brands")
    assert info["role"] == APP_ROLE
    assert info["is_superuser"] is False
    assert info["bypasses_rls"] is False
    assert info["rls_enabled"] is True
    assert info["unscoped_raised"] is True
    assert info["unscoped_sqlstate"] == UNDEFINED_OBJECT
