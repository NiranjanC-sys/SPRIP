"""Static checks on ``Base.metadata`` that would otherwise fail mid-migration.

Every check here exists because the failure it prevents is expensive in the same
specific way: the schema is valid Python, imports cleanly, passes every unit test
that does not touch a database, and then aborts partway through
``alembic upgrade head`` - leaving a half-built database and a developer reading a
stack trace 3,500 statements deep to learn that two indexes share a name.

    python scripts/devtools/check_schema.py

Exits non-zero on any error-level finding. Warnings are printed and do not fail
the run: they flag indexes that cost write throughput without serving a query,
which is a judgement call rather than a defect.
"""

from __future__ import annotations

import sys
from collections import defaultdict

from sqlalchemy import Index, Table, UniqueConstraint

import speaker_roi_core.models  # noqa: F401  - registers every table
from speaker_roi_core.db.base import Base

#: PostgreSQL's NAMEDATALEN - 1. Longer identifiers are truncated *silently*, so
#: two long similar names collapse into one and the second CREATE fails.
MAX_IDENTIFIER = 63


class Report:
    """Collected findings. Errors fail the run; warnings only inform."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_identifier_lengths(tables: list[Table], report: Report) -> None:
    """Nothing over 63 bytes, measured in bytes rather than characters."""
    for table in tables:
        for kind, name in _named_objects(table):
            if name is None:
                continue
            size = len(name.encode("utf-8"))
            if size > MAX_IDENTIFIER:
                report.error(
                    f"{size} bytes (max {MAX_IDENTIFIER}) - {kind} on "
                    f"{table.fullname}: {name}\n"
                    f"    pass an explicit shorter name= to the helper"
                )


def check_duplicate_names(tables: list[Table], report: Report) -> None:
    """Relation names must be unique per schema.

    In PostgreSQL tables, indexes, sequences and views share one namespace inside
    a schema. An index named the same as another index - or as a table - in the
    same schema is a hard ``DuplicateTable`` error at ``CREATE`` time.
    """
    seen: dict[tuple[str, str], list[str]] = defaultdict(list)
    for table in tables:
        schema = table.schema or "public"
        seen[(schema, table.name)].append(f"table {table.fullname}")
        for index in table.indexes:
            if index.name:
                seen[(schema, index.name)].append(f"index on {table.fullname}")

    for (schema, name), owners in sorted(seen.items()):
        if len(owners) > 1:
            joined = "\n      ".join(sorted(owners))
            report.error(
                f"name {schema}.{name} is claimed {len(owners)} times:\n"
                f"      {joined}\n"
                f"    tables and indexes share one namespace per schema"
            )


def check_redundant_prefix_indexes(tables: list[Table], report: Report) -> None:
    """Warn where one index is a strict column-prefix of another.

    A B-tree on ``(tenant_id, brand_id)`` already answers everything a B-tree on
    ``(tenant_id)`` answers, because the planner can seek on any leading subset of
    the key. Keeping both means paying two index writes per INSERT for one index
    worth of read performance.

    Only flagged, never failed: a narrower index is legitimately smaller and can
    win on a very wide table, and partial indexes with different predicates are
    not comparable at all.
    """
    for table in tables:
        # Candidates that could make another index redundant. Unique constraints
        # count: PostgreSQL implements each with a backing unique index that the
        # planner uses for ordinary lookups exactly like any other B-tree.
        covering = [
            (index.name or "?", _column_names(index))
            for index in table.indexes
            if not _is_partial(index)
        ] + [
            (f"{constraint.name} (unique)", [c.name for c in constraint.columns])
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint) and constraint.name
        ]
        redundant = [
            (index.name or "?", _column_names(index))
            for index in sorted(table.indexes, key=lambda i: i.name or "")
            if not index.unique and not _is_partial(index)
        ]
        for name, columns in redundant:
            for other_name, other_columns in covering:
                if other_name == name or len(other_columns) < len(columns):
                    continue
                if other_columns[: len(columns)] == columns:
                    report.warn(
                        f"{table.fullname}: {name} ({', '.join(columns)}) is covered "
                        f"by {other_name} ({', '.join(other_columns)})"
                    )
                    break


def check_tenant_tables_are_seekable(tables: list[Table], report: Report) -> None:
    """Every tenant table needs at least one index leading with ``tenant_id``.

    Row-level security rewrites every read as ``... AND tenant_id =
    current_setting('app.tenant_id')``. Without a tenant-leading index that
    predicate is a filter over the whole table, so the largest customer's query
    plan degrades in proportion to *every other* customer's data - the one
    scaling failure a multi-tenant product cannot explain away.
    """
    for table in tables:
        if "tenant_id" not in table.columns:
            continue
        leading = [
            index.name for index in table.indexes if _column_names(index)[:1] == ["tenant_id"]
        ]
        # A unique constraint leading with tenant_id is just as good: Postgres
        # backs it with a real index and the planner seeks on its prefix.
        leading += [
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
            and [c.name for c in constraint.columns][:1] == ["tenant_id"]
        ]
        pk_leads = _constraint_columns(table)[:1] == ["tenant_id"]
        if not leading and not pk_leads:
            report.error(
                f"{table.fullname} has a tenant_id column but no index leading "
                f"with it; add tenant_lookup_index(...) or recency_index(...)"
            )


def check_partitioned_tables_include_key(tables: list[Table], report: Report) -> None:
    """A partitioned table's primary key must contain its partition key.

    PostgreSQL refuses a unique constraint that does not include every partition
    key column, because it cannot enforce uniqueness across partitions otherwise.
    The error text names the constraint, not the partitioning, so it reads as a
    mysterious PK rejection.
    """
    partition_keys = {
        "core.hcp_rx_monthly": "month",
        "core.marketing_activity": "month",
        "audit.audit_events": "created_at",
    }
    for table in tables:
        key = partition_keys.get(table.fullname)
        if key is None:
            continue
        pk_columns = _constraint_columns(table)
        if key not in pk_columns:
            report.error(
                f"{table.fullname} is partitioned by {key} but its primary key is "
                f"({', '.join(pk_columns)}); the partition key must be part of it"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _named_objects(table: Table) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = [("table", table.name)]
    out.extend(("index", index.name) for index in table.indexes)
    out.extend(
        (type(constraint).__name__, getattr(constraint, "name", None))
        for constraint in table.constraints
    )
    return [(kind, name) for kind, name in out if isinstance(name, str)]


def _column_names(index: Index) -> list[str]:
    """Column names in key order, ignoring ASC/DESC and expression wrappers."""
    names: list[str] = []
    for expression in index.expressions:
        name = getattr(expression, "name", None)
        if name is None:
            # A DESC/NULLS wrapper or a raw expression: unwrap one level.
            element = getattr(expression, "element", None)
            name = getattr(element, "name", None)
        names.append(name if isinstance(name, str) else "<expr>")
    return names


def _is_partial(index: Index) -> bool:
    return index.dialect_options["postgresql"].get("where") is not None


def _constraint_columns(table: Table) -> list[str]:
    pk = table.primary_key
    return [column.name for column in pk.columns] if pk is not None else []


CHECKS = (
    check_identifier_lengths,
    check_duplicate_names,
    check_tenant_tables_are_seekable,
    check_partitioned_tables_include_key,
    check_redundant_prefix_indexes,
)


def main() -> int:
    tables = list(Base.metadata.sorted_tables)
    report = Report()
    for check in CHECKS:
        check(tables, report)

    for warning in report.warnings:
        print(f"warn   {warning}")
    for error in report.errors:
        print(f"ERROR  {error}")

    indexes = sum(len(t.indexes) for t in tables)
    print(
        f"\n{len(tables)} tables, {indexes} indexes checked - "
        f"{len(report.errors)} errors, {len(report.warnings)} warnings"
    )
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
