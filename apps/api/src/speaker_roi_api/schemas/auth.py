"""Request and response shapes for authentication and the signed-in user's own profile.

Two things here are deliberate and would be easy to "improve" into a security problem.

**No response model contains a token.** The session token is set as an ``HttpOnly`` cookie and
never appears in a JSON body. Returning it in the body would make it readable by page script,
which is the entire difference between "an XSS can act as the user until they close the tab" and
"an XSS has stolen a credential valid for twelve hours".

**The login response is the same shape whether MFA is outstanding or not.** A separate
``MfaChallenge`` model would encourage a client to branch on the *shape*, and a client that
branches on shape rather than on the ``mfaRequired`` flag breaks the day a third state exists
(forced password change, forced enrolment - both of which already do exist here).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import EmailStr, Field, StringConstraints

from speaker_roi_api.schemas.common import Schema

#: A TOTP code, loosely constrained. Loosely because the *strict* check belongs in the
#: verification function - which strips spaces and hyphens, since authenticator apps display
#: "123 456" and users paste what they see. Rejecting that at the schema boundary produces a
#: field error where the honest answer is "that is the right code, typed the way it was shown".
Code = Annotated[str, StringConstraints(min_length=6, max_length=14, strip_whitespace=True)]

#: Not constrained beyond a sane maximum. Every policy rule lives in ``passwords.policy_failures``
#: so that a user submitting a weak password gets the full list of what is wrong with it in one
#: response, rather than one rule at a time from a schema validator.
Password = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class LoginRequest(Schema):
    email: EmailStr
    password: Password
    remember: bool = Field(
        default=False,
        description="Extend the session's absolute lifetime. Does not extend the idle timeout - "
        "an unattended browser still locks.",
    )


class TenantSummary(Schema):
    """An organisation as it appears in the switcher."""

    id: uuid.UUID
    name: str
    #: The short stable identifier, e.g. ``acme-pharma``. Used in URLs and in export filenames,
    #: which is why it is exposed at all - the UUID would be correct and unreadable.
    code: str
    status: str
    #: The role held *in this organisation*. A user can be an analyst in one and a read-only
    #: reviewer in another, so this cannot be a property of the user.
    role: str | None = None


class SessionUser(Schema):
    """The identity half of the session, safe for the client to cache in memory."""

    id: uuid.UUID
    email: EmailStr
    display_name: str = Field(serialization_alias="displayName")
    is_platform_admin: bool = Field(default=False, serialization_alias="isPlatformAdmin")
    mfa_enrolled: bool = Field(default=False, serialization_alias="mfaEnrolled")


class LoginResponse(Schema):
    """What the client needs to decide which screen to show next.

    The three flags are checked in this order: ``mustChangePassword`` first (nothing else is
    reachable until it is done), then ``mfaRequired``, then whether ``activeTenantId`` is set. A
    client that checks them in a different order will occasionally show a tenant picker to
    someone who cannot yet use it.
    """

    user: SessionUser
    mfa_required: bool = Field(serialization_alias="mfaRequired")
    mfa_enrolment_required: bool = Field(
        default=False,
        serialization_alias="mfaEnrolmentRequired",
        description="The user's role demands a second factor and they have not enrolled one. "
        "They must complete enrolment before the session becomes usable; it is not optional "
        "and cannot be dismissed.",
    )
    must_change_password: bool = Field(serialization_alias="mustChangePassword")
    tenants: list[TenantSummary]
    active_tenant_id: uuid.UUID | None = Field(serialization_alias="activeTenantId")
    expires_at: datetime = Field(serialization_alias="expiresAt")


class MfaVerifyRequest(Schema):
    code: Code


class MfaEnrolStartResponse(Schema):
    """The one and only time the secret leaves the server.

    ``provisioningUri`` contains the shared secret in a query parameter, which is why this
    response is never logged, never cached, and is not returned again on a repeated call - a
    second call issues a *new* secret, invalidating the first. A URI that can be re-fetched is a
    URI that ends up in a browser history export.
    """

    secret: str = Field(description="Base32 shared secret, for manual entry.")
    provisioning_uri: str = Field(
        serialization_alias="provisioningUri",
        description="otpauth:// URI for the QR code. Treat as a credential.",
    )


class MfaEnrolConfirmRequest(Schema):
    code: Code


class RecoveryCodesResponse(Schema):
    """Shown once, in plaintext, and stored only as hashes.

    ``count`` exists so the UI can say "2 of 10 remaining" on the security page without the
    server having to hand back anything sensitive to answer that question.
    """

    codes: list[str] = Field(
        description="Single-use. Displayed once and not retrievable afterwards."
    )
    count: int


class RecoveryCodeRequest(Schema):
    code: Annotated[str, StringConstraints(min_length=8, max_length=64, strip_whitespace=True)]


class SwitchTenantRequest(Schema):
    tenant_id: uuid.UUID = Field(
        validation_alias="tenantId",
        description="Requested organisation. Treated as a lookup key into the caller's own "
        "memberships, never as a claim of access - an organisation the caller does not belong "
        "to is reported as not found.",
    )


class ChangePasswordRequest(Schema):
    current_password: Password = Field(validation_alias="currentPassword")
    new_password: Password = Field(validation_alias="newPassword")


class ReauthenticateRequest(Schema):
    password: Password


class PasswordResetRequest(Schema):
    email: EmailStr


class PasswordResetConfirmRequest(Schema):
    token: Annotated[str, StringConstraints(min_length=20, max_length=200)]
    new_password: Password = Field(validation_alias="newPassword")


class MembershipSummary(Schema):
    """One membership, as the profile page shows it."""

    tenant: TenantSummary
    role: str
    all_brands: bool = Field(serialization_alias="allBrands")
    brand_ids: list[uuid.UUID] = Field(default_factory=list, serialization_alias="brandIds")
    vendor_id: uuid.UUID | None = Field(default=None, serialization_alias="vendorId")
    granted_at: datetime = Field(serialization_alias="grantedAt")


class MeResponse(Schema):
    """Everything the frontend needs to render the shell and gate its navigation.

    ``permissions`` is the effective set for the *active* organisation, already reduced by the
    vendor restriction. The client uses it to hide controls the user cannot use - which is a
    usability measure and explicitly not a security one: every endpoint re-checks server-side,
    because a hidden button is a suggestion and a permission check is a rule.
    """

    user: SessionUser
    active_tenant: TenantSummary | None = Field(serialization_alias="activeTenant")
    memberships: list[MembershipSummary]
    permissions: list[str]
    roles: list[str]
    is_vendor: bool = Field(serialization_alias="isVendor")
    brand_scope: list[uuid.UUID] | None = Field(
        default=None,
        serialization_alias="brandScope",
        description="Null means every brand in the organisation. An empty list means none, "
        "which is a real and distinct state - a membership whose brand grants were all revoked.",
    )
    session_expires_at: datetime | None = Field(
        default=None, serialization_alias="sessionExpiresAt"
    )
    reauthentication_valid_until: datetime | None = Field(
        default=None,
        serialization_alias="reauthenticationValidUntil",
        description="Until when sensitive operations will proceed without re-entering the "
        "password. The client uses this to prompt before submitting rather than after failing.",
    )


class SessionSummary(Schema):
    """An active session, for the "where you're signed in" list.

    Deliberately thin. Neither the IP address nor the user-agent string is stored in a
    reversible form, so this cannot show "Chrome on Windows from Bengaluru" - and inventing
    that from a hash is not possible. What it can honestly show is when a session started, when
    it was last used, and whether it is the current one, which is enough to answer the question
    the page exists for: is there a session here I do not recognise.
    """

    id: uuid.UUID
    issued_at: datetime = Field(serialization_alias="issuedAt")
    last_seen_at: datetime = Field(serialization_alias="lastSeenAt")
    absolute_expires_at: datetime = Field(serialization_alias="absoluteExpiresAt")
    is_current: bool = Field(serialization_alias="isCurrent")
    mfa_satisfied: bool = Field(serialization_alias="mfaSatisfied")


class LogoutResponse(Schema):
    status: Literal["signed_out"] = "signed_out"


__all__ = [
    "ChangePasswordRequest",
    "Code",
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "MeResponse",
    "MembershipSummary",
    "MfaEnrolConfirmRequest",
    "MfaEnrolStartResponse",
    "MfaVerifyRequest",
    "Password",
    "PasswordResetConfirmRequest",
    "PasswordResetRequest",
    "ReauthenticateRequest",
    "RecoveryCodeRequest",
    "RecoveryCodesResponse",
    "SessionSummary",
    "SessionUser",
    "SwitchTenantRequest",
    "TenantSummary",
]
