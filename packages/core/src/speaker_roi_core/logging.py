"""Structured logging with mandatory redaction.

plan.md §15: *never log file contents, access tokens or sensitive free text*, and *do not
ingest patient names, phone numbers, addresses, prescription images or ABHA identifiers*.
A policy document cannot deliver that. What delivers it is a processor in the logging
pipeline that every line passes through, whether the developer thought about it or not.

The design has one governing idea: **redaction is a property of the pipeline, not of the
call site.** A call site that has to remember to redact will eventually not, usually in the
exception handler written at 2am. So :func:`_redact` runs on every event dictionary,
recursively, and:

* drops values under keys that name a secret (``password``, ``token``, ``authorization``,
  ``secret``, ``api_key``, ``cookie``, …);
* masks values that *look* like a credential regardless of their key, because the field
  that leaks a bearer token is usually called something innocuous like ``header`` or
  ``payload``;
* masks anything shaped like an email address, an Indian phone number or an ABHA id
  wherever it appears in a string, because those arrive inside free text from uploaded
  files and no key name predicts them;
* truncates long strings, since the realistic way a spreadsheet's contents reach a log is
  a driver echoing a failing statement with its bound parameters.

Two further deliberate choices:

**Redaction is fail-closed.** If the redactor itself raises on a pathological value, the
processor replaces the whole event with a marker rather than letting the unredacted
original through. A lost log line is an inconvenience; an emitted one is permanent.

**Context is bound automatically.** The tenant, correlation id and principal come from
:mod:`speaker_roi_core.context` in a processor, so no call site can omit them and every
line is correlatable. That is what makes it acceptable for the *messages* to be terse.
"""

from __future__ import annotations

import logging
import logging.config
import re
import sys
import time
import uuid
from collections.abc import Callable, Mapping, MutableMapping
from typing import Any, Final

import structlog

from speaker_roi_core.context import current_context

#: What a redacted value is replaced with. A fixed marker rather than a truncation of the
#: real value: a "partially redacted" token is often still enough to be useful to whoever
#: finds it, and a prefix is enough to identify which credential it was.
REDACTED: Final = "***REDACTED***"

#: Keys whose values never reach a log sink. Matched as a *substring* of the lowercased
#: key, so ``db_password``, ``passwordHash`` and ``x-api-key`` are all covered by short
#: entries, and a new field named in the same spirit is covered without a code change.
SENSITIVE_KEY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "authorization",
        "auth_header",
        "api_key",
        "apikey",
        "access_key",
        "private_key",
        "credential",
        "cookie",
        "session_key",
        "csrf",
        "otp",
        "mfa_code",
        "totp",
        "recovery_code",
        "signature",
        "dsn",
        # Patient-adjacent identifiers plan.md §15 forbids ingesting at all. Present here
        # as a second line of defence: if one ever reaches the process through a
        # malformed upload, it must not also reach the log aggregator.
        "patient_name",
        "phone",
        "mobile",
        "address",
        "abha",
        "aadhaar",
        "prescription_image",
        "raw_row",
        "raw_value",
        "file_contents",
        "free_text",
    }
)

#: Keys that are *contained in* a sensitive token but are themselves safe and useful.
#: ``token_count`` is a metric, ``phone_column_present`` is a schema fact, and losing them
#: would make the AI cost dashboard and the ingestion diagnostics unbuildable.
#:
#: Compared against the *normalised* key, so entries are written in underscore form and a
#: hyphenated variant of the same field is covered by the same entry.
SAFE_KEY_EXCEPTIONS: Final[frozenset[str]] = frozenset(
    {
        "token_count",
        "input_tokens",
        "output_tokens",
        "token_budget",
        "has_password",
        "password_age_days",
        "phone_column_present",
        "address_column_present",
        "secret_rotated_at",
        "cookie_count",
    }
)

