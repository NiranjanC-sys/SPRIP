"""Writing the audit trail.

One function, called from the service layer rather than from a middleware. A middleware that
audited every request automatically would look tidier and would be wrong twice over: it cannot
know *what* changed - the before and after state that makes an audit entry useful rather than a
duplicate access log - and it would record a row for every read, burying the twelve interesting
events of the day under four hundred thousand.

Three rules, all from plan.md §15, all enforced here so no call site can get them wrong.

**States are whitelisted, never dumped.** :func:`snapshot` takes an explicit field list. A
``model_dump()`` of an ORM row would put an email address, a password hash and a vendor's
submitted free text into a table with a seven-year retention.

**Identifiers are hashed, not stored.** An IP address is personal data, and the audit use case -
spotting one source hammering an endpoint - is served just as well by a stable keyed hash.

**A failed write is loud but not fatal.** An audit insert failing must not roll back the
business transaction it describes; the trail's own integrity is protected by the grants (the
application role holds INSERT and SELECT and nothing else) and by an alert on this log event,
not by taking the feature offline. The exception is the security-relevant subset - authorization
denials and publication - where ``critical=True`` makes the failure fatal, because an
unrecorded permission denial is exactly the event an attacker wants unrecorded.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from speaker_roi_api.security.tokens import hash_pii
from speaker_roi_core.context import current_context
from speaker_roi_core.enums import AuditAction, AuditOutcome
from speaker_roi_core.errors import InternalError
from speaker_roi_core.logging import get_logger
from speaker_roi_core.models import AuditEvent

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

#: Actions whose absence from the trail is itself a security event, so a failed insert raises.
_CRITICAL: frozenset[AuditAction] = frozenset(
    {
        AuditAction.PERMISSION_DENIED,
        AuditAction.LOGIN_FAILED,
        AuditAction.MEMBERSHIP_CHANGED,
        AuditAction.VENDOR_GRANT_GRANTED,
        AuditAction.VENDOR_GRANT_REVOKED,
        AuditAction.RESULT_PUBLISHED,
        AuditAction.MODEL_ACTIVATED,
        AuditAction.FINANCE_ASSUMPTION_APPROVED,
        AuditAction.OBJECT_DOWNLOAD_AUTHORIZED,
        AuditAction.RETENTION_DELETION_EXECUTED,
    }
)

#: Truncation limit for the free-text-adjacent fields that are allowed at all. A label is for
#: recognising a record in a list, so three hundred characters is generous; an unbounded one is
#: a place for a whole prescription note to arrive.
_LABEL_MAX = 300


def snapshot(obj: object, fields: Sequence[str]) -> dict[str, Any]:
    """Extract exactly ``fields`` from ``obj``, coerced to JSON-safe scalars.

    The explicit field list is the control. Callers pass the columns whose change is
    meaningful to a reviewer - a status, an amount, a role - and nothing else reaches the
    trail, so adding a sensitive column to a model cannot retroactively start auditing it.
    """
    out: dict[str, Any] = {}
    for name in fields:
        value = getattr(obj, name, None)
        if value is None:
            out[name] = None
        elif isinstance(value, uuid.UUID):
            out[name] = str(value)
        elif isinstance(value, str):
            out[name] = value[:_LABEL_MAX]
        elif isinstance(value, bool | int | float):
            out[name] = value
        else:
            # Dates, decimals, enums. ``str`` rather than a type-specific formatter because
            # this value is read by a human in a diff view, not parsed.
            out[name] = str(value)[:_LABEL_MAX]
    return out


def changed_fields(
    before: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> list[str] | None:
    """Which whitelisted fields actually differ.

    Stored alongside the two states so a reviewer scanning a hundred entries can see *what*
    changed without diffing two JSON blobs, and so "somebody touched this record but changed
    nothing" is distinguishable from a real edit.
    """
    if before is None or after is None:
        return None
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k) != after.get(k)) or []


_UNSET = object()


async def record(
    session: AsyncSession,
    action: AuditAction,
    *,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    resource_label: str | None = None,
    before_state: Mapping[str, Any] | None = None,
    after_state: Mapping[str, Any] | None = None,
    reason: str | None = None,
    tenant_id: uuid.UUID | object | None = _UNSET,
    actor_user_id: uuid.UUID | None = None,
    actor_label: str | None = None,
    status_code: int | None = None,
) -> None:
    """Append one audit row, inside the caller's transaction.

    Inside the caller's transaction on purpose: the audit entry and the change it describes
    commit or roll back together. A separate transaction would let a rolled-back edit leave an
    audit row claiming it happened, which is worse than no row - a trail that records things
    that did not occur cannot be used as evidence for the ones that did.

    Almost every argument defaults from the ambient context, so a call site names only what is
    specific to it. That is not brevity for its own sake: the correlation id, the route and the
    actor are the fields a caller is most likely to omit or to pass inconsistently, and reading
    them from one place makes every row joinable to the request that produced it.
    """
    ctx = current_context()
    principal = ctx.principal if ctx else None

    event = AuditEvent(
        tenant_id=tenant_id if tenant_id is not _UNSET else (ctx.tenant_id if ctx else None),
        action=action,
        outcome=outcome,
        actor_user_id=actor_user_id
        if actor_user_id is not None
        else (principal.user_id if principal else None),
        # The domain, not the address. Enough to tell an internal actor from a customer during
        # an investigation; not a contact list sitting in a seven-year table.
        actor_label=_actor_label(actor_label, principal),
        actor_role=_actor_role(principal),
        actor_kind=_actor_kind(principal),
        resource_type=resource_type,
        resource_id=resource_id,
        resource_label=(resource_label or None) and resource_label[:_LABEL_MAX],
        before_state=dict(before_state) if before_state is not None else None,
        after_state=dict(after_state) if after_state is not None else None,
        changed_fields=changed_fields(before_state, after_state),
        reason=(reason or None) and reason[:200],
        correlation_id=ctx.correlation_id if ctx else None,
        request_id=ctx.request_id if ctx else None,
        session_id=principal.session_id if principal else None,
        ip_hash=hash_pii(ctx.client_ip) if ctx and ctx.client_ip else None,
        user_agent_hash=hash_pii(ctx.user_agent) if ctx and ctx.user_agent else None,
        http_method=ctx.method if ctx else None,
        route=ctx.route if ctx else None,
        status_code=status_code,
    )
    session.add(event)
    try:
        # Wrapped in a SAVEPOINT so a failed INSERT does not poison the caller's transaction.
        # PostgreSQL aborts the entire transaction on any error; without the savepoint the
        # caller's subsequent statements would all fail with "current transaction is aborted",
        # which turns a non-critical audit failure into a 500.
        async with session.begin_nested():
            await session.flush([event])
    except Exception as exc:
        log.error(
            "audit.write_failed",
            audit_action=str(action),
            outcome=str(outcome),
            error=type(exc).__name__,
            critical=action in _CRITICAL,
        )
        if action in _CRITICAL:
            raise InternalError(
                "The action could not be completed because it could not be recorded.",
                internal_detail=f"audit insert failed for {action}: {type(exc).__name__}",
                remediation="Retry. If this persists, the audit store needs attention "
                "before this action can proceed.",
            ) from exc


def _actor_label(explicit: str | None, principal: Any) -> str | None:
    if explicit:
        return explicit[:200]
    if principal is None:
        return None
    email = getattr(principal, "email", "") or ""
    domain = email.rpartition("@")[2] if "@" in email else None
    return f"@{domain}" if domain else None


def _actor_role(principal: Any) -> str | None:
    """One role, from a principal that may hold several.

    Sorted and joined would exceed the column; picking one arbitrarily would be misleading.
    The first alphabetically is recorded with the count, which is honest about being a
    summary - and the full set is recoverable from the membership table as of that timestamp.
    """
    if principal is None:
        return None
    roles: Iterable[str] = sorted(getattr(principal, "roles", ()) or ())
    listed = list(roles)
    if not listed:
        return None
    if len(listed) == 1:
        return listed[0][:40]
    return f"{listed[0]}+{len(listed) - 1}"[:40]


def _actor_kind(principal: Any) -> str:
    if principal is None:
        return "SYSTEM"
    if getattr(principal, "is_service_account", False):
        return "SERVICE"
    if getattr(principal, "is_vendor", False):
        return "VENDOR"
    if getattr(principal, "is_platform_admin", False):
        return "PLATFORM"
    return "USER"


async def record_denial(
    session: AsyncSession, *, permission: str, resource_type: str | None = None
) -> None:
    """A permission denial, recorded as its own action.

    Separate from a generic failure because the aggregate is the signal: one denial is a user
    clicking something they cannot use, and forty in a minute from one principal is either a
    broken frontend or an enumeration attempt, and both are worth an alert.
    """
    await record(
        session,
        AuditAction.PERMISSION_DENIED,
        outcome=AuditOutcome.DENIED,
        resource_type=resource_type,
        reason=f"missing permission: {permission}",
        status_code=403,
    )


__all__ = ["changed_fields", "record", "record_denial", "snapshot"]
