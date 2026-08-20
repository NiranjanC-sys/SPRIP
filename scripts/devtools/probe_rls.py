"""Probe the live database for the guarantees the DDL layer claims to provide.

This is the fast, dependency-free version of ``tests/security/test_rls.py``: it
runs against whatever cluster ``pg.py`` is managing and answers the only question
that matters after a migration - *does app_rw actually see nothing but its own
tenant?* Run it after any change to ``db/ddl.py`` or to a model's ``__rls__``.

    python scripts/devtools/probe_rls.py
"""

from __future__ import annotations

import sys
import uuid

import psycopg

import speaker_roi_core.models  # noqa: F401  - populates Base.metadata
from speaker_roi_core.db.base import Base, declared_rls
from speaker_roi_core.db.ddl import APP_ROLE, READONLY_ROLE, RlsIntent, security_plan

#: The two ways an unset tenant context surfaces, both of them hard errors.
#: `undefined_object` on a connection that has never set the GUC;
#: `invalid_text_representation` on one that has, because Postgres keeps the
#: placeholder defined for the rest of the session and rollback restores it to the
#: empty string rather than removing it. The second is the case a pooled
#: connection actually produces, so both must be treated as "correctly refused".
NO_TENANT_CONTEXT = (
    psycopg.errors.UndefinedObject,
    psycopg.errors.InvalidTextRepresentation,
)


HOST, PORT, DB = "127.0.0.1", 54329, "speaker_roi"
MIG = f"host={HOST} port={PORT} dbname={DB} user=app_migrator password=app_migrator_pw"
APP = f"host={HOST} port={PORT} dbname={DB} user={APP_ROLE} password=app_rw_pw"

T1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
T2 = uuid.UUID("22222222-2222-2222-2222-222222222222")

results: list[tuple[str, bool, str]] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    results.append((label, passed, detail))


def seed() -> None:
    """Two tenants, one brand each, written by the migrator (which bypasses RLS)."""
    with psycopg.connect(MIG, autocommit=True) as c:
        for tid, code, name in ((T1, "acme", "Acme Pharma"), (T2, "globex", "Globex Labs")):
            c.execute(
                "insert into core.tenants (id, code, name) values (%s, %s, %s) "
                "on conflict (id) do nothing",
                (tid, code, name),
            )
            c.execute(
                "insert into core.brands (tenant_id, code, name) values (%s, %s, %s) "
                "on conflict do nothing",
                (tid, f"{code}-brand", f"{name} Brand"),
            )


def probe_reads() -> None:
    with psycopg.connect(APP) as c:
        with c.cursor() as cur:
            cur.execute("select set_config('app.tenant_id', %s, true)", (str(T1),))
            cur.execute("select code from core.brands order by code")
            rows = [r[0] for r in cur.fetchall()]
        check("app_rw reads only its own tenant's rows", rows == ["acme-brand"], str(rows))
        c.rollback()

        # An unset tenant context must be an error. Returning zero rows would look
        # to a user like "this customer has no data" and to an on-call engineer
        # like a product bug rather than a missing dependency.
        try:
            with c.cursor() as cur:
                cur.execute("select count(*) from core.brands")
            check("unset app.tenant_id raises", False, "query succeeded")
        except NO_TENANT_CONTEXT:
            check("unset app.tenant_id raises rather than returning empty", True)
        c.rollback()

        # The GUC is transaction-local, so it cannot leak to the next request that
        # borrows this pooled connection.
        with c.cursor() as cur:
            cur.execute("select set_config('app.tenant_id', %s, true)", (str(T1),))
        c.rollback()
        try:
            with c.cursor() as cur:
                cur.execute("select count(*) from core.brands")
            check("tenant context does not survive the transaction", False, "leaked")
        except NO_TENANT_CONTEXT:
            check("tenant context does not survive the transaction", True)
        c.rollback()


def probe_writes() -> None:
    with psycopg.connect(APP) as c:
        try:
            with c.cursor() as cur:
                cur.execute("select set_config('app.tenant_id', %s, true)", (str(T1),))
                cur.execute(
                    "insert into core.brands (tenant_id, code, name) values (%s, 'x', 'X')",
                    (T2,),
                )
            check("cross-tenant INSERT refused", False, "insert succeeded")
        except psycopg.errors.InsufficientPrivilege:
            check("cross-tenant INSERT refused by WITH CHECK", True)
        c.rollback()

        # Re-parenting is the subtler attack: the USING clause admits the row and
        # only the WITH CHECK clause rejects the new tenant_id.
        try:
            with c.cursor() as cur:
                cur.execute("select set_config('app.tenant_id', %s, true)", (str(T1),))
                cur.execute("update core.brands set tenant_id = %s", (T2,))
            check("re-parenting a row to another tenant refused", False, "update succeeded")
        except psycopg.errors.InsufficientPrivilege:
            check("re-parenting a row to another tenant refused by WITH CHECK", True)
        c.rollback()


