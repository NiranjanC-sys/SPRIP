"""The permission matrix, and the one place authorization decisions are defined.

Roles are coarse and stable; permissions are fine and get added constantly. Endpoints
therefore depend on *permissions*, never on roles - `require(Permission.EVENT_WRITE)` rather
than `if role in (PHARMA_ADMIN, BRAND_MANAGER)`. The difference matters the first time a
customer asks for a role that can edit events but not approve them: with a role check that is
a change to every handler that mentioned the old roles, and every one of them is a place to
forget.

Three properties here are deliberate and load-bearing.

**A role's grants are a literal set, not a hierarchy.** It is tempting to write
``ANALYTICS_LEAD ⊃ BRAND_MANAGER ⊃ EXECUTIVE_VIEWER`` and inherit. But the roles are not
actually nested - a Finance Reviewer approves monetary assumptions that an Analytics Lead
cannot touch, and a Compliance Reviewer can publish results but cannot run an analysis. An
invented hierarchy would silently grant whichever permission was added to the "lower" role
next, and nobody reviewing that diff would see the widening.

**PLATFORM_ADMIN is not a superuser.** plan.md §5.4 requires that the operator of the
platform cannot read a customer's commercial data. It is granted the platform console
permissions and nothing else, and :meth:`speaker_roi_core.context.Principal.has` does not
treat it as an implicit bypass. This is the single most counter-intuitive line in the file and
the one most likely to be "fixed" by someone debugging an access denial.

**VENDOR_CONTRIBUTOR's grants are a floor, not a ceiling.** The vendor role can write
uploads, but which *datasets* it may write is a per-vendor grant in
``core.vendor_dataset_grants``, and whether it may see a given row is decided by its vendor
scope. Holding ``UPLOAD_WRITE`` says a vendor may upload something, never that it may upload
this. See :func:`assert_vendor_may_write_dataset`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from speaker_roi_core.context import Principal
from speaker_roi_core.enums import Role
from speaker_roi_core.errors import ForbiddenError

if TYPE_CHECKING:
    from collections.abc import Iterable


class Permission(StrEnum):
    """A single authorizable capability.

    Named ``<subject>:<verb>`` so the string form is legible in an audit record and in a
    denial message, and so a reviewer reading ``permissions`` on a session can tell what it
    allows without consulting this file.
    """

    # --- platform (tenant-less) -------------------------------------------
    PLATFORM_TENANT_READ = "platform.tenant:read"
    PLATFORM_TENANT_WRITE = "platform.tenant:write"
    PLATFORM_USER_READ = "platform.user:read"
    PLATFORM_HEALTH_READ = "platform.health:read"

    # --- tenant administration -------------------------------------------
    TENANT_READ = "tenant:read"
    TENANT_WRITE = "tenant:write"
    USER_READ = "user:read"
    USER_INVITE = "user:invite"
    MEMBERSHIP_WRITE = "membership:write"
    VENDOR_READ = "vendor:read"
    VENDOR_WRITE = "vendor:write"
    API_KEY_WRITE = "api_key:write"

    # --- commercial master data ------------------------------------------
    BRAND_READ = "brand:read"
    BRAND_WRITE = "brand:write"
    CAMPAIGN_READ = "campaign:read"
    CAMPAIGN_WRITE = "campaign:write"
    EVENT_READ = "event:read"
    EVENT_WRITE = "event:write"
    HCP_READ = "hcp:read"
    HCP_WRITE = "hcp:write"

    # --- prescriber-grain data (the sensitive tier) -----------------------
    #: Reading the HCP-grain prescription panel. Held by nobody who does not need it, and
    #: never by a vendor, regardless of the vendor's write grants (plan.md §5.5).
    RX_READ = "rx:read"
    RX_WRITE = "rx:write"
    IDENTITY_RESOLVE = "identity:resolve"

    # --- ingestion --------------------------------------------------------
    UPLOAD_READ = "upload:read"
    UPLOAD_WRITE = "upload:write"
    #: Reviewing and accepting another party's upload into a published data version.
    DATA_VERSION_PUBLISH = "data_version:publish"
    MAPPING_DECIDE = "mapping:decide"
    DATA_HEALTH_READ = "data_health:read"

    # --- analytics --------------------------------------------------------
    ANALYSIS_READ = "analysis:read"
    ANALYSIS_RUN = "analysis:run"
    #: Move a completed run from internal to visible. Separate from running it, because the
    #: person who ran an analysis should not be the person who signs off on it.
    RESULT_SUBMIT = "result:submit"
    RESULT_REVIEW = "result:review"
    RESULT_PUBLISH = "result:publish"

    # --- money ------------------------------------------------------------
    FINANCE_READ = "finance:read"
    FINANCE_ASSUMPTION_WRITE = "finance.assumption:write"
    #: Approving the assumptions every ROI number downstream is computed from.
    FINANCE_ASSUMPTION_APPROVE = "finance.assumption:approve"
    ROI_READ = "roi:read"

    # --- forward-looking --------------------------------------------------
    FORECAST_READ = "forecast:read"
    SCENARIO_READ = "scenario:read"
    SCENARIO_WRITE = "scenario:write"
    OPTIMIZER_RUN = "optimizer:run"

    # --- models -----------------------------------------------------------
    MODEL_READ = "model:read"
    MODEL_TRAIN = "model:train"
    MODEL_APPROVE = "model:approve"

    # --- assistant, export, audit ----------------------------------------
    AI_QUERY = "ai:query"
    EXPORT_CREATE = "export:create"
    EXPORT_READ = "export:read"
    AUDIT_READ = "audit:read"


P = Permission

#: Read-only access to the analytical surface. Composed rather than repeated so that adding a
#: new read-only analytical resource is one edit, not nine.
_ANALYTICAL_READ: frozenset[Permission] = frozenset(
    {
        P.BRAND_READ,
        P.CAMPAIGN_READ,
        P.EVENT_READ,
        P.ANALYSIS_READ,
        P.ROI_READ,
        P.FORECAST_READ,
        P.SCENARIO_READ,
        P.FINANCE_READ,
        P.DATA_HEALTH_READ,
        P.MODEL_READ,
        P.AI_QUERY,
        P.EXPORT_CREATE,
        P.EXPORT_READ,
    }
)

#: Deliberately *not* a superset of anything. See the module docstring.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    # Operates the platform. Sees tenants, their health and their bills - never their data.
    Role.PLATFORM_ADMIN: frozenset(
        {
            P.PLATFORM_TENANT_READ,
            P.PLATFORM_TENANT_WRITE,
            P.PLATFORM_USER_READ,
            P.PLATFORM_HEALTH_READ,
            P.AUDIT_READ,
        }
    ),
    # Owns one customer's configuration end to end, including who else gets in.
    Role.PHARMA_ADMIN: _ANALYTICAL_READ
    | frozenset(
        {
            P.TENANT_READ,
            P.TENANT_WRITE,
            P.USER_READ,
            P.USER_INVITE,
            P.MEMBERSHIP_WRITE,
            P.VENDOR_READ,
            P.VENDOR_WRITE,
            P.API_KEY_WRITE,
            P.BRAND_WRITE,
            P.CAMPAIGN_WRITE,
            P.EVENT_WRITE,
            P.HCP_READ,
            P.HCP_WRITE,
            P.UPLOAD_READ,
            P.UPLOAD_WRITE,
            P.AUDIT_READ,
            # Not RX_READ. An administrator's job is configuration; prescriber-grain
            # prescription data is the analyst's tier and there is no operational reason
            # for the two to coincide. Grantable per tenant if a customer insists.
        }
    ),
    # A third party submitting data. The narrowest role in the system.
    Role.VENDOR_CONTRIBUTOR: frozenset(
        {
            P.UPLOAD_READ,
            P.UPLOAD_WRITE,
            # Its own submissions' health only - the vendor-scoped filter, not the tenant's
            # full Data Health page.
            P.DATA_HEALTH_READ,
        }
    ),
    # Owns data quality: mappings, duplicates, publication of a clean data version.
    Role.DATA_STEWARD: frozenset(
        {
            P.BRAND_READ,
            P.CAMPAIGN_READ,
            P.EVENT_READ,
            P.EVENT_WRITE,
            P.HCP_READ,
            P.HCP_WRITE,
            P.RX_READ,
            P.RX_WRITE,
            P.IDENTITY_RESOLVE,
            P.UPLOAD_READ,
            P.UPLOAD_WRITE,
            P.MAPPING_DECIDE,
            P.DATA_VERSION_PUBLISH,
            P.DATA_HEALTH_READ,
            P.ANALYSIS_READ,
            P.EXPORT_CREATE,
            P.EXPORT_READ,
            P.VENDOR_READ,
        }
    ),
    # Runs the causal work and owns the models.
    Role.ANALYTICS_LEAD: _ANALYTICAL_READ
    | frozenset(
        {
            P.HCP_READ,
            P.RX_READ,
            P.ANALYSIS_RUN,
            P.RESULT_SUBMIT,
            P.OPTIMIZER_RUN,
            P.SCENARIO_WRITE,
            P.MODEL_TRAIN,
            P.UPLOAD_READ,
            # Not RESULT_PUBLISH and not MODEL_APPROVE. The person who produced a result
            # does not clear it - that separation is what makes the review gate mean
            # anything, and it is required by plan.md §15.
        }
    ),
    # Owns the monetary inputs, and is the only role that can approve them.
    Role.FINANCE_REVIEWER: _ANALYTICAL_READ
    | frozenset(
        {
            P.FINANCE_ASSUMPTION_WRITE,
            P.FINANCE_ASSUMPTION_APPROVE,
            P.SCENARIO_WRITE,
        }
    ),
    # Clears results for publication and reads the audit trail. Cannot produce them.
    Role.COMPLIANCE_REVIEWER: _ANALYTICAL_READ
    | frozenset(
        {
            P.RESULT_REVIEW,
            P.RESULT_PUBLISH,
            P.MODEL_APPROVE,
            P.AUDIT_READ,
            P.UPLOAD_READ,
        }
    ),
    # Plans and reads within their brand scope. The scope, not the role, is the limit.
    Role.BRAND_MANAGER: _ANALYTICAL_READ
    | frozenset(
        {
            P.HCP_READ,
            P.EVENT_WRITE,
            P.CAMPAIGN_WRITE,
            P.SCENARIO_WRITE,
            P.OPTIMIZER_RUN,
        }
    ),
    # Reads the roll-ups. No write anywhere, including scenarios.
    Role.EXECUTIVE_VIEWER: _ANALYTICAL_READ - frozenset({P.EXPORT_CREATE}),
}

#: Permissions that require a *recent* second factor, not merely a valid session.
#:
#: plan.md §5.2 mandates forced re-authentication for sensitive administrative actions. The
#: set is defined by consequence rather than by role: anything that changes who can get in,
#: what the money numbers are, or what the outside world sees.
REAUTH_REQUIRED: frozenset[Permission] = frozenset(
    {
        P.PLATFORM_TENANT_WRITE,
        P.MEMBERSHIP_WRITE,
        P.USER_INVITE,
        P.API_KEY_WRITE,
        P.VENDOR_WRITE,
        P.TENANT_WRITE,
        P.FINANCE_ASSUMPTION_APPROVE,
        P.RESULT_PUBLISH,
        P.MODEL_APPROVE,
        P.DATA_VERSION_PUBLISH,
    }
)

#: Permissions that expose prescriber-grain prescription data, directly or by aggregation
#: fine enough to re-identify. A vendor principal is refused these unconditionally - before
#: the role matrix is consulted at all - because a misconfigured membership must not be able
#: to hand a data supplier the outcomes of the data it supplied (plan.md §5.5).
VENDOR_FORBIDDEN: frozenset[Permission] = frozenset(
    {
        P.RX_READ,
        P.ROI_READ,
        P.ANALYSIS_READ,
        P.FORECAST_READ,
        P.FINANCE_READ,
        P.SCENARIO_READ,
        P.MODEL_READ,
        P.AI_QUERY,
        P.HCP_READ,
        P.AUDIT_READ,
    }
)


def permissions_for(roles: Iterable[Role | str]) -> frozenset[str]:
    """Union the grants of every role held, as the strings a ``Principal`` carries.

    An unknown role name yields nothing rather than raising. A role removed from the enum
    but still present on an old membership row would otherwise take the whole login down,
    and "this user has fewer permissions than expected" is a far better failure than "this
    user cannot sign in and neither can anyone else with a stale row".
    """
    granted: set[str] = set()
    for role in roles:
        try:
            resolved = Role(role)
        except ValueError:
            continue
        granted.update(str(p) for p in ROLE_PERMISSIONS.get(resolved, frozenset()))
    return frozenset(granted)


def effective_permissions(roles: Iterable[Role | str], *, is_vendor: bool) -> frozenset[str]:
    """Grants for a set of roles, with the vendor subtraction applied.

    The subtraction happens here, once, at the point the principal is built - not at each
    endpoint. A check that lives at the call site is a check somebody can forget to write
    on the next endpoint, and the thing being prevented is the single worst disclosure this
    system could make.
    """
    granted = permissions_for(roles)
    if is_vendor:
        granted -= {str(p) for p in VENDOR_FORBIDDEN}
    return granted


def has_permission(principal: Principal, permission: Permission) -> bool:
    return principal.has(str(permission))


def assert_permission(principal: Principal, permission: Permission) -> None:
    """Raise :class:`ForbiddenError` unless the principal holds ``permission``.

    The message names the permission and not the roles that would grant it. Telling a
    caller "you need PHARMA_ADMIN" tells them which account to go phishing for; telling
    them which capability is missing is what they need to raise a ticket.
    """
    if not has_permission(principal, permission):
        raise ForbiddenError(
            f"this action requires the {permission} permission",
            internal_detail=(
                f"principal={principal.user_id} roles={sorted(principal.roles)} "
                f"missing={permission}"
            ),
            context={"required_permission": str(permission)},
        )


def requires_reauthentication(permission: Permission) -> bool:
    return permission in REAUTH_REQUIRED


__all__ = [
    "REAUTH_REQUIRED",
    "ROLE_PERMISSIONS",
    "VENDOR_FORBIDDEN",
    "Permission",
    "assert_permission",
    "effective_permissions",
    "has_permission",
    "permissions_for",
    "requires_reauthentication",
]
