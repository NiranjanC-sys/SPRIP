"""Identity, membership and session tables.

The authorization model has one invariant that the rest of the product depends
on (plan.md §5.5): **a user's effective scope is derived from rows in this
schema, never from request data and never from an identity-provider token
claim.** An OIDC token proves *who* the caller is; ``auth.memberships`` decides
*what they may see*. That is why ``memberships`` is a real table with its own
audit trail rather than a claim mapping.

Users are platform-level: the same person can be a Brand Manager in one tenant
and a Compliance Reviewer in another, and must be able to switch context without
a second account. Consequently ``auth.users`` carries no ``tenant_id`` and has no
row-level-security policy - it is reachable only through a membership join, and
the API never exposes a user lookup that is not membership-scoped.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from speaker_roi_core.db.base import (
    ActorMixin,
    Base,
    EffectiveDatedMixin,
    TenantMixin,
    TimestampMixin,
    VersionMixin,
    effective_range_check,
    tenant_lookup_index,
    uuid_pk,
)
from speaker_roi_core.db.types import JSONB, Sha256, pg_enum
from speaker_roi_core.enums import (
    AuthProviderKind,
    InvitationStatus,
    MembershipStatus,
    Role,
    UserStatus,
)

if TYPE_CHECKING:
    from speaker_roi_core.models.core import Brand, Tenant, Vendor


class User(Base, TimestampMixin, ActorMixin, VersionMixin):
    """A person who can sign in. Platform-scoped, no RLS policy.

    ``email`` is stored lowercased and uniquely indexed on the lowercased value,
    because treating ``A@x.com`` and ``a@x.com`` as different accounts is a
    credential-stuffing aid, not a feature.

    ``password_hash`` is nullable: an OIDC-only user has no local credential, and
    a local user who has been migrated to SSO should lose theirs rather than keep
    a dormant second way in.
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        Index("ix_users_external_subject", "auth_provider_kind", "external_subject"),
        CheckConstraint(
            "auth_provider_kind <> 'LOCAL' OR password_hash IS NOT NULL "
            "OR status IN ('INVITED', 'DISABLED')",
            name="local_user_has_credential",
        ),
        CheckConstraint(
            "failed_login_count >= 0",
            name="failed_login_count_non_negative",
        ),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus), nullable=False, default=UserStatus.INVITED
    )
    auth_provider_kind: Mapped[AuthProviderKind] = mapped_column(
        pg_enum(AuthProviderKind), nullable=False, default=AuthProviderKind.LOCAL
    )

    # --- local credential -------------------------------------------------
    #: Argon2id encoded hash (algorithm, parameters and salt are embedded in the
    #: string, so a parameter upgrade is a rehash-on-next-login, not a migration).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    must_change_password: Mapped[bool] = mapped_column(nullable=False, default=False)

    # --- second factor ----------------------------------------------------
    #: TOTP shared secret, encrypted with the application data key. Never
    #: returned by any endpoint; the enrolment response carries the provisioning
    #: URI exactly once and is not persisted.
    mfa_secret_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    #: A secret that has been generated but not yet proved. Separate from the live
    #: one so that re-enrolling does not disable the authenticator that currently
    #: works: overwriting ``mfa_secret_encrypted`` in place would leave an account
    #: that claims to be enrolled against a secret only the abandoned enrolment
    #: attempt ever saw, which is a lockout with no recovery path short of an
    #: operator. The pending value is promoted on confirmation and discarded
    #: otherwise.
    mfa_pending_secret_encrypted: Mapped[bytes | None] = mapped_column(nullable=True)
    mfa_enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Set by tenant policy for privileged roles (plan.md §5.2 requires MFA for
    #: administrative roles).
    mfa_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    #: Hashed single-use recovery codes. Stored as a JSONB array of hashes so a
    #: used code can be marked spent without leaking the remaining ones.
    mfa_recovery_codes: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    # --- federated identity ------------------------------------------------
    #: The IdP's stable subject claim. Never the email: emails get reassigned.
    external_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_issuer: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- lockout / activity -------------------------------------------------
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_password_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Platform operators. Deliberately a column on the user rather than a role
    #: in a membership, because a platform admin is not scoped to a tenant and
    #: must not inherit tenant data access (plan.md §5.4).
    is_platform_admin: Mapped[bool] = mapped_column(nullable=False, default=False)

    #: Set when a deletion request is executed. The row survives so audit events
    #: referencing this actor remain interpretable (docs/PLAN_REVIEW.md F-15).
    tombstoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Membership(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """Grants one user one role inside one tenant.

    A user may hold several roles in the same tenant (a Brand Manager who is also
    the Finance Controller in a small affiliate). Effective permissions are the
    union; the landing route is chosen by ``ROLE_LANDING_PRECEDENCE``.
    """

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "role", name="uq_memberships_tenant_user_role"),
        tenant_lookup_index("memberships", "status", "role"),
        Index("ix_memberships_user", "user_id"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(pg_enum(Role), nullable=False)
    status: Mapped[MembershipStatus] = mapped_column(
        pg_enum(MembershipStatus), nullable=False, default=MembershipStatus.ACTIVE
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    #: ``True`` means "all brands in the tenant". ``False`` means the scope is the
    #: explicit set in ``brand_scopes`` - and an empty set therefore denies
    #: everything, which is the safe default for a newly created scoped role.
    all_brands: Mapped[bool] = mapped_column(nullable=False, default=True)

    user: Mapped[User] = relationship(back_populates="memberships")
    tenant: Mapped[Tenant] = relationship(back_populates="memberships")
    brand_scopes: Mapped[list[MembershipBrandScope]] = relationship(
        back_populates="membership", cascade="all, delete-orphan"
    )
    vendor_scopes: Mapped[list[MembershipVendorScope]] = relationship(
        back_populates="membership", cascade="all, delete-orphan"
    )


class MembershipBrandScope(Base, TenantMixin, TimestampMixin, ActorMixin):
    """Restricts a membership to specific brands (plan.md §5.5)."""

    __tablename__ = "membership_brand_scopes"
    __table_args__ = (
        UniqueConstraint(
            "membership_id", "brand_id", name="uq_membership_brand_scopes_membership_brand"
        ),
        tenant_lookup_index("membership_brand_scopes", "brand_id"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    membership_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth.memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.brands.id", ondelete="CASCADE"), nullable=False
    )

    membership: Mapped[Membership] = relationship(back_populates="brand_scopes")
    brand: Mapped[Brand] = relationship()


class MembershipVendorScope(Base, TenantMixin, TimestampMixin, ActorMixin):
    """Binds a Vendor Contributor membership to exactly the vendors it may act for.

    plan.md §5.5 forbids a vendor from seeing another vendor's submissions. This
    table is the allowlist that the vendor-scoped queries filter on; there is no
    "all vendors" escape hatch, by design.
    """

    __tablename__ = "membership_vendor_scopes"
    __table_args__ = (
        UniqueConstraint(
            "membership_id", "vendor_id", name="uq_membership_vendor_scopes_membership_vendor"
        ),
        tenant_lookup_index("membership_vendor_scopes", "vendor_id"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    membership_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth.memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.vendors.id", ondelete="CASCADE"), nullable=False
    )

    membership: Mapped[Membership] = relationship(back_populates="vendor_scopes")
    vendor: Mapped[Vendor] = relationship()


class Session(Base, TimestampMixin):
    """Server-side session record.

    Sessions live in PostgreSQL rather than in a signed cookie so that *revocation
    is immediate* - disabling a user, revoking a membership or a compliance
    incident must end access now, which a stateless JWT cannot guarantee until it
    expires. The cookie carries only an opaque random token; this table stores its
    SHA-256, so a database leak does not yield usable session tokens.

    Two independent expiries are tracked (plan.md §15.1): idle timeout for
    unattended workstations and an absolute cap that forces periodic
    re-authentication regardless of activity.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        Index("ix_sessions_user_active", "user_id", "revoked_at"),
        Index("ix_sessions_absolute_expires_at", "absolute_expires_at"),
        CheckConstraint("absolute_expires_at > issued_at", name="absolute_expiry_after_issue"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Sha256, nullable=False)

    #: The tenant the user is currently acting in. Nullable for a platform admin
    #: or a user who has not yet chosen a context.
    active_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.tenants.id", ondelete="CASCADE"), nullable=True
    )

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    #: When the second factor was last satisfied. Privileged actions require this
    #: to be recent (plan.md §5.2 "forced re-authentication for sensitive
    #: administrative actions"), independent of session validity.
    mfa_satisfied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reauthenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: Rotation chain. A new session id is minted on privilege change and after
    #: login, defeating session fixation; the predecessor is kept briefly for
    #: forensics.
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    #: Hashed, not raw. An IP address is personal data under GDPR/DPDP and we
    #: only ever need equality comparison for anomaly detection (plan.md §15.2).
    ip_hash: Mapped[str | None] = mapped_column(Sha256, nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(Sha256, nullable=True)

    #: Refresh token for the federated case, hashed. Rotated on every use; reuse
    #: of a spent token revokes the whole chain.
    refresh_token_hash: Mapped[str | None] = mapped_column(Sha256, nullable=True)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship()


class Invitation(Base, TenantMixin, TimestampMixin, ActorMixin):
    """Invite-only onboarding (plan.md §5.2 - there is no self-service signup).

    The emailed token is single-use and stored only as a hash, so the invitation
    record cannot be replayed by anyone with database access.
    """

    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
        tenant_lookup_index("invitations", "status"),
        Index("ix_invitations_email_lower", text("lower(email)")),
        CheckConstraint("expires_at > created_at", name="invitation_expiry_after_creation"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[Role] = mapped_column(pg_enum(Role), nullable=False)
    status: Mapped[InvitationStatus] = mapped_column(
        pg_enum(InvitationStatus), nullable=False, default=InvitationStatus.PENDING
    )
    token_hash: Mapped[str] = mapped_column(Sha256, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Brand and vendor scope to apply on acceptance, as codes rather than ids so
    #: an invitation stays valid if a brand is recreated during onboarding.
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PasswordResetToken(Base, TimestampMixin):
    """Single-use password reset. Hashed token, short expiry, one live token per user."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
        Index("ix_password_reset_tokens_user", "user_id", "consumed_at"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Sha256, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_ip_hash: Mapped[str | None] = mapped_column(Sha256, nullable=True)


class LoginAttempt(Base):
    """Append-only record of authentication attempts.

    Drives lockout and gives the security team something to investigate with.
    The identifier is hashed because a failed-login table is otherwise a list of
    valid email addresses, and ``outcome``/``failure_reason`` are enumerated so a
    log line can never carry a submitted password fragment.
    """

    __tablename__ = "login_attempts"
    __rls__: ClassVar[str | None] = None
    __table_args__ = (
        # Lockout, and the only query on the hot path. It runs *before* the tenant
        # is known, so `identifier_hash` has to lead - a tenant-first index would
        # be unusable here no matter how the rest of the table is queried.
        Index("ix_login_attempts_identifier_at", "identifier_hash", "attempted_at"),
        # Retention purge, which is cross-tenant by definition.
        Index("ix_login_attempts_at", "attempted_at"),
        # "Show me failed logins for my organisation", from the tenant security
        # console. Partial because the overwhelming majority of rows are written
        # pre-authentication with no tenant at all, and indexing those NULLs would
        # triple the index for entries this query never visits.
        Index(
            "ix_login_attempts_tenant_at",
            "tenant_id",
            desc("attempted_at"),
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    identifier_hash: Mapped[str] = mapped_column(Sha256, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    succeeded: Mapped[bool] = mapped_column(nullable=False)
    #: Enumerated reason - ``BAD_CREDENTIAL``, ``LOCKED``, ``DISABLED``,
    #: ``MFA_FAILED``, ``UNKNOWN_USER``, ``TENANT_SUSPENDED``.
    failure_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(Sha256, nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(Sha256, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Not `index=True`: the indexes on this column are declared in
    #: `__table_args__` above, where their purpose can be written down.
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class IdentityProvider(Base, TimestampMixin, ActorMixin, VersionMixin):
    """OIDC configuration.

    ``tenant_id`` is nullable: a null row is the platform-wide default provider,
    a non-null row is a tenant that brings its own Entra ID or Keycloak realm.
    This is *not* ``TenantMixin`` - the nullability is the point, and a platform
    admin must be able to read the default row without a tenant context.

    The client secret is stored as a *reference* (a secret-manager key or
    environment variable name), never the secret itself: plan.md §15 forbids
    committing or persisting credentials.
    """

    __tablename__ = "identity_providers"
    __rls__: ClassVar[str | None] = None
    __table_args__ = (
        Index("uq_identity_providers_tenant", "tenant_id", unique=True),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.tenants.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[AuthProviderKind] = mapped_column(pg_enum(AuthProviderKind), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    issuer: Mapped[str] = mapped_column(String(500), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[str] = mapped_column(String(500), nullable=False, default="openid email profile")
    #: Cached discovery document, refreshed on a timer. Cached so a brief IdP
    #: outage does not become an outage here.
    discovery_cache: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    discovery_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Maps IdP group/role claims onto our roles. Advisory only: it seeds a
    #: membership at first login and is re-checked against the DB thereafter, so
    #: a tampered token cannot escalate (docs/PLAN_REVIEW.md F-3).
    role_claim_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    auto_provision: Mapped[bool] = mapped_column(nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)


class ApiKey(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """Service-to-service credential for automated dataset delivery.

    Enterprise integrations should not drive a browser. A key is scoped exactly
    like a membership (role plus brand/vendor scope) so an integration cannot see
    more than the human equivalent. Only the hash and a short display prefix are
    stored - the full key is returned once, at creation.
    """

    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        tenant_lookup_index("api_keys", "revoked_at"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    key_hash: Mapped[str] = mapped_column(Sha256, nullable=False)
    role: Mapped[Role] = mapped_column(pg_enum(Role), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Optional CIDR allowlist, stored as text to avoid a dialect-specific type
    #: in the ORM layer; validated on write.
    allowed_cidrs: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)


class DelegatedAccessGrant(Base, TenantMixin, TimestampMixin, ActorMixin, EffectiveDatedMixin):
    """Time-boxed elevation, e.g. a support engineer granted read access.

    Standing broad access is the thing audits object to. Every grant here has an
    end date, a stated reason and an approver, and the effective-dated mixin's
    ``[from, to)`` interval is what the authorization layer checks - an expired
    grant needs no revocation job to stop working.
    """

    __tablename__ = "delegated_access_grants"
    __table_args__ = (
        effective_range_check(),
        # The docstring promises "every grant here has an end date". Without this
        # the mixin's nullable ``effective_to`` makes standing access one omitted
        # field away, which is the exact finding an access review would raise.
        CheckConstraint("effective_to IS NOT NULL", name="grant_is_time_boxed"),
        tenant_lookup_index(
            "delegated_access_grants",
            "grantee_user_id",
            "effective_from",
            # Explicit short name: the derived one is 64 characters and Postgres
            # truncates at 63 without saying so.
            name="grantee_window",
        ),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    grantee_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(pg_enum(Role), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    approved_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_open_ended(self) -> bool:
        """Always ``False`` by construction; kept explicit for reviewers."""
        return self.effective_to is None


__all__ = [
    "ApiKey",
    "DelegatedAccessGrant",
    "IdentityProvider",
    "Invitation",
    "LoginAttempt",
    "Membership",
    "MembershipBrandScope",
    "MembershipVendorScope",
    "PasswordResetToken",
    "Session",
    "User",
]
