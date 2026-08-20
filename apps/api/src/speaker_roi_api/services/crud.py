"""The generic half of every resource endpoint: keyset listing, fetch, create, patch, deactivate.

Written once because the alternative is writing it twenty-two times, and the parts that are easy
to get wrong are the parts that would then be wrong in some subset of those twenty-two.

**Listing is keyset, never offset.** ``OFFSET 50000`` makes PostgreSQL walk and discard fifty
thousand rows before returning one, so the last page of a large table is the slowest query in the
application. Worse, on a table being written to, offset paging *silently skips and repeats rows* -
a row inserted before the cursor shifts everything after it, and the client that is paging through
to build a report gets a report with holes in it and no error.

**Every list query is bounded by a hard maximum**, not merely by a default. A client that asks for
a hundred thousand rows is asking for the API to buffer a hundred thousand ORM objects, and the
answer is to give it the maximum page and a cursor rather than to oblige.

**Updates use optimistic concurrency and cannot be opted out of.** The ``row_version`` column is
in the ``UPDATE ... WHERE`` clause, so two people editing the same event cost is a 412 for the
second rather than a silent overwrite. The alternative - last write wins - is indistinguishable
from working right up to the point where a finance figure someone reviewed is not the figure that
is stored.

**The tenant is never a parameter here.** It is enforced by row-level security on the connection,
which means a bug in this module cannot leak across tenants. Passing ``tenant_id`` into a filter
would look like defence in depth and would actually be the opposite: it invites the reader to
believe *that* is the enforcement, and a future refactor that drops the filter would then be
silently catastrophic instead of merely wrong.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypeVar

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.orm.exc import StaleDataError

from speaker_roi_api.deps import encode_cursor
from speaker_roi_api.services import audit
from speaker_roi_core.enums import AuditAction
from speaker_roi_core.errors import (
    ConflictError,
    InvalidCursorError,
    NotFoundError,
    PreconditionFailedError,
    ValidationError,
)
from speaker_roi_core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from speaker_roi_api.deps import Page

log = get_logger(__name__)

T = TypeVar("T")

#: How many rows a list endpoint will count before giving up on an exact total.
#:
#: An exact ``COUNT(*)`` over a filtered multi-million-row partition is a sequential scan, and it
#: is requested by the UI purely to render "1-50 of N". Above this ceiling the total is reported
#: as ``None`` and the UI shows "1-50 of many", which is a far better trade than a two-second
#: page load for a number nobody acts on.
COUNT_CEILING = 10_000


def _coerce_cursor_key(raw: str, column: InstrumentedAttribute[Any]) -> Any:
    """Turn the cursor's text sort key back into the column's own Python type.

    The cursor is text - ``encode_cursor`` builds it with an f-string - and asyncpg binds
    parameters by their Python type rather than letting the server infer one. Handing a ``str``
    to a ``timestamptz`` comparison therefore fails at the driver, not with a helpful error but
    with an operator-does-not-exist from PostgreSQL. So the type is read off the column and the
    key is coerced back to it.

    A key that will not coerce is a corrupted or hand-built cursor, and it is refused rather
    than silently ignored: ignoring it would return page one while the client believes it is
    reading page nine, which produces duplicated rows in whatever the client is assembling.
    """
    try:
        python_type = column.type.python_type
    except NotImplementedError:  # pragma: no cover - custom types without a Python mapping
        return raw
    try:
        if python_type is str:
            return raw
        if python_type is uuid.UUID:
            return uuid.UUID(raw)
        if python_type is datetime:
            return datetime.fromisoformat(raw)
        if python_type is date:
            return date.fromisoformat(raw)
        if python_type is int:
            return int(raw)
        if python_type is Decimal:
            return Decimal(raw)
        if python_type is bool:
            return raw.lower() in {"true", "1"}
    except (ValueError, ArithmeticError) as exc:
        raise InvalidCursorError(
            internal_detail=f"cursor key {raw!r} is not a {python_type}"
        ) from exc
    return raw


async def paginate(
    session: AsyncSession,
    stmt: Select[tuple[Any, ...]],
    page: Page,
    *,
    sort_column: InstrumentedAttribute[Any],
    id_column: InstrumentedAttribute[uuid.UUID],
    descending: bool = True,
    with_total: bool = False,
) -> tuple[list[Any], str | None, int | None]:
    """Apply a keyset window to ``stmt`` and return ``(rows, next_cursor, total)``.

    The ordering is always ``(sort_column, id_column)`` - the id is a tiebreaker, and it is not
    optional. Without it, rows sharing a sort value straddle the page boundary in an order the
    database is free to change between the two queries, so some are returned twice and others
    never. A stable secondary key is the whole reason keyset pagination is correct.

    One extra row is fetched beyond the requested limit. Its existence is what tells us whether
    to emit a cursor, and asking that way costs one row rather than a second ``COUNT`` query -
    and unlike a count, it cannot disagree with the page it accompanies.
    """
    decoded = page.decode()
    if decoded is not None:
        raw_key, cursor_id = decoded
        cursor_key = _coerce_cursor_key(raw_key, sort_column)
        # The compound comparison, spelled out rather than using a row-value constructor: the
        # two forms are equivalent for the planner here, and this one is legible to whoever has
        # to reason about whether the index is being used.
        boundary = (
            or_(
                sort_column < cursor_key,
                and_(sort_column == cursor_key, id_column < cursor_id),
            )
            if descending
            else or_(
                sort_column > cursor_key,
                and_(sort_column == cursor_key, id_column > cursor_id),
            )
        )
        stmt = stmt.where(boundary)

    total: int | None = None
    if with_total:
        # Counted over a bounded subquery so the ceiling is enforced by the database rather
        # than by reading rows and stopping. Note this counts what remains *after* the cursor
        # boundary, which is what a "N remaining" indicator should say; a total over the whole
        # filtered set would change meaning between page one and page two.
        capped = stmt.limit(COUNT_CEILING).subquery()
        counted = (await session.execute(select(func.count()).select_from(capped))).scalar_one()
        total = None if counted >= COUNT_CEILING else int(counted)

    order = (
        (sort_column.desc(), id_column.desc())
        if descending
        else (sort_column.asc(), id_column.asc())
    )
    rows = list((await session.execute(stmt.order_by(*order).limit(page.limit + 1))).scalars())

    next_cursor: str | None = None
    if len(rows) > page.limit:
        rows = rows[: page.limit]
        last = rows[-1]
        next_cursor = encode_cursor(getattr(last, sort_column.key), getattr(last, id_column.key))
    return rows, next_cursor, total


async def get_or_404(
    session: AsyncSession,
    model: type[T],
    row_id: uuid.UUID,
    *,
    resource: str,
    options: Sequence[Any] = (),
) -> T:
    """Fetch one row by id, or raise 404.

    404 and not 403 for a row in another tenant. Row-level security means the query simply
    returns nothing, and that is the correct answer to surface: telling a caller "this exists
    but is not yours" confirms the existence of another customer's record, which is a
    cross-tenant information leak achieved entirely through status codes.
    """
    stmt = select(model).where(model.id == row_id)  # type: ignore[attr-defined]
    if options:
        stmt = stmt.options(*options)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError(resource, row_id)
    return row


async def create(
    session: AsyncSession,
    model: type[T],
    values: dict[str, Any],
    *,
    resource: str,
    audit_fields: Sequence[str],
    label: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> T:
    """Insert a row, stamp the actor, and write the audit entry.

    ``IntegrityError`` is translated rather than propagated. A unique-violation reaching the
    generic handler becomes a 500 with a correlation id, which tells the user nothing; here it
    becomes a 409 that names the constraint's *resource* - never the constraint itself, since a
    database object name is internal detail and occasionally reveals a column a caller should
    not know about.
    """
    if "tenant_id" not in values and "tenant_id" in model.__table__.columns:
        from speaker_roi_core.context import current_tenant_id

        values = {**values, "tenant_id": current_tenant_id()}
    row = model(**values)  # type: ignore[call-arg]
    if actor_id is not None and hasattr(row, "created_by"):
        row.created_by = actor_id  # type: ignore[attr-defined]
        row.updated_by = actor_id  # type: ignore[attr-defined]

    # A savepoint, not a plain flush. PostgreSQL aborts the whole transaction on a constraint
    # violation, so without one the caller cannot do *anything* afterwards - including writing
    # the audit row that records the refusal - and would have to discard work it had already
    # done in this request. The savepoint confines the damage to the failed INSERT.
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush([row])
    except IntegrityError as exc:
        raise _translate_integrity_error(exc, resource) from exc

    await audit.record(
        session,
        AuditAction.RECORD_CREATED,
        resource_type=resource,
        resource_id=getattr(row, "id", None),
        resource_label=label,
        after_state=audit.snapshot(row, audit_fields),
        status_code=201,
    )
    return row


async def update(
    session: AsyncSession,
    row: Any,
    changes: dict[str, Any],
    *,
    resource: str,
    audit_fields: Sequence[str],
    expected_version: int | None = None,
    label: str | None = None,
    actor_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> Any:
    """Apply ``changes``, enforcing the version token, and audit the before/after pair.

    The version is checked *here* against the loaded row as well as by the ORM at flush time.
    Two checks because they catch different races: this one catches a client that read the
    resource, went to lunch, and submitted - producing a clear 412 naming the current version -
    while the flush-time check catches two requests interleaving inside the same second, where
    no amount of reading beforehand would have helped.
    """
    if expected_version is not None and hasattr(row, "row_version"):
        current = int(row.row_version)
        if current != expected_version:
            raise PreconditionFailedError(
                "This record was changed by someone else since you loaded it.",
                context={"current_version": current, "submitted_version": expected_version},
                remediation="Reload the record and re-apply your change.",
            )

    before = audit.snapshot(row, audit_fields)
    applied = {k: v for k, v in changes.items() if v is not _UNSET}
    if not applied:
        # An empty patch is a no-op, not an error - a client that sends only unchanged fields
        # should not be punished - but it must not write an audit row claiming an edit happened.
        return row
    for key, value in applied.items():
        setattr(row, key, value)
    if actor_id is not None and hasattr(row, "updated_by"):
        row.updated_by = actor_id

    try:
        async with session.begin_nested():
            await session.flush([row])
    except StaleDataError as exc:
        raise PreconditionFailedError(
            "This record was changed by someone else while your update was in flight.",
            remediation="Reload the record and re-apply your change.",
        ) from exc
    except IntegrityError as exc:
        raise _translate_integrity_error(exc, resource) from exc

    await session.refresh(row)
    after = audit.snapshot(row, audit_fields)
    await audit.record(
        session,
        AuditAction.RECORD_UPDATED,
        resource_type=resource,
        resource_id=getattr(row, "id", None),
        resource_label=label,
        before_state=before,
        after_state=after,
        reason=reason,
        status_code=200,
    )
    return row


async def deactivate(
    session: AsyncSession,
    row: Any,
    *,
    resource: str,
    audit_fields: Sequence[str],
    status_field: str = "status",
    inactive_value: Any = None,
    reason: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> Any:
    """Retire a row without deleting it.

    Nothing in this application hard-deletes business data on a user's request. An event that
    was analysed is referenced by an estimate, a published result and an audit trail; deleting
    it would either cascade into that history or leave it dangling, and both are worse than a
    row marked inactive and filtered out of every list. Genuine erasure is a separate, governed
    path with its own approval and its own audit action.
    """
    before = audit.snapshot(row, audit_fields)
    setattr(row, status_field, inactive_value)
    if actor_id is not None and hasattr(row, "updated_by"):
        row.updated_by = actor_id
    await session.flush([row])
    await audit.record(
        session,
        AuditAction.RECORD_DEACTIVATED,
        resource_type=resource,
        resource_id=getattr(row, "id", None),
        before_state=before,
        after_state=audit.snapshot(row, audit_fields),
        reason=reason,
        status_code=200,
    )
    return row


class _Unset:
    """Sentinel for "this field was not present in the PATCH body".

    Needed because ``None`` is a legitimate value for most nullable columns, so a plain
    ``if value is None: skip`` makes it impossible to *clear* a field through the API. Every
    optional patch field defaults to this instead.
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "UNSET"


