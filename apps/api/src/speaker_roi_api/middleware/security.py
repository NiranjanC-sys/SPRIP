"""Security response headers, and a hard cap on request body size.

Both are cheap, both are the kind of thing a penetration test finds, and both are easier to get
right once here than to remember at every response.

The Content-Security-Policy is the part worth reading. It is strict - no ``unsafe-inline``, no
``unsafe-eval``, no wildcard hosts - which means the frontend must not use inline event handlers
or inline ``<style>`` attributes. That constraint is deliberate and the frontend is built to it:
a CSP with ``unsafe-inline`` in the script directive provides essentially no XSS protection,
which makes it worse than none, because it looks like a control in an audit.

``frame-ancestors 'none'`` rather than ``X-Frame-Options``. The old header is not in any
standard and is inconsistently implemented for the ``ALLOW-FROM`` case; both are sent, because
the deployment may sit behind something that only understands the old one.

The body limit is enforced against the ``Content-Length`` header *and* against the bytes
actually read, because the header is client-supplied and a chunked request has none at all.
Checking only the header is the common mistake, and it means a chunked upload with no
declared length bypasses the limit entirely.
"""

from __future__ import annotations

import orjson
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from speaker_roi_core.errors import AppError, ErrorCode

#: Directives shared by every response. ``connect-src 'self'`` is what stops an injected script
#: exfiltrating to an attacker's host even if it manages to execute.
_CSP = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        # Google Fonts is the one external origin the design system uses. Named explicitly
        # rather than allowed by wildcard, so a compromised CDN elsewhere gains nothing.
        "style-src 'self' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com data:",
        # data: for the chart library's canvas exports and the MFA enrolment QR code, both of
        # which are generated in-page rather than fetched.
        "img-src 'self' data: blob:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        # Blocks the legacy plugin and mixed-content paths that predate CSP.
        "upgrade-insecure-requests",
    )
)

#: Sent on every response, whatever its status. An error page is as good a place to plant a
#: script as a successful one.
BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Denies the ambient capabilities this application has no use for. A feature that is never
    # used cannot be abused by injected script.
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
        "microphone=(), payment=(), usb=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    # Cached authenticated JSON in a shared proxy is a cross-user disclosure. Individual
    # endpoints that serve genuinely public, cacheable content override this.
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware:
    """Attach the security headers, and HSTS when the deployment terminates TLS.

    Written against the raw ASGI interface rather than ``BaseHTTPMiddleware`` because that
    class buffers the response body to support its ``call_next`` abstraction, which would
    undo the streaming used by the export download endpoint. Header mutation does not need
    the body, so there is no reason to pay for it.
    """

    def __init__(self, app: ASGIApp, *, hsts: bool = False, csp: str | None = None) -> None:
        self._app = app
        self._hsts = hsts
        self._csp = csp if csp is not None else _CSP

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in BASE_HEADERS.items():
                    headers.setdefault(name, value)
                headers.setdefault("Content-Security-Policy", self._csp)
                if self._hsts:
                    # Two years, subdomains included, preload-eligible. Only sent when the
                    # deployment is genuinely HTTPS-only: sending it from a local HTTP server
                    # would pin the developer's browser to https://localhost for two years.
                    headers.setdefault(
                        "Strict-Transport-Security",
                        "max-age=63072000; includeSubDomains; preload",
                    )
            await send(message)

        await self._app(scope, receive, send_with_headers)


class RequestTooLargeError(AppError):
    """413. A body larger than the endpoint's limit, refused before it is buffered."""

    status_code = 413
    code = ErrorCode.PAYLOAD_TOO_LARGE


class BodySizeLimitMiddleware:
    """Refuse an oversized request body, counting bytes rather than trusting the header.

    Two limits, because the two kinds of request have genuinely different needs: a JSON
    request body has no business exceeding a megabyte, while a monthly prescription extract
    is legitimately hundreds. Applying the upload limit everywhere would let an attacker
    send a 500MB JSON document to any endpoint and have it parsed.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        upload_max_body_bytes: int,
        upload_path_prefixes: tuple[str, ...] = ("/api/v1/uploads",),
    ) -> None:
        self._app = app
        self._max = max_body_bytes
        self._upload_max = upload_max_body_bytes
        self._upload_prefixes = upload_path_prefixes

    def _limit_for(self, path: str) -> int:
        return (
            self._upload_max
            if any(path.startswith(prefix) for prefix in self._upload_prefixes)
            else self._max
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        limit = self._limit_for(scope.get("path", ""))
        declared = Headers(scope=scope).get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            # Refused without reading the body. The connection is closed by the response,
            # so the client stops sending - which is the point of checking the header at
            # all: it saves transferring 500MB before refusing it.
            await _refuse(send, limit)
            return

        counted = 0
        exceeded = False

        async def receive_counting() -> Message:
            nonlocal counted, exceeded
            message = await receive()
            if message["type"] == "http.request":
                counted += len(message.get("body", b""))
                if counted > limit:
                    exceeded = True
                    # An empty final chunk rather than the real bytes: the handler must not
                    # receive a truncated body it might treat as complete. It sees an
                    # abruptly ended stream, and the guard below turns that into a 413.
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def send_guarded(message: Message) -> None:
            if exceeded and message["type"] == "http.response.start":
                await _refuse(send, limit)
                return
            if exceeded and message["type"] == "http.response.body":
                return
            await send(message)

        await self._app(scope, receive_counting, send_guarded)


async def _refuse(send: Send, limit: int) -> None:
    body = orjson.dumps(
        {
            "error": {
                "code": str(ErrorCode.PAYLOAD_TOO_LARGE),
                "message": f"the request body exceeds the {limit // (1024 * 1024)} MiB limit",
                "remediation": "split the file into smaller batches, or use the chunked "
                "upload endpoint for large data files",
            }
        }
    )
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


__all__ = [
    "BASE_HEADERS",
    "BodySizeLimitMiddleware",
    "RequestTooLargeError",
    "SecurityHeadersMiddleware",
]