def probe_grants() -> None:
    with psycopg.connect(APP) as c, c.cursor() as cur:
        cur.execute(
            "select p, has_table_privilege(%s, 'audit.audit_events', p) "
            "from unnest(array['SELECT','INSERT','UPDATE','DELETE']) p",
            (APP_ROLE,),
        )
        privs = dict(cur.fetchall())
        check(
            "audit.audit_events is append-only for app_rw",
            privs == {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False},
            str(privs),
        )

        # The whole isolation model rests on app_rw not owning anything: an owner
        # bypasses every policy on its own tables with no error raised anywhere.
        cur.execute(
            "select count(*) from pg_class c join pg_roles r on r.oid = c.relowner "
            "where r.rolname = %s and c.relkind in ('r', 'p', 'v', 'm')",
            (APP_ROLE,),
        )
        owned = cur.fetchone()[0]
        cur.execute("select rolbypassrls or rolsuper from pg_roles where rolname = %s", (APP_ROLE,))
        privileged = cur.fetchone()[0]
        check(
            "app_rw owns no relations and cannot bypass RLS",
            owned == 0 and not privileged,
            f"owns={owned} bypassrls={privileged}",
        )

        # Querying a partition child names a table with no policy of its own, so
        # ungranted children are the only thing between a curious query and every
        # tenant's prescriber data.
        cur.execute(
            "select count(*) from pg_class c where c.relispartition and c.relkind = 'r' "
            "and has_table_privilege(%s, c.oid, 'SELECT')",
            (APP_ROLE,),
        )
        check("no partition child is readable by app_rw", cur.fetchone()[0] == 0)

        # app_ro exists for the governed AI layer and must never reach raw tables.
        cur.execute(
            "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where c.relkind in ('r', 'p') "
            "and n.nspname in ('core', 'analytics', 'ml', 'ingestion') "
            "and has_table_privilege(%s, c.oid, 'SELECT')",
            (READONLY_ROLE,),
        )
        check("app_ro cannot read raw tables (published views only)", cur.fetchone()[0] == 0)


def probe_policy_coverage() -> None:
    """Every tenant table has RLS enabled, and nothing else does."""
    expected = {
        s.fullname
        for s in security_plan(Base.metadata, declared_rls())
        if s.intent is not RlsIntent.NONE
    }
    with psycopg.connect(MIG) as c, c.cursor() as cur:
        cur.execute(
            "select n.nspname || '.' || c.relname from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where c.relrowsecurity and not c.relispartition"
        )
        live = {r[0] for r in cur.fetchall()}
    missing = sorted(expected - live)
    extra = sorted(live - expected)
    check(
        f"all {len(expected)} tenant tables have RLS enabled, and only those",
        not missing and not extra,
        f"missing={missing} unexpected={extra}",
    )


def probe_exclude_constraint() -> None:
    """Effective-dated history cannot overlap - the constraint says so, not the app."""
    with psycopg.connect(MIG, autocommit=True) as c:
        brand_id = c.execute(
            "select id from core.brands where tenant_id = %s limit 1", (T1,)
        ).fetchone()[0]
        c.execute("delete from core.finance_assumptions where tenant_id = %s", (T1,))
        c.execute("delete from core.finance_versions where tenant_id = %s", (T1,))
        version_id = c.execute(
            "insert into core.finance_versions (tenant_id, code, label) "
            "values (%s, 'probe', 'Probe') returning id",
            (T1,),
        ).fetchone()[0]
        insert = (
            "insert into core.finance_assumptions (tenant_id, finance_version_id, brand_id, "
            "contribution_per_nrx, currency, effective_from, effective_to) "
            "values (%s, %s, %s, %s, 'INR', %s, %s)"
        )
        c.execute(insert, (T1, version_id, brand_id, 1200, "2026-01-01", "2026-07-01"))
        try:
            c.execute(insert, (T1, version_id, brand_id, 900, "2026-04-01", "2026-10-01"))
            check("overlapping effective-dated rows rejected", False, "insert succeeded")
        except psycopg.errors.ExclusionViolation:
            check("overlapping effective-dated rows rejected by EXCLUDE", True)
        # An adjacent, non-overlapping row must still be accepted: a constraint that
        # rejects everything would pass the check above and break the product.
        try:
            c.execute(insert, (T1, version_id, brand_id, 900, "2026-07-01", "2027-01-01"))
            check("adjacent effective-dated row accepted", True)
        except psycopg.errors.ExclusionViolation as exc:
            check("adjacent effective-dated row accepted", False, str(exc).strip())
        c.execute("delete from core.finance_assumptions where tenant_id = %s", (T1,))
        c.execute("delete from core.finance_versions where tenant_id = %s", (T1,))


PROBES = (
    probe_reads,
    probe_writes,
    probe_grants,
    probe_policy_coverage,
    probe_exclude_constraint,
)


def main() -> int:
    seed()
    for probe in PROBES:
        probe()
    for label, passed, detail in results:
        suffix = f"  [{detail}]" if detail and not passed else ""
        print(f"{'PASS' if passed else 'FAIL'}  {label}{suffix}")
    passed_count = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed_count}/{len(results)} passed")
    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
