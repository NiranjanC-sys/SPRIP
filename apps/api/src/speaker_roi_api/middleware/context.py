"""Bind a :class:`RequestContext` for the lifetime of every request.

This is the first middleware in the stack and everything else depends on it: the logger reads
the correlation id from the ambient context, the database session reads the tenant from it, and
the audit writer refuses to write a row without one. It runs before authentication, so the
context it binds carries no principal - the authentication dependency amends it later with
:func:`speaker_roi_core.context.bind`.

The route *template* is captured rather than the path, and that distinction is load-bearing
twice over. As a Prometheus label, ``/events/{event_id}`` is one time series while
``/events/<uuid>`` is one per event and will exhaust the metrics backend. As a log field, the
template is what makes "which endpoint is slow" answerable by grouping.

Starlette only resolves the matched route *after* the request has been routed, which is after
this middleware has already run - so the template is read back on the way out, from
``request.scope``, and the log line is emitted there rather than on entry.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from speaker_roi_core.context import RequestContext, new_correlation_id, request_context

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

#: Header a caller may use to join their own trace to ours. Accepted, but never trusted as a
#: value: it is echoed into logs, so it is validated to a conservative shape first. An
#: unvalidated header here is a log-injection vector - a newline in it can forge a log line.
CORRELATION_HEADER = "X-Correlation-Id"
REQUEST_ID_HEADER = "X-Request-Id"

_SAFE_CORRELATION = re.compile(r"\A[A-Za-z0-9_.:-]{8,64}\Z")

#: Trusted proxy handling. ``X-Forwarded-For`` is client-controlled unless a proxy we operate
#: overwrote it, so it is only read when the deployment says so. Reading it unconditionally
#: means every rate limit and every lockout is bypassable by setting a header.
FORWARDED_FOR_HEADER = "X-Forwarded-For"


def _clean_correlation_id(raw: str | None) -> str:
    """An inbound correlation id if it is safe to echo, otherwise a fresh one."""
    if raw and _SAFE_CORRELATION.match(raw):
        return raw
    return new_correlation_id()


def client_ip(request: Request, *, trust_forwarded: bool) -> str | None:
    """The caller's address, honouring the proxy header only when configured to.

    The *leftmost* entry is taken when trusting, because that is the original client and the
    entries to its right are the proxies. It is also the one an attacker can forge, which is
    exactly why ``trust_forwarded`` exists rather than a heuristic: whether the header is
    trustworthy is a fact about the deployment topology, and no amount of parsing can
    determine it from inside the process.
    """
    if trust_forwarded:
        forwarded = request.headers.get(FORWARDED_FOR_HEADER)
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    return request.client.host if request.client else None


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind context, echo the correlation id, and record the resolved route template."""

    def __init__(self, app: object, *, trust_forwarded_for: bool = False) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._trust_forwarded_for = trust_forwarded_for

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = _clean_correlation_id(request.headers.get(CORRELATION_HEADER))
        ctx = RequestContext(
            correlation_id=correlation_id,
            request_id=uuid.uuid4().hex,
            source="api",
            method=request.method,
            # Provisional. Replaced by the matched template below, once routing has run.
            route=request.url.path,
            client_ip=client_ip(request, trust_forwarded=self._trust_forwarded_for),
            user_agent=request.headers.get("user-agent"),
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        with request_context(ctx):
            # Handed to downstream code that has a Request but not the ambient context -
            # notably the exception handlers, which run outside this block in Starlette's
            # own error middleware and so cannot read the context var.
            request.state.context = ctx
            response = await call_next(request)
            resolved = request.scope.get("route")
            template = getattr(resolved, "path", None)
            if template:
                # Mutating state rather than rebinding: the context object is frozen and the
                # request is over, so nothing downstream reads it - but the access logger and
                # the metrics middleware, which sit outside this one, need the template.
                request.state.route_template = template
            response.headers[CORRELATION_HEADER] = correlation_id
            response.headers[REQUEST_ID_HEADER] = ctx.request_id or ""
            return response


def route_template(request: Request) -> str:
    """The matched route template, falling back to a bounded placeholder.

    The fallback matters: a request that 404s never matches a route, so there is no template,
    and using the raw path as the metric label would let an unauthenticated scanner create one
    time series per URL it probes. ``__unmatched__`` is one label value for all of them.
    """
    template = getattr(request.state, "route_template", None)
    if template:
        return str(template)
    resolved = request.scope.get("route")
    return str(getattr(resolved, "path", None) or "__unmatched__")


__all__ = [
    "CORRELATION_HEADER",
    "REQUEST_ID_HEADER",
    "RequestContextMiddleware",
    "client_ip",
    "route_template",
]
