"""OpenAPI document: tag descriptions, the shared error schema, and the security scheme.

The generated document is the API documentation. Writing a separate prose reference alongside
it guarantees the two disagree within a release, so the effort goes here instead - into tag
descriptions that explain *when* to use a group of endpoints, and into an error schema that is
attached to every response rather than described once in a paragraph.

The one thing FastAPI does not infer is the error envelope. It documents the 200 shape from the
return annotation and then documents 422 as its own internal ``HTTPValidationError``, which is
not what this application returns. :func:`customise_openapi` replaces that and adds the error
responses that apply to every authenticated endpoint, so a client generator produces a typed
error branch instead of an untyped one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi.openapi.utils import get_openapi

if TYPE_CHECKING:
    from fastapi import FastAPI

    from speaker_roi_core.config import Settings

DESCRIPTION = """
Measures the **causal** commercial return of pharmaceutical speaker programmes, and forecasts
the return of programmes not yet run.

### What the numbers mean

Every estimate this API returns carries an interval and an **evidence grade**. The grade comes
from hard design gates - parallel-trends tests, covariate balance, placebo outcomes, effective
sample size - and never from a model's self-reported confidence. When the gates fail, the
endpoint returns `NOT_ESTIMABLE` with the reason rather than a number, and that is a successful
response to a well-formed question, not an error in the usual sense.

A naive before-and-after comparison of attendees overstates the true effect by five to eight
times on representative data, because the physicians who attend are the ones already growing.
Everything here exists to avoid publishing that number.

### Conventions

* **Pagination** is keyset-based. Follow `nextCursor`; do not construct cursors.
* **Long operations** return `202 Accepted` with a `statusUrl` to poll. Analyses, optimizer
  solves and exports are never synchronous.
* **Idempotency**: send `Idempotency-Key` on every POST that starts work or changes a monetary
  figure. A retry with the same key returns the original outcome instead of doing it twice.
* **Concurrency**: mutable resources return a `version`. Send it back on `PATCH`; a stale value
  is refused with `412` rather than silently overwriting someone else's edit.
* **Errors** all share one shape: `{"error": {"code", "message", ...}}`. Branch on `code`, never
  on the message text.
* **Correlation**: every response carries `X-Correlation-Id`. Quote it in a support request.

### Access

Browser clients authenticate with an `HttpOnly` session cookie established by
`POST /auth/login`. Machine clients present a short-lived bearer token minted from an API key.
Authorization is by permission, and permissions come from the role memberships resolved
server-side from the session - never from anything in the request.

