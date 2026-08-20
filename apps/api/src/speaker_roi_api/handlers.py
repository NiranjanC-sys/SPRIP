"""Exception handlers: every failure leaves through here, in one shape.

The contract is that a client can always distinguish success from failure by the presence of an
``error`` key, and can always act on ``error.code`` without parsing prose. That only holds if
*nothing* escapes to Starlette's default handler, which emits ``{"detail": ...}`` and would give
callers a second error shape to handle. So there are four handlers, and the last one catches
``Exception``.

Two details are worth defending.

**Pydantic's validation errors are rewritten rather than passed through.** FastAPI's default 422
body includes the submitted value under ``input``, which is how a rejected upload row ends up in
a log aggregator - plan.md §15 forbids exactly that. The rewrite keeps the location and the
message and drops the value.

**The catch-all logs the exception and returns a correlation id, not the message.** An
unhandled exception's text routinely contains a connection string, a SQL fragment with literal
values, or a file path. The caller gets "something went wrong, quote this id"; the id is what
turns that into a five-second log query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import orjson
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import Response

from speaker_roi_core import metrics
from speaker_roi_core.context import current_context
from speaker_roi_core.errors import AppError, ErrorCode, FieldError, ValidationError
from speaker_roi_core.logging import get_logger

if TYPE_CHECKING:
    from starlette.requests import Request

log = get_logger(__name__)


class ORJSONResponse(Response):
    """JSON responses via orjson.

    Chosen for a specific reason rather than for benchmarks: it serialises ``datetime``,
    ``UUID`` and ``Decimal`` natively and *consistently*. The stdlib encoder needs a custom
    ``default`` for each, and a custom default is a place where one endpoint formats a
    timestamp differently from another - which the frontend then has to defend against.
    """

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(
            content,
            option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_UTC_Z,
        )


def _correlation_id(request: Request) -> str | None:
    """The request's correlation id, from the context if bound or the request state if not.

    Both are consulted because exception handlers run *outside* the context-binding
    middleware in Starlette's stack, so the context var may already have been reset by the
    time a handler executes. The middleware also stashes the context on ``request.state``
    precisely for this case.
    """
    ctx = current_context()
    if ctx is not None:
        return ctx.correlation_id
    stashed = getattr(request.state, "context", None)
    return getattr(stashed, "correlation_id", None)


def _response(
    request: Request, error: AppError, *, headers: dict[str, str] | None = None
) -> ORJSONResponse:
    correlation_id = _correlation_id(request)
    metrics.record_app_error(str(error.code), error.status_code)

    fields = {"error_code": str(error.code), "status": error.status_code, **error.log_fields()}
    if error.alertable or error.status_code >= 500:
        log.error("api.error", **fields)
    else:
        # Client errors at info. A 404 or a 403 is a normal event in a healthy system, and
        # logging them at warning trains everyone to ignore warnings.
        log.info("api.error", **fields)

    merged = dict(headers or {})
    if error.retry_after_seconds is not None:
        merged["Retry-After"] = str(error.retry_after_seconds)
    if error.code is ErrorCode.NOT_AUTHENTICATED:
        # RFC 7235 requires a challenge on a 401. ``Bearer`` rather than ``Cookie`` because
        # the browser flow must not trigger the native basic-auth dialog, which cannot be
        # dismissed and looks like a broken site.
        merged["WWW-Authenticate"] = 'Bearer realm="speaker-roi"'
    return ORJSONResponse(
        content=error.to_envelope(correlation_id=correlation_id),
        status_code=error.status_code,
        headers=merged,
    )


async def handle_app_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, AppError)
    return _response(request, exc)


async def handle_validation_error(request: Request, exc: Exception) -> Response:
    """Rewrite FastAPI's 422 into the standard envelope, dropping submitted values.

    Also normalises the status. FastAPI uses 422 for a body that failed schema validation,
    which is right, and this application uses 422 for ``NOT_ESTIMABLE``, which is also right -
    both are "well-formed but unprocessable". They are told apart by ``error.code``, and the
    metrics count them separately, which is the whole reason ``app_errors`` is labelled by
    code rather than by status.
    """
    assert isinstance(exc, RequestValidationError)
    field_errors = [
        FieldError(
            loc=[str(part) for part in raw.get("loc", ())],
            message=str(raw.get("msg", "invalid value")),
            code=str(raw.get("type", "invalid")),
        )
        for raw in exc.errors()
    ]
    return _response(
        request,
        ValidationError(
            "the request could not be validated",
            field_errors=field_errors,
            # Counted for the whole request rather than per field, so a form with nine bad
            # fields is one validation event and not nine.
            context={"field_count": len(field_errors)},
        ),
    )


async def handle_http_exception(request: Request, exc: Exception) -> Response:
    """Wrap the exceptions Starlette raises itself - 404 for an unmatched route, 405, 401.

    These come from the framework, not from application code, so they arrive as
    ``HTTPException`` with a plain string detail. Mapping them to a code here is what keeps
    the promise that every error body has an ``error.code`` a client can branch on.
    """
    assert isinstance(exc, HTTPException)
    mapping = {
        401: ErrorCode.NOT_AUTHENTICATED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        405: ErrorCode.MALFORMED_REQUEST,
        406: ErrorCode.MALFORMED_REQUEST,
        409: ErrorCode.CONFLICT,
        413: ErrorCode.PAYLOAD_TOO_LARGE,
        415: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
        429: ErrorCode.RATE_LIMITED,
    }
    detail = exc.detail if isinstance(exc.detail, str) else "the request could not be completed"
    error = AppError(
        detail,
        code=mapping.get(exc.status_code, ErrorCode.INTERNAL_ERROR),
        status_code=exc.status_code,
    )
    return _response(request, error, headers=dict(exc.headers or {}))


async def handle_unexpected(request: Request, exc: Exception) -> Response:
    """The backstop. Logs the traceback, returns a correlation id and nothing else.

    Registered against ``Exception``, so it also catches the bugs. Note that this must *not*
    be reached by ``AppError`` - handler lookup is by exact class then MRO, and ``AppError``
    has its own registration, so the specific handler wins.
    """
    log.exception(
        "api.unhandled_exception",
        exception_type=type(exc).__name__,
        route=getattr(request.state, "route_template", request.url.path),
    )
    correlation_id = _correlation_id(request)
    metrics.record_app_error(str(ErrorCode.INTERNAL_ERROR), 500)
    body: dict[str, Any] = {
        "error": {
            "code": str(ErrorCode.INTERNAL_ERROR),
            "message": "An unexpected error occurred. The incident has been recorded.",
            "remediation": "If this persists, contact support and quote the correlation id.",
        }
    }
    if correlation_id:
        body["error"]["correlation_id"] = correlation_id
    return ORJSONResponse(content=body, status_code=500)


def install(app: FastAPI) -> None:
    """Register every handler. Called once by the app factory.

    Order of registration does not matter - Starlette resolves by class - but completeness
    does: if ``Exception`` were omitted, an unhandled error would produce a bare 500 with an
    empty body and a stack trace on stdout, which is both a disclosure risk and unactionable.
    """
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected)


__all__ = [
    "ORJSONResponse",
    "handle_app_error",
    "handle_http_exception",
    "handle_unexpected",
    "handle_validation_error",
    "install",
]
