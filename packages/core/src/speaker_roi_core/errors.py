"""The application's error taxonomy and its wire envelope.

One exception hierarchy, one JSON shape, one place that decides which HTTP status a
failure earns. The alternative - raising ``HTTPException`` where the failure is detected -
puts transport concerns in the service layer, makes the same failure serialise differently
depending on which endpoint hit it, and cannot be raised at all from the worker, which has
no HTTP response to attach a status to.

Three rules the envelope enforces, all of them from plan.md §15:

**The message is for the caller; the cause is for the log.** Every error carries a
``message`` that is safe to render in a browser and an optional ``internal_detail`` that
never leaves the process. A stack trace, a failing SQL statement or a filename is
diagnostic gold in a log line and an information leak in a response body.

**Authorization failures do not explain themselves.** :class:`NotFoundError` and
:class:`ForbiddenError` are deliberately close in shape, because the decision of which to
return is a security decision: telling an unauthorized caller that an event *exists* but
belongs to another tenant is a cross-tenant information leak, so cross-tenant misses are
:class:`NotFoundError` by policy. See :func:`tenant_scoped_missing`.

**Every error is correlatable.** The envelope carries the request's correlation id, so a
user reporting "it said something went wrong at 14:32" is one log query away from the
actual traceback, and no traceback needs to be shown to them for that to work.

The taxonomy also carries the domain refusals this product is built around -
:class:`NotEstimableError`, :class:`EvidenceGradeError`, :class:`UnapprovedAssumptionError`.
Those are not bugs and not client mistakes; they are the analytical engine correctly
declining to publish a number, and they must reach the UI as an explanation rather than as
a 500.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final, Self


class ErrorCode(enum.StrEnum):
    """Stable, machine-readable failure identifiers.

    The frontend switches on these, so they are part of the API contract: a value may be
    added, but renaming or removing one is a breaking change. They are deliberately more
    granular than HTTP status codes, because ``409 Conflict`` covers both "this name is
    taken" and "this upload is already being processed", and those need different UI.
    """

    # --- request shape -----------------------------------------------------
    VALIDATION_FAILED = "VALIDATION_FAILED"
    MALFORMED_REQUEST = "MALFORMED_REQUEST"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    INVALID_CURSOR = "INVALID_CURSOR"

    # --- authentication and authorization ----------------------------------
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    MFA_REQUIRED = "MFA_REQUIRED"
    MFA_INVALID = "MFA_INVALID"
    REAUTHENTICATION_REQUIRED = "REAUTHENTICATION_REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    TENANT_SCOPE_REQUIRED = "TENANT_SCOPE_REQUIRED"

    # --- resources ---------------------------------------------------------
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    IMMUTABLE_RESOURCE = "IMMUTABLE_RESOURCE"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"

    # --- domain refusals ---------------------------------------------------
    NOT_ESTIMABLE = "NOT_ESTIMABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNAPPROVED_ASSUMPTION = "UNAPPROVED_ASSUMPTION"
    OUT_OF_SUPPORT = "OUT_OF_SUPPORT"
    INGESTION_REJECTED = "INGESTION_REJECTED"
    ANALYSIS_STATE_INVALID = "ANALYSIS_STATE_INVALID"

    # --- capacity ----------------------------------------------------------
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    CONCURRENCY_LIMIT = "CONCURRENCY_LIMIT"

    # --- infrastructure ----------------------------------------------------
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class FieldError:
    """One field-level validation failure.

    ``loc`` mirrors Pydantic's location tuple (``("body", "events", 0, "attendees")``) so
    a form can attach the message to the control that produced it without the frontend
    re-deriving the path.
    """

    __slots__ = ("code", "loc", "message")

    def __init__(self, loc: Sequence[str | int], message: str, code: str = "invalid") -> None:
        self.loc = tuple(loc)
        self.message = message
        self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"loc": list(self.loc), "message": self.message, "code": self.code}

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"FieldError({'.'.join(str(p) for p in self.loc)}: {self.message})"


class AppError(Exception):
    """Base class for every failure this application raises on purpose.

    Subclasses set ``status_code`` and ``code`` as class attributes so that a raise site
    reads as domain vocabulary - ``raise NotFoundError("event", event_id)`` - and the
    transport mapping lives here rather than at each of the several hundred raise sites.

    ``internal_detail`` is the single most important field. It is logged and never
    serialised, which lets a raise site be *specific* about the cause without anyone having
    to decide, under time pressure, whether that specificity is safe to expose.
    """

    status_code: int = 500
    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    #: Whether a client may usefully retry the identical request. Drives ``Retry-After``
    #: and lets the generated TS client decide without hard-coding a status list.
    retryable: bool = False
    #: Whether this failure should page someone. A 4xx is the caller's problem; a 5xx that
    #: is not a dependency blip is ours.
    alertable: bool = False

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode | None = None,
        status_code: int | None = None,
        internal_detail: str | None = None,
        field_errors: Sequence[FieldError] | None = None,
        context: Mapping[str, Any] | None = None,
        remediation: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.internal_detail = internal_detail
        self.field_errors: tuple[FieldError, ...] = tuple(field_errors or ())
        #: Structured, caller-safe context. Identifiers and counts belong here; free text
        #: from a user-supplied file does not, because it is the one thing plan.md §15
        #: names explicitly as unloggable.
        self.context: dict[str, Any] = dict(context or {})
        #: What the caller can do about it, in a sentence. An error the user cannot act on
        #: is a support ticket, so subclasses that have an obvious remedy state it.
        self.remediation = remediation
        self.retry_after_seconds = retry_after_seconds

    def to_envelope(self, *, correlation_id: str | None = None) -> dict[str, Any]:
        """The exact JSON body the API returns.

        Nested under ``error`` rather than flattened at the top level, so a successful
        response and a failed one are never ambiguous to a client that forgot to check the
        status code - a response either has ``error`` or it does not.
        """
        body: dict[str, Any] = {
            "error": {
                "code": str(self.code),
                "message": self.message,
            }
        }
        if self.field_errors:
            body["error"]["fields"] = [f.to_dict() for f in self.field_errors]
        if self.context:
            body["error"]["context"] = self.context
        if self.remediation:
            body["error"]["remediation"] = self.remediation
        if self.retryable:
            body["error"]["retryable"] = True
        if self.retry_after_seconds is not None:
            body["error"]["retry_after_seconds"] = self.retry_after_seconds
        if correlation_id:
            body["error"]["correlation_id"] = correlation_id
        return body

    def log_fields(self) -> dict[str, Any]:
        """Everything worth logging, including what the envelope withholds."""
        fields: dict[str, Any] = {
            "error_code": str(self.code),
            "status_code": self.status_code,
            "error_message": self.message,
        }
        if self.internal_detail:
            fields["internal_detail"] = self.internal_detail
        if self.context:
            fields["error_context"] = self.context
        if self.field_errors:
            fields["field_error_count"] = len(self.field_errors)
        return fields

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"{type(self).__name__}({self.code!s}, {self.message!r})"


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


class ValidationError(AppError):
    """Request body, query or path failed validation.

    422 and not 400: the request was syntactically well-formed JSON that the schema
    rejected. The distinction matters to an integrator, because a 400 means "fix your
    serialiser" and a 422 means "fix your values".
    """

    status_code = 422
    code = ErrorCode.VALIDATION_FAILED

    @classmethod
    def from_fields(cls, field_errors: Sequence[FieldError], message: str | None = None) -> Self:
        count = len(field_errors)
        default = f"{count} field{'s' if count != 1 else ''} failed validation"
        return cls(message or default, field_errors=field_errors)


class MalformedRequestError(AppError):
    status_code = 400
    code = ErrorCode.MALFORMED_REQUEST


class UnsupportedMediaTypeError(AppError):
    """The payload is not a format this endpoint can read.

    The accepted list is in the response on purpose. A 415 that says only "unsupported media
    type" leaves the uploader guessing, and what they guess is to rename the file - which is
    both futile against content sniffing and the exact behaviour that trains people to
    circumvent safety checks.

    ``detected`` is the type inferred from the *bytes*, not the one the client declared.
    Reporting the declared type back would just repeat what the caller sent; reporting what
    it actually is tells them their "CSV" is a zip archive.
    """

    status_code = 415
    code = ErrorCode.UNSUPPORTED_MEDIA_TYPE

    def __init__(
        self,
        *,
        detected: str | None = None,
        allowed: Sequence[str] = (),
        internal_detail: str | None = None,
    ) -> None:
        readable = ", ".join(_MEDIA_TYPE_LABELS.get(a, a) for a in allowed)
        message = "This file type is not accepted."
        if detected:
            message = f"This file appears to be {_MEDIA_TYPE_LABELS.get(detected, detected)}, which is not accepted."
        super().__init__(
            message,
            context={"detected_type": detected, "accepted_types": list(allowed)},
            remediation=f"Upload one of: {readable}." if readable else None,
            internal_detail=internal_detail,
        )


class PayloadTooLargeError(AppError):
    """The upload exceeds the configured ceiling.

    The limit is stated in megabytes as well as bytes. A limit expressed only as
    ``209715200`` requires the reader to do arithmetic before they know whether their 300 MB
    file is close or nowhere near, and the remediation they need - split the file by month -
    depends on that.
    """

    status_code = 413
    code = ErrorCode.PAYLOAD_TOO_LARGE

    def __init__(
        self,
        *,
        limit_bytes: int,
        actual_bytes: int | None = None,
        internal_detail: str | None = None,
    ) -> None:
        limit_mb = limit_bytes / (1024 * 1024)
        message = f"The file is larger than the {limit_mb:.0f} MB upload limit."
        context: dict[str, Any] = {"limit_bytes": limit_bytes, "limit_mb": round(limit_mb, 1)}
        if actual_bytes is not None:
            context["actual_bytes"] = actual_bytes
        super().__init__(
            message,
            context=context,
            remediation=(
                "Split the file - one upload per month, or per brand - and submit them "
                "separately. Each upload is validated independently."
            ),
            internal_detail=internal_detail,
        )


#: Human labels for the media types the product accepts, used in the two errors above.
#: A user who uploaded a macro-enabled workbook needs to read "an Excel workbook with
#: macros", not ``application/vnd.ms-excel.sheet.macroEnabled.12``.
_MEDIA_TYPE_LABELS: Final[dict[str, str]] = {
    "text/csv": "a CSV file",
    "text/plain": "a plain text file",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "an Excel workbook (.xlsx)",
    "application/vnd.ms-excel": "a legacy Excel workbook (.xls)",
    "application/vnd.ms-excel.sheet.macroEnabled.12": "an Excel workbook containing macros",
    "application/zip": "a zip archive",
    "application/pdf": "a PDF",
    "application/gzip": "a gzip archive",
    "application/x-rar-compressed": "a RAR archive",
    "application/x-7z-compressed": "a 7-Zip archive",
    "application/x-bzip2": "a bzip2 archive",
    "application/x-executable": "an executable program",
    "application/x-msdownload": "a Windows executable",
    "text/x-script": "a script",
    "application/octet-stream": "an unrecognised binary file",
    "application/json": "a JSON file",
}


class InvalidCursorError(AppError):
    """An opaque pagination cursor did not decode, or was signed for another query.

    400 rather than 422, and deliberately uninformative. A cursor encodes the sort key of
    the last row seen; an attacker who learns to forge one reads rows in an order the
    query was never authorized for. So a bad cursor gets "start from the beginning" and no
    diagnostic.
    """

    status_code = 400
    code = ErrorCode.INVALID_CURSOR

    def __init__(self, internal_detail: str | None = None) -> None:
        super().__init__(
            "The pagination cursor is not valid. Request the first page again.",
            internal_detail=internal_detail,
            remediation="Omit the cursor parameter to restart pagination.",
        )


# ---------------------------------------------------------------------------
# Authentication and authorization
# ---------------------------------------------------------------------------


class NotAuthenticatedError(AppError):
    status_code = 401
    code = ErrorCode.NOT_AUTHENTICATED

    def __init__(self, message: str = "Authentication is required.", **kw: Any) -> None:
        super().__init__(message, **kw)


class SessionExpiredError(NotAuthenticatedError):
    """Distinguished from a missing session so the SPA can preserve unsaved work.

    Both are 401. A missing session means "you were never signed in here" and the right
    response is a redirect to login; an expired one means "you were, and you may have a
    half-filled form open", where the right response is an in-place re-auth prompt. One
    code for both forces the client to discard state it did not need to discard.
    """

    code = ErrorCode.SESSION_EXPIRED

    def __init__(self, message: str = "Your session has expired. Sign in again.", **kw: Any):
        super().__init__(message, **kw)


class InvalidCredentialsError(NotAuthenticatedError):
    """Wrong username *or* wrong password, and the caller is never told which.

    The message is fixed at the class level for exactly this reason: a raise site cannot
    accidentally make it more helpful. Distinguishing the two turns a login form into a
    user-enumeration oracle, which is the reconnaissance step before credential stuffing.
    """

    code = ErrorCode.INVALID_CREDENTIALS

    def __init__(self, *, internal_detail: str | None = None) -> None:
        super().__init__(
            "The email address or password is incorrect.",
            internal_detail=internal_detail,
        )


class AccountLockedError(NotAuthenticatedError):
    code = ErrorCode.ACCOUNT_LOCKED
    retryable = True


class MfaRequiredError(AppError):
    """Credentials were correct; a second factor is outstanding.

    401 with its own code and a short-lived challenge token in ``context``. Not 403,
    because the caller is *becoming* authenticated rather than being refused.
    """

    status_code = 401
    code = ErrorCode.MFA_REQUIRED


class MfaInvalidError(AppError):
    status_code = 401
    code = ErrorCode.MFA_INVALID


class ReauthenticationRequiredError(AppError):
    """A sensitive operation inside a live session needs credentials re-entered.

    plan.md §15. Publishing a result, approving a finance assumption and changing a role
    are the operations a stolen session would be used for, and they are rare enough that
    re-prompting costs a legitimate user seconds a month.
    """

    status_code = 401
    code = ErrorCode.REAUTHENTICATION_REQUIRED

    def __init__(self, operation: str, *, window_seconds: int) -> None:
        super().__init__(
            "Confirm your password to continue.",
            context={"operation": operation, "window_seconds": window_seconds},
            remediation="Re-enter your password; the confirmation lasts "
            f"{window_seconds // 60} minutes.",
        )


class ForbiddenError(AppError):
    """Authenticated, identified, and not permitted.

    Used when the caller is *allowed to know the resource exists* - typically because it
    is inside their own tenant - but lacks the permission for this verb on it. When they
    are not allowed to know it exists, raise :class:`NotFoundError` instead; see
    :func:`tenant_scoped_missing`.
    """

    status_code = 403
    code = ErrorCode.FORBIDDEN

    def __init__(
        self,
        message: str = "You do not have permission to perform this action.",
        *,
        required_permission: str | None = None,
        **kw: Any,
    ) -> None:
        context = dict(kw.pop("context", None) or {})
        if required_permission:
            context["required_permission"] = required_permission
        super().__init__(message, context=context, **kw)


class TenantScopeRequiredError(AppError):
    """No tenant could be resolved for a request that needs one.

    A distinct failure from "forbidden", and a load-bearing one: plan.md §15 forbids
    accepting a tenant scope from browser form data, so the scope is resolved from the
    session server-side. If that resolution yields nothing, the correct behaviour is to
    refuse loudly rather than to fall through to a query with no tenant predicate - which
    under row-level security returns zero rows, and without it returns everything.
    """

    status_code = 400
    code = ErrorCode.TENANT_SCOPE_REQUIRED

    def __init__(
        self,
        message: str = "A tenant context is required for this request.",
        *,
        internal_detail: str | None = None,
    ) -> None:
        # ``internal_detail`` matters more here than on most subclasses. This error has two
        # very different causes that produce an identical response: a user with no tenant
        # membership (their problem, and the message tells them so), and a query that ran
        # outside ``session_scope`` so the RLS predicate could not resolve the GUC (our
        # problem, and the message would send the investigation in the wrong direction).
        # Only the log line can tell them apart.
        super().__init__(
            message,
            internal_detail=internal_detail,
            remediation="Select a tenant, or ask an administrator to grant you access to one.",
        )


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class NotFoundError(AppError):
    """The resource does not exist, or the caller may not know that it does."""

    status_code = 404
    code = ErrorCode.NOT_FOUND

    def __init__(
        self,
        resource: str,
        identifier: str | uuid.UUID | None = None,
        *,
        internal_detail: str | None = None,
    ) -> None:
        label = resource.replace("_", " ")
        super().__init__(
            f"The requested {label} was not found.",
            context={"resource": resource} | ({"id": str(identifier)} if identifier else {}),
            internal_detail=internal_detail,
        )


class ConflictError(AppError):
    status_code = 409
    code = ErrorCode.CONFLICT


class AlreadyExistsError(ConflictError):
    code = ErrorCode.ALREADY_EXISTS

    def __init__(self, resource: str, field: str, value: str) -> None:
        label = resource.replace("_", " ")
        super().__init__(
            f"A {label} with this {field.replace('_', ' ')} already exists.",
            field_errors=[FieldError(("body", field), "already in use", "duplicate")],
            context={"resource": resource, "field": field},
        )
        # The value is diagnostic and may be an email address, so it is logged only.
        self.internal_detail = f"{resource}.{field}={value!r} already present in tenant scope"


class PreconditionFailedError(AppError):
    """An ``If-Match`` did not match, so the caller's copy is stale.

    412 and not 409: the request could be retried verbatim after a re-read, and the
    distinction lets the client decide between "refresh and re-apply" and "surface a merge
    conflict to the user".
    """

    status_code = 412
    code = ErrorCode.PRECONDITION_FAILED


class ImmutableResourceError(ConflictError):
    """A published result, an audit event or an approved finance version was edited.

    plan.md §15 makes audit append-only and published analytical results immutable. The
    grants in the migration are the real enforcement; this exception is what the
    application returns *before* reaching for a statement the database would refuse, so
    the user gets an explanation instead of a driver error.
    """

    code = ErrorCode.IMMUTABLE_RESOURCE

    def __init__(self, resource: str, *, reason: str | None = None) -> None:
        label = resource.replace("_", " ")
        super().__init__(
            f"This {label} cannot be changed once it has been published.",
            context={"resource": resource},
            remediation=reason
            or "Create a new version instead; the existing record stays as the audit trail.",
        )


class IdempotencyKeyReusedError(ConflictError):
    """The same ``Idempotency-Key`` arrived with a different request body.

    A replay of the *identical* request returns the stored response, which is the whole
    point of the header. A different body under a used key is a client bug that would
    otherwise perform an unintended second mutation, so it is refused rather than merged.
    """

    code = ErrorCode.IDEMPOTENCY_KEY_REUSED

    def __init__(self, key: str) -> None:
        super().__init__(
            "This idempotency key was already used for a different request.",
            context={"idempotency_key": key},
            remediation="Generate a new idempotency key for a new request.",
        )


# ---------------------------------------------------------------------------
# Domain refusals - the analytical engine declining, correctly
# ---------------------------------------------------------------------------


class DomainRefusal(AppError):
    """Base class for "the method cannot answer this", as distinct from "you asked wrong".

    These are the product working as designed. A causal estimate that fails its
    identification gates is not an error to be retried or a bug to be fixed; it is the
    honest answer, and the UI renders it as a no-evidence state with the reasons attached.
    Grouping them under one base lets the API layer render all of them that way, and lets
    the metrics layer count them separately from faults.
    """

    status_code = 422
    alertable = False


class NotEstimableError(DomainRefusal):
    """The design does not support an estimate at all - a feasibility failure.

    Distinct from :class:`EvidenceGradeError` by exactly the distinction the evidence
    grader draws: *feasibility* means there is no valid comparison to make (too few
    matched attendees, no clean pre-period, no overlap), and *credibility* means a
    comparison exists but does not survive scrutiny. A feasibility failure yields no point
    estimate; a credibility failure yields one that may not be published as money.
    """

    code = ErrorCode.NOT_ESTIMABLE

    def __init__(self, reasons: Sequence[str], *, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            "This analysis cannot be estimated reliably from the available data.",
            context=dict(context or {}) | {"reasons": list(reasons)},
            remediation="More measured events, or a longer clean pre-event period, would "
            "make this estimable. The reasons list what is currently missing.",
        )


class EvidenceGradeError(DomainRefusal):
    """The estimate exists but its grade forbids the requested use.

    Raised when ROI is requested for a result graded ``DIRECTIONAL`` or below. The whole
    argument of this product is that a number good enough to indicate a direction is not
    good enough to put a currency symbol in front of, so this refusal is a feature and its
    message says so rather than apologising.
    """

    code = ErrorCode.INSUFFICIENT_EVIDENCE

    def __init__(self, grade: str, *, required: Sequence[str], detail: str | None = None) -> None:
        super().__init__(
            detail
            or (
                f"This result is graded {grade}, which is not strong enough to publish a "
                "financial figure."
            ),
            context={"grade": grade, "required_grades": list(required)},
            remediation="The direction of the effect can still be reported. A financial "
            "figure needs evidence graded " + " or ".join(required) + ".",
        )


class UnapprovedAssumptionError(DomainRefusal):
    """ROI was requested against a finance assumption set that nobody approved.

    Effective-dated and versioned finance assumptions are the input that turns a clinical
    effect into money, so an unapproved set is the one way a plausible-looking currency
    figure can be manufactured without anyone accountable for it.
    """

    code = ErrorCode.UNAPPROVED_ASSUMPTION

    def __init__(self, *, reason: str) -> None:
        super().__init__(
            "No approved finance assumptions apply to this result.",
            context={"reason": reason},
            remediation="Ask a finance approver to approve an assumption version effective "
            "on or before the event date.",
        )


class OutOfSupportError(DomainRefusal):
    """A forecast was requested for inputs outside the range the model was fitted on.

    M3 refuses and M4 warns, and the asymmetry is deliberate: an extrapolated per-attendee
    *effect* invents money, while an extrapolated turnout *rate* degrades gracefully and
    still beats guessing. So this is raised by the impact forecaster and not by the
    attendance forecaster.
    """

    code = ErrorCode.OUT_OF_SUPPORT

    def __init__(self, features: Sequence[str]) -> None:
        super().__init__(
            "This program is outside the range of the programs the model has measured.",
            context={"out_of_support_features": list(features)},
            remediation="Adjust the plan towards previously measured programs, or treat the "
            "pooled average as the only defensible estimate.",
        )


class IngestionRejectedError(DomainRefusal):
    """An upload failed a structural or safety gate before any row was accepted.

    Partial ingestion of a spreadsheet is worse than none: it leaves a tenant unable to
    say which months are complete. Rejection carries the row-level errors so the uploader
    can fix the file in one pass rather than discovering the next problem after each retry.
    """

    code = ErrorCode.INGESTION_REJECTED
    status_code = 422


class AnalysisStateError(DomainRefusal):
    """The analysis run is not in a state where this transition is legal.

    Publishing a run that is still executing, or re-running a published one, is a
    workflow error rather than a data error, and it must not silently succeed - a
    published result whose inputs are still moving is unauditable.
    """

    code = ErrorCode.ANALYSIS_STATE_INVALID
    status_code = 409

    def __init__(self, *, current: str, attempted: str, allowed: Sequence[str]) -> None:
        super().__init__(
            f"This analysis is {current.lower().replace('_', ' ')}, so it cannot be "
            f"{attempted.lower().replace('_', ' ')}.",
            context={"current_state": current, "attempted": attempted, "allowed": list(allowed)},
        )


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------


class RateLimitedError(AppError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    retryable = True

    def __init__(self, *, retry_after_seconds: int, limit: int, window: str = "minute") -> None:
        super().__init__(
            "Too many requests. Try again shortly.",
            context={"limit": limit, "window": window},
            retry_after_seconds=retry_after_seconds,
        )


class QuotaExceededError(AppError):
    """A per-tenant budget is spent - AI requests, storage, analysis runs.

    402 would imply a payment path this product does not own, and 429 would imply that
    waiting a minute helps. 403 with a distinct code says the request is refused on
    entitlement grounds and names the quota.
    """

    status_code = 403
    code = ErrorCode.QUOTA_EXCEEDED

    def __init__(self, *, quota: str, limit: int, used: int, resets: str | None = None) -> None:
        super().__init__(
            f"The {quota.replace('_', ' ')} quota for this workspace is exhausted.",
            context={"quota": quota, "limit": limit, "used": used}
            | ({"resets_at": resets} if resets else {}),
        )


class ConcurrencyLimitError(AppError):
    """Too many analyses already running for this tenant.

    Retryable, because the answer really is "wait for one to finish". A causal analysis
    with a full sensitivity suite is nine to eleven pipeline runs, so an unbounded queue
    is a way for one tenant to starve every other.
    """

    status_code = 429
    code = ErrorCode.CONCURRENCY_LIMIT
    retryable = True

    def __init__(self, *, running: int, limit: int) -> None:
        super().__init__(
            "This workspace already has the maximum number of analyses running.",
            context={"running": running, "limit": limit},
            retry_after_seconds=60,
            remediation="Wait for a running analysis to finish, or cancel one.",
        )


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


class InternalError(AppError):
    """An unexpected fault. The caller learns nothing except the correlation id.

    The default message is fixed and generic on purpose. Anything specific about an
    unexpected failure - a driver message, a key name, a path - is exactly the material
    that turns a crash into a disclosure, and by definition nobody has reviewed it for
    safety, because nobody expected it.
    """

    status_code = 500
    code = ErrorCode.INTERNAL_ERROR
    alertable = True

    def __init__(
        self,
        internal_detail: str | None = None,
        *,
        message: str = "Something went wrong. The error has been recorded.",
    ) -> None:
        super().__init__(message, internal_detail=internal_detail)


class DependencyUnavailableError(AppError):
    """Postgres, Redis, object storage or the model provider is not answering.

    503 and retryable. Named separately from :class:`InternalError` so that the alert
    routing can distinguish "our code is broken" from "something we depend on is", which
    are answered by different people.
    """

    status_code = 503
    code = ErrorCode.DEPENDENCY_UNAVAILABLE
    retryable = True
    alertable = True

    def __init__(self, dependency: str, *, internal_detail: str | None = None) -> None:
        super().__init__(
            "A service this request depends on is temporarily unavailable.",
            context={"dependency": dependency},
            internal_detail=internal_detail,
            retry_after_seconds=15,
        )


class TimeoutError_(AppError):
    """Named with a trailing underscore so it cannot shadow the builtin.

    Shadowing ``TimeoutError`` in a module that also catches ``asyncio.TimeoutError`` is a
    genuinely nasty bug: the ``except`` clause silently starts catching the wrong class.
    """

    status_code = 504
    code = ErrorCode.TIMEOUT
    retryable = True
    alertable = True


class NotImplementedYetError(AppError):
    """A declared endpoint that is deliberately not wired up yet.

    Better than a 404, which is indistinguishable from a typo in the path, and better
    than silence. 501 with this code lets the generated client and the acceptance suite
    both tell "not built" apart from "broken".
    """

    status_code = 501
    code = ErrorCode.NOT_IMPLEMENTED


# ---------------------------------------------------------------------------
# Policy helpers
# ---------------------------------------------------------------------------


def tenant_scoped_missing(
    resource: str,
    identifier: str | uuid.UUID,
    *,
    exists_elsewhere: bool = False,
) -> NotFoundError:
    """The one correct way to answer "that row is not in your tenant".

    A tenant-scoped query that returns nothing has two possible causes: the row does not
    exist, or it exists and belongs to someone else. Under row-level security the
    application cannot tell them apart, and *that is the desired property* - so both
    become a 404 and the caller cannot use response codes to enumerate another tenant's
    identifiers.

    ``exists_elsewhere`` is only ever set by a platform-admin code path that legitimately
    queried across tenants. It changes the log line and never the response.
    """
    return NotFoundError(
        resource,
        identifier,
        internal_detail=(
            f"{resource} {identifier} exists outside the caller's tenant scope; returned 404 "
            "to avoid cross-tenant enumeration"
            if exists_elsewhere
            else None
        ),
    )


#: Status codes that must never carry a response body describing the cause in detail.
#: Referenced by the API's exception handler and asserted in ``tests/security``.
OPAQUE_STATUSES: frozenset[int] = frozenset({401, 403, 404, 500})


__all__ = [
    "OPAQUE_STATUSES",
    "AccountLockedError",
    "AlreadyExistsError",
    "AnalysisStateError",
    "AppError",
    "ConcurrencyLimitError",
    "ConflictError",
    "DependencyUnavailableError",
    "DomainRefusal",
    "ErrorCode",
    "EvidenceGradeError",
    "FieldError",
    "ForbiddenError",
    "IdempotencyKeyReusedError",
    "ImmutableResourceError",
    "IngestionRejectedError",
    "InternalError",
    "InvalidCredentialsError",
    "InvalidCursorError",
    "MalformedRequestError",
    "MfaInvalidError",
    "MfaRequiredError",
    "NotAuthenticatedError",
    "NotEstimableError",
    "NotFoundError",
    "NotImplementedYetError",
    "OutOfSupportError",
    "PayloadTooLargeError",
    "PreconditionFailedError",
    "QuotaExceededError",
    "RateLimitedError",
    "ReauthenticationRequiredError",
    "SessionExpiredError",
    "TenantScopeRequiredError",
    "TimeoutError_",
    "UnapprovedAssumptionError",
    "UnsupportedMediaTypeError",
    "ValidationError",
    "tenant_scoped_missing",
]