#: Character class guarding the numeric patterns against firing inside a UUID.
#:
#: A UUID's final group is twelve hex characters, so roughly one identifier in sixteen has
#: an all-digit final group - and the "long digit run" rule below then rewrote
#: ``...-000000000007`` to ``...-***REDACTED***``. That is worse than useless: it
#: mangles the ``tenant_id`` and ``correlation_id`` fields that make the log searchable at
#: all, silently, for a fraction of identifiers, so the field looks fine in every example
#: anyone checks. Requiring that the run is not adjacent to a hex digit or a dash excludes
#: UUIDs, hashes and hex-encoded values while still catching a bare numeric identifier.
_HEXISH = r"[0-9A-Fa-f-]"

#: Value-shape patterns, applied to every string regardless of its key.
#:
#: These exist because the key name is unreliable. A bearer token most often leaks inside
#: a value called ``headers``, and an email address leaks inside a validation message that
#: helpfully quoted the offending cell.
_VALUE_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    # Authorization header values, with or without the header name.
    (re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + REDACTED),
    # JWTs, which are three base64url segments and are recognisable without a key name.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b"), REDACTED),
    # Anything self-labelling as a key. Covers most provider formats without listing them.
    (re.compile(r"(?i)\b(sk|pk|api|key)[-_][A-Za-z0-9]{16,}\b"), REDACTED),
    # A URL with inline credentials - the classic accidental DSN in a connection error.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+):[^\s/@]+@"), r"\1:" + REDACTED + "@"),
    # Email addresses. The domain is preserved because it is operationally useful and is
    # not, on its own, a personal identifier.
    (re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"), REDACTED + r"@\1"),
    # Indian mobile numbers. The separators are the point: a number pasted out of a
    # spreadsheet arrives as "+91 98765 43210" or "98765-43210" far more often than as ten
    # bare digits, and the first version of this pattern matched only the bare form - so
    # the single most common real-world spelling of the thing it exists to catch went
    # straight through.
    #
    # The groupings are enumerated rather than expressed as "digits with optional
    # separators anywhere". A permissive ``[6-9](?:[\s.-]?\d){9}`` also matches ten small
    # integers separated by spaces, which is exactly what a row of monthly prescription
    # counts looks like - so it would silently redact ordinary analytical output. Indian
    # mobiles are written 5-5, 3-3-4, or unbroken; those three are what this accepts.
    (
        re.compile(
            r"(?<![\w+])(?:\+?91[\s.-]?)?"
            r"(?:[6-9]\d{4}[\s.-]\d{5}|[6-9]\d{2}[\s.-]\d{3}[\s.-]\d{4}|[6-9]\d{9})"
            r"(?![\d-])"
        ),
        REDACTED,
    ),
    # ABHA: 14 digits, conventionally written in 2-4-4-4 groups.
    (
        re.compile(rf"(?<!{_HEXISH})\d{{2}}[\s-]?\d{{4}}[\s-]?\d{{4}}[\s-]?\d{{4}}(?!{_HEXISH})"),
        REDACTED,
    ),
    # Long digit runs, which is what a bare identifier column looks like when a row is
    # echoed into an error message.
    (re.compile(rf"(?<!{_HEXISH})\d{{12,}}(?!{_HEXISH})"), REDACTED),
)

#: Strings longer than this are truncated. Generous enough for a real message and a stack
#: frame, short enough that a spreadsheet row or a base64 blob cannot pass through whole.
MAX_VALUE_CHARS: Final = 512

#: Depth beyond which nesting is collapsed. Guards against a self-referential structure
#: turning a log call into an infinite walk, and against a deeply nested API payload being
#: logged in full.
MAX_DEPTH: Final = 6

#: Sequence and mapping size beyond which the remainder is summarised as a count. A
#: 50,000-row ingestion frame in an error context would otherwise be logged element by
#: element.
MAX_ITEMS: Final = 50


def _is_sensitive_key(key: str) -> bool:
    """Whether a key's value must never be emitted.

    Hyphens and spaces are normalised to underscores before matching. HTTP header names are
    conventionally hyphenated - ``x-api-key``, ``x-csrf-token`` - and headers are the single
    most likely dictionary in the process to contain a credential, so matching ``api_key``
    but not ``api-key`` would miss the case the rule most exists for. Normalising the key
    rather than doubling every entry in the token set means a new entry cannot be added in
    only one of its two spellings.
    """
    lowered = key.lower().replace("-", "_").replace(" ", "_")
    if lowered in SAFE_KEY_EXCEPTIONS:
        return False
    return any(token in lowered for token in SENSITIVE_KEY_TOKENS)


