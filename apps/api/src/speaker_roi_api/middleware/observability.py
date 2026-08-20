"""One access log line and one set of metrics per request.

Both live in the same middleware because they measure the same thing and must agree. Two
middlewares timing the same request produce two slightly different durations, and the first
time an engineer notices that the log says 900ms and the dashboard says 1.2s they stop trusting
both.

The log line is emitted on the way *out*, not on the way in. An entry-and-exit pair doubles the
log volume to say nothing the exit line does not already carry, and the fields that matter -
status, duration, response size - only exist at the end. The exception is a request that dies
mid-flight: that is caught here and logged with its exception, because otherwise a client
disconnect during a slow analysis query leaves no trace at all.

What is deliberately absent: the query string, the request body, and any header other than the
bounded few. plan.md §15 forbids logging free text and identifiers that could carry patient
data, and a query string is the easiest place for one to arrive - ``?email=...`` in a URL is
personal data in a log file with a two-year retention.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

from speaker_roi_api.middleware.context import route_template
from speaker_roi_core import metrics
from speaker_roi_core.context import current_context
from speaker_roi_core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

log = get_logger("speaker_roi_api.access")

#: Requests slower than this are logged at warning. Chosen to sit above the p99 of every
#: interactive endpoint and below the point a user gives up, so the warning stream is a list of
#: things worth looking at rather than a second copy of the access log.
SLOW_REQUEST_SECONDS = 2.0

#: Paths excluded from the access log. Kubernetes probes these every few seconds, and their
#: successful responses are pure noise; their *failures* still appear, because the status is
#: checked before the exclusion.
_QUIET_PATHS = frozenset({"/healthz", "/readyz", "/livez", "/metrics"})


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Time the request, count it, and log the outcome exactly once."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        metrics.http_in_flight.inc()
        try:
            response = await call_next(request)
        except Exception:
            # Caught only to produce the record, then re-raised. A request that dies here
            # produced no response, so without this branch it is absent from both the access
            # log and the metrics - and "the endpoint that crashes has no latency data" is
            # the worst possible gap in an incident.
            self._record(request, status=500, elapsed=time.perf_counter() - started, failed=True)
            raise
        else:
            self._record(
                request,
                status=response.status_code,
                elapsed=time.perf_counter() - started,
                failed=False,
            )
            return response
        finally:
            # In the finally so it is decremented on the success path, the exception path and
            # a cancellation alike. A gauge that leaks on one of the three drifts upward all
            # day and eventually reads as permanent saturation.
            metrics.http_in_flight.dec()

    def _record(self, request: Request, *, status: int, elapsed: float, failed: bool) -> None:
        template = route_template(request)
        method = request.method
        metrics.http_requests.labels(route=template, method=method, status=str(status)).inc()
        metrics.http_latency.labels(route=template, method=method).observe(elapsed)

        if template in _QUIET_PATHS and status < 400 and not failed:
            return

        ctx = current_context()
        fields = {
            "route": template,
            "method": method,
            "status": status,
            "duration_ms": round(elapsed * 1000, 1),
            **(ctx.log_fields() if ctx else {}),
        }
        if failed:
            log.exception("http.request_failed", **fields)
        elif status >= 500:
            log.error("http.request", **fields)
        elif status >= 400 or elapsed >= SLOW_REQUEST_SECONDS:
            log.warning("http.request", **fields)
        else:
            log.info("http.request", **fields)


__all__ = ["SLOW_REQUEST_SECONDS", "ObservabilityMiddleware"]