_UNSET = _Unset()
UNSET: Any = _UNSET


def patch_changes(payload: Any, *fields: str) -> dict[str, Any]:
    """Extract only the fields the client actually sent.

    Uses pydantic's ``model_fields_set`` rather than comparing against defaults, which is the
    only way to distinguish "omitted" from "explicitly set to the default". Comparing to
    defaults means a client cannot set a field *back* to its default, and that failure is
    invisible - the request succeeds and the value does not change.
    """
    sent = getattr(payload, "model_fields_set", set())
    return {name: getattr(payload, name) for name in fields if name in sent}


def _translate_integrity_error(exc: IntegrityError, resource: str) -> Exception:
    """Turn a constraint violation into the right 4xx.

    The constraint name is put in ``internal_detail`` and never in the message. A name like
    ``uq_hcp_tenant_npi`` names a column the caller may not be permitted to know exists, and in
    any case a client cannot act on it - what it can act on is "a record with this identifier
    already exists".
    """
    detail = str(getattr(exc, "orig", exc))
    lowered = detail.lower()
    if "unique" in lowered or "duplicate key" in lowered:
        return ConflictError(
            f"A {resource.replace('_', ' ')} with these details already exists.",
            internal_detail=detail[:500],
            remediation="Check for an existing record before creating a new one.",
        )
    if "foreign key" in lowered:
        return ValidationError(
            "One of the referenced records does not exist or is not available to you.",
            internal_detail=detail[:500],
        )
    if "check constraint" in lowered:
        return ValidationError(
            "The submitted values are not a valid combination.",
            internal_detail=detail[:500],
        )
    if "not-null" in lowered or "null value" in lowered:
        return ValidationError("A required value is missing.", internal_detail=detail[:500])
    # Anything else is genuinely unexpected and should page someone rather than be dressed up
    # as a client error.
    log.error("crud.unmapped_integrity_error", resource=resource, detail=detail[:500])
    return exc


__all__ = [
    "COUNT_CEILING",
    "UNSET",
    "create",
    "deactivate",
    "get_or_404",
    "paginate",
    "patch_changes",
    "update",
]