def _scrub_string(value: str) -> str:
    for pattern, replacement in _VALUE_PATTERNS:
        value = pattern.sub(replacement, value)
    if len(value) > MAX_VALUE_CHARS:
        # Report the original length: knowing a value was 400 kB is diagnostic, and the
        # bytes themselves are not.
        value = f"{value[:MAX_VALUE_CHARS]}…[truncated, {len(value)} chars]"
    return value


def _redact(value: Any, *, depth: int = 0) -> Any:
    """Recursively redact a value.

    Handles the containers that actually appear in log events. Anything else is rendered
    with ``repr`` and then scrubbed as a string - which is the important case, because an
    arbitrary ORM object's ``repr`` is exactly where a password hash or an email address
    turns up without anyone choosing to log it.
    """
    if depth > MAX_DEPTH:
        return f"<max depth {MAX_DEPTH} exceeded: {type(value).__name__}>"

    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _scrub_string(value)
    if isinstance(value, bytes | bytearray | memoryview):
        # Never the content. Length is the only part that is ever diagnostic.
        return f"<{len(value)} bytes>"
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for index, (k, v) in enumerate(value.items()):
            if index >= MAX_ITEMS:
                out["…"] = f"{len(value) - MAX_ITEMS} more keys"
                break
            key = str(k)
            out[key] = REDACTED if _is_sensitive_key(key) else _redact(v, depth=depth + 1)
        return out
    if isinstance(value, list | tuple | set | frozenset):
        items = list(value)
        rendered = [_redact(v, depth=depth + 1) for v in items[:MAX_ITEMS]]
        if len(items) > MAX_ITEMS:
            rendered.append(f"…{len(items) - MAX_ITEMS} more")
        return rendered
    if hasattr(value, "get_secret_value"):
        # A pydantic SecretStr already masks itself, but only under str/repr. Being
        # explicit means a future container type that does not is still covered.
        return REDACTED
    return _scrub_string(repr(value))