External vendor contributors are a restricted principal: prescription data, ROI, analyses,
forecasts and other vendors' submissions are removed from their permission set at
authentication time and are not reachable by any endpoint.
""".strip()

TAGS: list[dict[str, Any]] = [
    {
        "name": "auth",
        "description": "Sign in, multi-factor verification, session and password lifecycle.",
    },
    {
        "name": "me",
        "description": "The signed-in user's own profile, memberships, preferences and "
        "notification state. The organisation switcher posts here.",
    },
    {
        "name": "tenants",
        "description": "Organisation settings, branding, currencies and feature flags. "
        "Platform operators create organisations; administrators configure their own.",
    },
    {
        "name": "users",
        "description": "Membership administration: invite, grant and revoke roles, set brand "
        "and vendor scope. Separation of duties is enforced here - the role that runs an "
        "analysis cannot be the role that publishes it.",
    },
    {
        "name": "master-data",
        "description": "Brands, products, vendors, taxonomy and market factors. The reference "
        "data every other module joins to.",
    },
    {
        "name": "hcps",
        "description": "Healthcare professional master records and identifier resolution. "
        "Prescriber-grain data is gated by a separate permission and is never exposed to "
        "vendor contributors or in speaker-selection ranking.",
    },
    {
        "name": "events",
        "description": "Speaker programmes: planning, workflow states, speakers, costs, "
        "invitations and attendance capture.",
    },
    {
        "name": "ingestion",
        "description": "Upload sessions, column mapping, validation, quarantine and dataset "
        "contracts. Files are validated before they are accepted, and a rejected row is "
        "returned with the reason rather than dropped.",
    },
    {
        "name": "analyses",
        "description": "Causal analysis runs: matching, event-study, cohort-time ATT, "
        "placebo and sensitivity suites. Asynchronous, versioned and reproducible from the "
        "stored specification.",
    },
    {
        "name": "roi",
        "description": "Return on investment built from a causal estimate and an approved "
        "finance assumption set. Refuses to compute against unapproved assumptions.",
    },
    {
        "name": "finance",
        "description": "Assumption sets, gross-margin and adherence parameters, currency and "
        "FX. Versioned and approval-gated, because these inputs move every ROI figure.",
    },
    {
        "name": "forecasts",
        "description": "Forward-looking estimates: expected attendance and reach for a planned "
        "programme, and the expected prescribing impact per attendee. Both refuse to "
        "extrapolate outside the support of their training data rather than returning a "
        "saturated guess.",
    },
    {
        "name": "optimizer",
        "description": "Budget and portfolio allocation under constraints, consuming the "
        "forecast models. Returns the allocation, its expected return with intervals, and "
        "which constraints bound the solution.",
    },
    {
        "name": "assistant",
        "description": "Natural-language questions over a governed semantic layer. Intents are "
        "allowlisted and resolved to read-only functions; there is no text-to-SQL, and the "
        "model narrates a structured fact payload it cannot enlarge.",
    },
    {
        "name": "exports",
        "description": "Report and dataset generation. Every export is logged with its filters "
        "and row count; downloads use short-lived authorized URLs.",
    },
    {
        "name": "audit",
        "description": "Append-only audit trail: authentication, authorization decisions, data "
        "changes, publication and model promotion.",
    },
    {
        "name": "admin",
        "description": "Platform console: organisations, estate-wide model registry, retention "
        "and support access. Restricted to platform operators, who are deliberately *not* "
        "granted tenant data access by virtue of being operators.",
    },
    {"name": "health", "description": "Liveness, readiness and metrics."},
]

#: The error envelope, described once and referenced everywhere.
_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["error"],
    "properties": {
        "error": {
            "type": "object",
            "required": ["code", "message"],
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Stable machine-readable taxonomy code. Branch on this.",
                    "example": "NOT_ESTIMABLE",
                },
                "message": {
                    "type": "string",
                    "description": "Human-readable and safe to display. Never contains "
                    "internal detail, identifiers or stack information.",
                },
                "fields": {
                    "type": "array",
                    "description": "Per-field validation failures. The submitted value is "
                    "deliberately absent.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "loc": {"type": "array", "items": {"type": "string"}},
                            "message": {"type": "string"},
                            "code": {"type": "string"},
                        },
                    },
                },
                "context": {
                    "type": "object",
                    "description": "Bounded, non-sensitive detail - counts and enumerated "
                    "reasons - for the client to render.",
                    "additionalProperties": True,
                },
                "remediation": {
                    "type": "string",
                    "description": "What the caller can do about it.",
                },
                "retryable": {"type": "boolean"},
                "retry_after_seconds": {"type": "integer", "nullable": True},
                "correlation_id": {
                    "type": "string",
                    "description": "Quote this in a support request.",
                },
            },
        }
    },
}

#: Attached to every operation. Written out rather than generated from ``ErrorCode`` so the
#: descriptions can say what a client should *do*, which the enum cannot.
_COMMON_RESPONSES: dict[str, dict[str, Any]] = {
    "400": {"description": "Malformed request."},
    "401": {"description": "Not authenticated, or the session has expired. Sign in again."},
    "403": {
        "description": "Authenticated but not permitted. The body names the missing "
        "permission, never the caller's roles."
    },
    "409": {"description": "Conflict: duplicate, immutable, or a reused idempotency key."},
    "412": {"description": "Stale `version`. Re-read the resource and re-apply the change."},
    "422": {
        "description": "Well-formed but unprocessable. Either schema validation "
        "(`VALIDATION_FAILED`) or a domain refusal (`NOT_ESTIMABLE`, `OUT_OF_SUPPORT`, "
        "`UNAPPROVED_ASSUMPTION`). These are different events despite sharing a status - "
        "distinguish them by `error.code`."
    },
    "429": {"description": "Rate limited. Honour `Retry-After`."},
    "503": {"description": "A dependency is unavailable. Retryable."},
}


def customise_openapi(app: FastAPI, settings: Settings) -> None:
    """Install a cached OpenAPI generator that adds what FastAPI cannot infer.

    Cached on ``app.openapi_schema`` because generation walks every route and every model, and
    the document is immutable for the process lifetime. Without the cache, a docs page load
    regenerates it on every request.
    """

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=TAGS,
        )
        components = schema.setdefault("components", {})
        components.setdefault("schemas", {})["Error"] = _ERROR_SCHEMA
        components["securitySchemes"] = {
            "sessionCookie": {
                "type": "apiKey",
                "in": "cookie",
                "name": settings.auth.session_cookie_name,
                "description": "Set by `POST /auth/login`. `HttpOnly`, `Secure` and "
                "`SameSite=Lax`, so it is unreadable by page script and is not sent on "
                "cross-site navigations.",
            },
            "bearerToken": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "For machine clients. Minted from an API key, valid fifteen "
                "minutes, and unable to satisfy re-authentication - so publication and "
                "role changes are not available to a service account.",
            },
        }
        schema["security"] = [{"sessionCookie": []}, {"bearerToken": []}]

        error_ref = {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                responses = operation.setdefault("responses", {})
                for status, meta in _COMMON_RESPONSES.items():
                    # ``setdefault``, so an operation that documented its own 409 with a
                    # specific meaning keeps it. The generic text is a floor, not a ceiling.
                    responses.setdefault(status, {**meta, "content": error_ref})

        schema["info"]["contact"] = {"name": "Platform Operations"}
        schema["info"]["x-environment"] = settings.app_env
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


__all__ = ["DESCRIPTION", "TAGS", "customise_openapi"]
