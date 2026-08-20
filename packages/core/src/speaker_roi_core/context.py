"""Ambient request context: who is asking, on whose behalf, and under what correlation id.

Held in :class:`~contextvars.ContextVar` rather than threaded through every signature.
That is a real trade-off - implicit state is harder to reason about than a parameter - and
it is made for two reasons that outweigh it here:

**The logger and the database session both need it, and neither is called by the other.**
Every log line carries the tenant and the correlation id; every database transaction sets
``app.tenant_id`` for row-level security. Threading a context object into both means every
intermediate function that calls neither still has to accept and forward it, and the one
place someone forgets is where a log line loses its tenant or a query loses its policy.

**``ContextVar`` is correct under ``asyncio``.** Each task gets a copy at creation, so two
concurrent requests cannot see each other's tenant, and a background task started from a
request inherits the context it was spawned in rather than racing for it.

The dangerous failure mode of ambient state is *leakage between requests* - request B
reading request A's tenant because the middleware forgot to reset. Two things guard it:
:func:`request_context` is a context manager that always resets its token, and
:func:`current_tenant_id` raises rather than returning ``None`` when no tenant is bound, so
a query that needs a tenant cannot silently run without one.

plan.md §15: the tenant, role and vendor scope in here are resolved **server-side from the
session**. Nothing in this module accepts a scope from request data; the middleware that
populates it reads the session record, and the setters are deliberately not exported for
route handlers to call.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Self

from speaker_roi_core.errors import TenantScopeRequiredError

# ---------------------------------------------------------------------------
# The context variables themselves. Private: everything reaches them through the
# accessors below, so that "who may set this" is answerable by grepping one file.
# ---------------------------------------------------------------------------

_context: ContextVar[RequestContext | None] = ContextVar("speaker_roi_context", default=None)


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated identity, resolved from the session.

    Frozen, because a permission check that can be mutated after it is made is not a
    permission check. A route that needs a different scope re-enters the context manager
    with a new principal rather than editing this one - which also means the change is
    visible in the log line for the nested scope.

    ``permissions`` is the flattened, resolved set - roles have already been expanded.
    Route guards test membership here rather than reasoning about role hierarchies at
    request time, so the hierarchy lives in one place and cannot be interpreted two ways.
    """

    user_id: uuid.UUID
    email: str
    #: Resolved role codes, e.g. ``("TENANT_ADMIN",)``. Informational for logs and the UI.
    roles: frozenset[str] = frozenset()
    #: Flattened permission codes. This is what authorization actually reads.
    permissions: frozenset[str] = frozenset()
    #: Brand ids this principal may see, or ``None`` for "every brand in the tenant".
    #: ``None`` and the empty set are meaningfully different: unrestricted versus
    #: restricted to nothing. Collapsing them is how a scoped user sees everything.
    brand_scope: frozenset[uuid.UUID] | None = None
    #: Set only for an external vendor contributor. plan.md §15 forbids exposing
    #: prescription outcomes, ROI or another vendor's submissions to one, so this being
    #: non-null is a hard filter in the service layer, not a UI preference.
    vendor_id: uuid.UUID | None = None
    #: When credentials were last presented. Drives the re-auth window for sensitive
    #: operations; ``None`` means the session was established by a means that cannot
    #: satisfy re-auth at all (an API token), so those operations are refused.
    authenticated_at_epoch: float | None = None
    mfa_satisfied: bool = False
    session_id: uuid.UUID | None = None
    is_platform_admin: bool = False
    is_service_account: bool = False

    def has(self, permission: str) -> bool:
        """Exact permission membership. Platform admin is *not* an implicit bypass.

        A wildcard superuser check here would mean a platform administrator silently
        satisfies every future permission, including ones added later for reasons that
        should not apply to them - reading a tenant's prescribing data, for instance,
        which is a support-access decision with its own audit requirement rather than a
        consequence of being an admin.
        """
        return permission in self.permissions

    def has_any(self, *permissions: str) -> bool:
        return any(p in self.permissions for p in permissions)

    def may_see_brand(self, brand_id: uuid.UUID) -> bool:
        return self.brand_scope is None or brand_id in self.brand_scope

    @property
    def is_vendor(self) -> bool:
        return self.vendor_id is not None

    def redacted(self) -> dict[str, Any]:
        """Log-safe identity. The email address is a personal identifier, so it goes out
        as a domain only - enough to tell an internal user from a customer during an
        incident, not enough to be a contact list in a log aggregator."""
        domain = self.email.rpartition("@")[2] if "@" in self.email else "?"
        return {
            "user_id": str(self.user_id),
            "user_domain": domain,
            "roles": sorted(self.roles),
            "is_vendor": self.is_vendor,
            "is_platform_admin": self.is_platform_admin,
            "is_service_account": self.is_service_account,
        }


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Everything ambient about the unit of work in flight.

    Covers an HTTP request, a Celery task and a CLI invocation alike. The worker is the
    reason this is not called ``HttpContext``: an analysis job needs the same tenant
    binding and the same correlation id as the request that enqueued it, and a job that
    ran without a tenant would either see nothing (under RLS) or everything (without it).
    """

    #: Stable across the whole causal chain, including into enqueued jobs, so a user's
    #: "it failed" maps to every log line the request and its jobs produced.
    correlation_id: str
    #: New for each hop. Distinguishes the request from the three jobs it spawned when
    #: they share a correlation id.
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    tenant_id: uuid.UUID | None = None
    principal: Principal | None = None
    #: ``api`` | ``worker`` | ``cli`` | ``test``. Drives which log sink and which timeout
    #: budget applies, and makes "why is an analysis running inside a request" answerable.
    source: str = "api"
    #: HTTP route template (``/api/v1/events/{event_id}``) rather than the concrete path,
    #: so metrics do not explode into one label value per identifier.
    route: str | None = None
    method: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    #: Present when the caller sent ``Idempotency-Key``.
    idempotency_key: str | None = None
    #: Free-form, log-only. Never serialised into a response.
    extra: Mapping[str, Any] = field(default_factory=dict)

    def with_(self, **changes: Any) -> Self:
        """A shallow copy with fields replaced.

        Used by the middleware, which builds the context in stages: correlation id and
        route before authentication, then the principal and tenant once the session has
        been read. Building it in one shot would mean the pre-auth failures - a malformed
        cookie, a rate limit - log without a correlation id, which is exactly when one is
        most useful.
        """
        merged = {
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "principal": self.principal,
            "source": self.source,
            "route": self.route,
            "method": self.method,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "idempotency_key": self.idempotency_key,
            "extra": self.extra,
        }
        merged.update(changes)
        return type(self)(**merged)

    def log_fields(self) -> dict[str, Any]:
        """The bound fields every log line in this context carries.

        ``None`` values are dropped rather than emitted as nulls: a log search for
        ``tenant_id`` should match lines that have one, and a pre-authentication line
        genuinely has no tenant.
        """
        fields: dict[str, Any] = {
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "source": self.source,
        }
        if self.tenant_id:
            fields["tenant_id"] = str(self.tenant_id)
        if self.route:
            fields["route"] = self.route
        if self.method:
            fields["method"] = self.method
        if self.client_ip:
            fields["client_ip"] = self.client_ip
        if self.idempotency_key:
            fields["idempotency_key"] = self.idempotency_key
        if self.principal is not None:
            fields.update(self.principal.redacted())
        fields.update(self.extra)
        return fields

    def to_headers(self) -> dict[str, str]:
        """Propagation for an outbound call or an enqueued job payload.

        Only the correlation id and the tenant travel. The principal deliberately does
        not: a job that carried a serialised permission set would be authorizing itself
        from data in a queue message, and a queue message is not a trust boundary the
        session store can vouch for. The worker re-resolves the principal from the
        persisted job record instead.
        """
        headers = {"X-Correlation-ID": self.correlation_id}
        if self.tenant_id:
            headers["X-Tenant-ID"] = str(self.tenant_id)
        return headers


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def new_correlation_id() -> str:
    """A fresh correlation id.

    Hex rather than the dashed UUID form: it survives being pasted into a log query, a
    URL and a Slack message without anyone having to think about escaping.
    """
    return uuid.uuid4().hex


def current_context() -> RequestContext | None:
    """The bound context, or ``None`` outside any request.

    Returns ``None`` rather than raising, because the logger calls this on every line and
    a log statement during startup - before any request exists - must not explode.
    """
    return _context.get()


def require_context() -> RequestContext:
    """The bound context, raising if there is none.

    For code that genuinely cannot proceed without one, such as writing an audit event:
    an audit row with no actor and no correlation id is not an audit row.
    """
    ctx = _context.get()
    if ctx is None:
        raise RuntimeError(
            "no request context is bound; this code path must run inside "
            "request_context(...). If it is a background task, bind the context that "
            "enqueued it rather than running without one."
        )
    return ctx


def current_tenant_id() -> uuid.UUID:
    """The bound tenant, raising :class:`TenantScopeRequiredError` if absent.

    Raising is the whole point. This is called by the database session to set
    ``app.tenant_id`` before a tenant-scoped query, and the two silent alternatives are
    both unacceptable: under row-level security an unset GUC returns zero rows, which
    presents as "your data disappeared", and if a policy is ever missing it returns every
    tenant's rows, which is a breach. A loud refusal is the only safe default.
    """
    ctx = _context.get()
    if ctx is None or ctx.tenant_id is None:
        raise TenantScopeRequiredError()
    return ctx.tenant_id


def current_tenant_id_or_none() -> uuid.UUID | None:
    """For the handful of legitimately cross-tenant paths.

    Platform administration, the login endpoint (which resolves a tenant *from* the
    credentials) and migrations. Deliberately named so that its use stands out in review.
    """
    ctx = _context.get()
    return ctx.tenant_id if ctx else None


def current_principal() -> Principal | None:
    ctx = _context.get()
    return ctx.principal if ctx else None


def require_principal() -> Principal:
    principal = current_principal()
    if principal is None:
        # Not NotAuthenticatedError: reaching here means a route that requires a
        # principal was wired without the authentication dependency, which is a
        # programming error and must not be reported to the caller as a 401 they could
        # fix by signing in.
        raise RuntimeError(
            "no principal is bound; the route is missing its authentication dependency"
        )
    return principal


def current_correlation_id() -> str | None:
    ctx = _context.get()
    return ctx.correlation_id if ctx else None


@contextlib.contextmanager
def request_context(ctx: RequestContext) -> Iterator[RequestContext]:
    """Bind a context for the duration of the block, then restore what was there.

    Restoring the *previous token* rather than setting ``None`` on exit is what makes
    nesting safe: an authenticated request that opens an inner unscoped block for a
    platform-admin lookup gets its own context back afterwards, instead of losing it.
    """
    token: Token[RequestContext | None] = _context.set(ctx)
    try:
        yield ctx
    finally:
        _context.reset(token)


@contextlib.contextmanager
def bind(**changes: Any) -> Iterator[RequestContext]:
    """Amend the bound context for a block.

    ``with bind(tenant_id=t): ...`` for the middleware stage that resolves the session,
    and ``with bind(extra={"analysis_id": ...}): ...`` to tag every log line inside a
    unit of work without passing the id to each of them.
    """
    ctx = require_context()
    if "extra" in changes:
        changes["extra"] = {**ctx.extra, **changes["extra"]}
    with request_context(ctx.with_(**changes)) as bound:
        yield bound


@contextlib.contextmanager
def system_context(
    *,
    source: str = "worker",
    tenant_id: uuid.UUID | None = None,
    correlation_id: str | None = None,
    **extra: Any,
) -> Iterator[RequestContext]:
    """A context for work with no human caller: a scheduled job, a migration, the CLI.

    No principal, on purpose. Anything a system context does is attributed in the audit
    trail to the system actor, which is a distinct and searchable actor kind - so
    "who published this" never resolves to a nightly job wearing a user's identity.
    """
    ctx = RequestContext(
        correlation_id=correlation_id or new_correlation_id(),
        tenant_id=tenant_id,
        source=source,
        extra=extra,
    )
    with request_context(ctx) as bound:
        yield bound


def assert_brand_access(brand_ids: Sequence[uuid.UUID]) -> None:
    """Refuse a request that names brands the principal is not scoped to.

    Checked here and *again* in the query predicate, which is not redundancy for its own
    sake: this check produces a clear 403 naming the problem, while the predicate is the
    guarantee that holds even if a future route forgets to call this. Defence in depth
    only counts when the outer layer is the one that can be forgotten.
    """
    principal = current_principal()
    if principal is None or principal.brand_scope is None:
        return
    denied = [str(b) for b in brand_ids if b not in principal.brand_scope]
    if denied:
        from speaker_roi_core.errors import ForbiddenError

        raise ForbiddenError(
            "You do not have access to one or more of the selected brands.",
            context={"denied_brand_count": len(denied)},
        )


__all__ = [
    "Principal",
    "RequestContext",
    "assert_brand_access",
    "bind",
    "current_context",
    "current_correlation_id",
    "current_principal",
    "current_tenant_id",
    "current_tenant_id_or_none",
    "new_correlation_id",
    "request_context",
    "require_context",
    "require_principal",
    "system_context",
]