def redact_processor(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Structlog processor applying :func:`_redact` to the whole event.

    Fail-closed: if redaction raises - a ``__repr__`` that throws, a mapping with
    unhashable keys - the event is replaced by a marker. Emitting the original because the
    redactor failed would be precisely backwards.
    """
    try:
        return {
            str(k): (REDACTED if _is_sensitive_key(str(k)) else _redact(v))
            for k, v in event_dict.items()
        }
    except Exception as exc:
        return {
            "event": "log_redaction_failed",
            "level": "error",
            "redaction_error": type(exc).__name__,
            "original_event_key": str(event_dict.get("event", "?"))[:80],
        }


def context_processor(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Bind the ambient request context onto every line.

    Explicit fields on the call win over the ambient ones, so a log statement can
    deliberately report a *different* tenant - which the platform-admin cross-tenant paths
    need in order to record both the acting and the target tenant on one line.
    """
    ctx = current_context()
    if ctx is None:
        return event_dict
    for key, value in ctx.log_fields().items():
        event_dict.setdefault(key, value)
    return event_dict


def drop_color_message(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Remove uvicorn's ANSI-decorated duplicate of the message.

    Uvicorn logs ``color_message`` alongside ``event``. In JSON output it is a byte-for-byte
    duplicate wrapped in escape codes, which doubles the volume of the noisiest logger in
    the process for no benefit.
    """
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(
    *,
    level: str = "INFO",
    fmt: str = "json",
    service: str = "speaker-roi",
    version: str = "1.0.0",
    environment: str = "local",
) -> None:
    """Install the logging pipeline for the process. Idempotent.

    Standard-library logging is routed *through* structlog rather than configured
    alongside it. Without that, SQLAlchemy, uvicorn and botocore emit unstructured,
    unredacted lines into the same stream - and those are the loggers most likely to print
    a connection string or a bound parameter.
    """
    shared: list[Callable[..., Any]] = [
        structlog.contextvars.merge_contextvars,
        context_processor,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        drop_color_message,
        # Redaction runs immediately before rendering: after the exception formatter, so
        # a traceback's captured values are scrubbed too, and after every processor that
        # might add a field.
        structlog.processors.UnicodeDecoder(),
    ]

    if fmt == "json":
        # ``format_exc_info`` renders the traceback into a string that redaction can then
        # scrub. The ``dict_tracebacks`` alternative produces a nested structure whose
        # local variables are far richer - and unreviewable.
        shared.append(structlog.processors.format_exc_info)
        shared.append(redact_processor)
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        shared.append(redact_processor)
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        foreign_pre_chain=shared,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Library loggers whose defaults are wrong for a service.
    #
    # ``sqlalchemy.engine`` at INFO echoes every statement with its bound parameters,
    # which is the single largest source of patient-adjacent data in a log stream.
    # ``asyncio`` at DEBUG reports every selector wakeup. ``botocore`` logs request
    # signing material at DEBUG.
    for noisy, noisy_level in (
        ("sqlalchemy.engine", "WARNING"),
        ("sqlalchemy.pool", "WARNING"),
        ("sqlalchemy.dialects", "WARNING"),
        ("asyncio", "WARNING"),
        ("botocore", "WARNING"),
        ("boto3", "WARNING"),
        ("urllib3", "WARNING"),
        ("s3transfer", "WARNING"),
        ("celery.utils.functional", "WARNING"),
        ("multipart", "WARNING"),
        ("watchfiles", "WARNING"),
    ):
        logging.getLogger(noisy).setLevel(noisy_level)

    # uvicorn installs its own handlers; clearing them prevents every access line being
    # emitted twice, once structured and once not.
    for uvicorn_logger in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(uvicorn_logger)
        lg.handlers.clear()
        lg.propagate = True

    structlog.contextvars.bind_contextvars(
        service=service, service_version=version, environment=environment
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """A bound logger. Call it at module scope; binding is cheap and cached."""
    return structlog.stdlib.get_logger(name)


class LogTimer:
    """Context manager that logs the duration of a block, and whether it failed.

    Used for the operations whose latency is a product concern rather than a request
    concern - an analysis stage, an ingestion pass, a model fit. Emits on the way out in
    both directions, because a stage that takes ninety seconds and then raises is
    invisible if the timing is only logged on success.

    ``monotonic`` and not ``time()``: a clock adjustment mid-block would otherwise produce
    a negative duration, and NTP stepping a container's clock is not hypothetical.
    """

    __slots__ = ("_log", "_start", "event", "fields", "threshold_ms")

    def __init__(
        self,
        event: str,
        *,
        logger: structlog.stdlib.BoundLogger | None = None,
        threshold_ms: float | None = None,
        **fields: Any,
    ) -> None:
        self.event = event
        self.fields = fields
        #: Below this, success is logged at DEBUG instead of INFO. Keeps the routine case
        #: out of the stream while leaving the slow one visible.
        self.threshold_ms = threshold_ms
        self._log = logger or get_logger("speaker_roi.timing")
        self._start = 0.0

    def __enter__(self) -> LogTimer:
        self._start = time.monotonic()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any
    ) -> bool:
        elapsed_ms = (time.monotonic() - self._start) * 1_000.0
        payload = {**self.fields, "duration_ms": round(elapsed_ms, 2)}
        if exc_type is not None:
            self._log.error(f"{self.event}.failed", error_type=exc_type.__name__, **payload)
        elif self.threshold_ms is not None and elapsed_ms < self.threshold_ms:
            self._log.debug(f"{self.event}.completed", **payload)
        else:
            self._log.info(f"{self.event}.completed", **payload)
        return False  # never suppress

    def add(self, **fields: Any) -> None:
        """Attach fields discovered inside the block - a row count, a chosen strategy."""
        self.fields.update(fields)


__all__ = [
    "MAX_DEPTH",
    "MAX_ITEMS",
    "MAX_VALUE_CHARS",
    "REDACTED",
    "SAFE_KEY_EXCEPTIONS",
    "SENSITIVE_KEY_TOKENS",
    "LogTimer",
    "configure_logging",
    "context_processor",
    "get_logger",
    "redact_processor",
]
