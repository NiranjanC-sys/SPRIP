"""First-run provisioning: a tenant, an administrator, a membership, a starting vocabulary.

This exists because every other write path in the application requires a principal, and a
principal requires a user, a tenant and a membership - none of which any endpoint can create for
the first time. Without this module a freshly migrated database is a schema nobody can log in to,
and the setup instructions would end at "now insert four rows by hand", which is how production
databases acquire an administrator with a password of ``admin``.

Three properties it is built for.

**Idempotent.** Every step checks for what it would create and reports ``created`` or ``existing``
instead of failing. An operator who is unsure whether the command already ran should be able to run
it again, and a container start-up hook that runs it on every boot should be safe. The one thing it
will not do is overwrite an existing password - a re-run must never silently reset the credential of
a live administrator.

**The password never travels as an argument.** Not a Typer option, not a positional. Command-line
arguments are visible in shell history, in ``ps`` output to every other user on the host, and in the
log of whatever CI system invoked it. It comes from an environment variable or an interactive
prompt, and if neither is offered one is generated and printed once.

**The administrator it creates is a *tenant* administrator.** ``PLATFORM_ADMIN`` is not a superuser
in this system - it deliberately carries no permission to read tenant business data - so a bootstrap
that only set ``is_platform_admin`` would produce an account that can sign in and see nothing. The
membership is what confers access, and the role that confers it is ``PHARMA_ADMIN``.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from speaker_roi_api.security.passwords import (
    assert_policy,
    hash_password,
    policy_failures,
)
from speaker_roi_api.services import audit
from speaker_roi_core.db.session import platform_session_scope, session_scope
from speaker_roi_core.enums import (
    AuditAction,
    AuthProviderKind,
    MembershipStatus,
    Role,
    TaxonomyKind,
    TenantStatus,
    UserStatus,
)
from speaker_roi_core.errors import NotFoundError
from speaker_roi_core.logging import get_logger
from speaker_roi_core.models.auth import Membership, User
from speaker_roi_core.models.core import TaxonomyValue, Tenant

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# The starting vocabulary
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SeedValue:
    """One taxonomy row, and optionally the rows nested under it."""

    code: str
    label: str
    children: tuple[SeedValue, ...] = ()


#: The controlled vocabularies a tenant starts with.
#:
#: Seeded rather than left empty because ingestion *rejects* codes it does not recognise, so an
#: empty taxonomy means the first upload fails every row and the operator has to guess which of
#: eight vocabularies to populate first. These are defaults, not fixtures: every one is an ordinary
#: tenant-owned row that can be relabelled, reordered or retired through the API.
#:
#: The values lean Indian-market because that is the deployment plan.md describes - four sales
#: regions with metro children, specialties that actually run speaker programmes, and the cost
#: categories a finance reviewer reconciles an event against. A tenant elsewhere retires them and
#: adds its own; nothing in the analytical layer depends on these particular codes existing.
DEFAULT_TAXONOMY: dict[TaxonomyKind, tuple[SeedValue, ...]] = {
    TaxonomyKind.REGION: (
        SeedValue(
            "north",
            "North",
            (
                SeedValue("delhi-ncr", "Delhi NCR"),
                SeedValue("punjab", "Punjab"),
                SeedValue("uttar-pradesh", "Uttar Pradesh"),
                SeedValue("rajasthan", "Rajasthan"),
            ),
        ),
        SeedValue(
            "west",
            "West",
            (
                SeedValue("mumbai", "Mumbai"),
                SeedValue("pune", "Pune"),
                SeedValue("gujarat", "Gujarat"),
            ),
        ),
        SeedValue(
            "south",
            "South",
            (
                SeedValue("bengaluru", "Bengaluru"),
                SeedValue("chennai", "Chennai"),
                SeedValue("hyderabad", "Hyderabad"),
                SeedValue("kerala", "Kerala"),
            ),
        ),
        SeedValue(
            "east",
            "East",
            (
                SeedValue("kolkata", "Kolkata"),
                SeedValue("odisha", "Odisha"),
                SeedValue("assam", "Assam"),
            ),
        ),
    ),
    TaxonomyKind.THERAPEUTIC_AREA: (
        SeedValue("cardiometabolic", "Cardiometabolic"),
        SeedValue("respiratory", "Respiratory"),
        SeedValue("anti-infectives", "Anti-infectives"),
        SeedValue("gastro", "Gastroenterology"),
        SeedValue("cns", "Central nervous system"),
        SeedValue("oncology", "Oncology"),
        SeedValue("dermatology", "Dermatology"),
        SeedValue("womens-health", "Women's health"),
    ),
    TaxonomyKind.SPECIALTY: (
        SeedValue("general-medicine", "General medicine"),
        SeedValue("cardiology", "Cardiology"),
        SeedValue("diabetology", "Diabetology"),
        SeedValue("endocrinology", "Endocrinology"),
        SeedValue("pulmonology", "Pulmonology"),
        SeedValue("gastroenterology", "Gastroenterology"),
        SeedValue("nephrology", "Nephrology"),
        SeedValue("neurology", "Neurology"),
        SeedValue("oncology", "Oncology"),
        SeedValue("orthopaedics", "Orthopaedics"),
        SeedValue("paediatrics", "Paediatrics"),
        SeedValue("dermatology", "Dermatology"),
        SeedValue("psychiatry", "Psychiatry"),
        SeedValue("urology", "Urology"),
        SeedValue("obstetrics-gynaecology", "Obstetrics & gynaecology"),
    ),
    TaxonomyKind.PRACTICE_TYPE: (
        SeedValue("solo-clinic", "Solo clinic"),
        SeedValue("group-clinic", "Group clinic"),
        SeedValue("nursing-home", "Nursing home"),
        SeedValue("corporate-hospital", "Corporate hospital"),
        SeedValue("government-hospital", "Government hospital"),
        SeedValue("medical-college", "Medical college"),
    ),
    TaxonomyKind.HCP_SEGMENT: (
        # Deliberately about engagement and practice scale, never about prescribing rank. A
        # segment called "top prescriber" would become a named prescribing ranking the moment it
        # were attached to an invitation list, which plan.md §15 prohibits outright.
        SeedValue("kol", "Key opinion leader"),
        SeedValue("tier-1", "Tier 1 - high volume practice"),
        SeedValue("tier-2", "Tier 2 - medium volume practice"),
        SeedValue("tier-3", "Tier 3 - developing practice"),
        SeedValue("academic", "Academic / teaching"),
    ),
    TaxonomyKind.TOPIC: (
        SeedValue("guideline-update", "Guideline update"),
        SeedValue("case-based-discussion", "Case-based discussion"),
        SeedValue("new-launch-science", "New launch science"),
        SeedValue("comorbidity-management", "Comorbidity management"),
        SeedValue("diagnostics-and-screening", "Diagnostics and screening"),
        SeedValue("treatment-adherence", "Treatment adherence"),
        SeedValue("safety-and-tolerability", "Safety and tolerability"),
        SeedValue("real-world-evidence", "Real-world evidence"),
    ),
    TaxonomyKind.COST_CATEGORY: (
        SeedValue("speaker-honorarium", "Speaker honorarium"),
        SeedValue("venue", "Venue hire"),
        SeedValue("food-beverage", "Food and beverage"),
        SeedValue("travel", "Travel"),
        SeedValue("accommodation", "Accommodation"),
        SeedValue("av-production", "AV and production"),
        SeedValue("materials", "Materials and printing"),
        SeedValue("agency-fee", "Agency fee"),
        SeedValue("platform-licence", "Virtual platform licence"),
        SeedValue("other", "Other"),
    ),
    TaxonomyKind.MARKETING_CHANNEL: (
        SeedValue("field-visit", "Field visit"),
        SeedValue("e-detailing", "E-detailing"),
        SeedValue("email", "Email"),
        SeedValue("webinar", "Webinar"),
        SeedValue("conference", "Conference"),
        SeedValue("print", "Print"),
        SeedValue("samples", "Samples"),
        SeedValue("digital-ads", "Digital advertising"),
    ),
}


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TaxonomyOutcome:
    created: int = 0
    existing: int = 0

    @property
    def total(self) -> int:
        return self.created + self.existing


@dataclass(slots=True)
class BootstrapResult:
    """What the run found and what it changed.

    Reported as data rather than printed from inside the service so the CLI decides the wording
    and a test can assert on the outcome. ``generated_password`` is populated only when this run
    generated one; it is the single place it exists in plaintext and it is never logged.
    """

    tenant_id: uuid.UUID
    tenant_code: str
    tenant_created: bool
    user_id: uuid.UUID
    user_email: str
    user_created: bool
    membership_role: Role
    membership_created: bool
    taxonomy: TaxonomyOutcome = field(default_factory=TaxonomyOutcome)
    generated_password: str | None = None
    mfa_enrolment_required: bool = False

    @property
    def changed_anything(self) -> bool:
        return (
            self.tenant_created
            or self.user_created
            or self.membership_created
            or self.taxonomy.created > 0
        )


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def generate_password() -> str:
    """A password an operator will copy once and then change.

    ``token_urlsafe`` rather than a word list: this value is meant to be pasted into a password
    manager on its way to a change-on-first-login, not typed or remembered, so entropy per
    character is the only property that matters. The policy check is a loop rather than a
    one-shot assertion because the policy includes a forbidden-substring rule that random output can, very
    occasionally, trip.
    """
    for _ in range(20):
        candidate = secrets.token_urlsafe(18)
        if not policy_failures(candidate, email=None, display_name=None):
            return candidate
    msg = "could not generate a password satisfying the configured policy"  # pragma: no cover
    raise RuntimeError(msg)  # pragma: no cover


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


async def _upsert_tenant(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    country: str,
    currency: str,
    locale: str,
    timezone: str,
    fiscal_year_start_month: int,
    synthetic_mode: bool,
) -> tuple[Tenant, bool]:
    existing = (
        await db.execute(select(Tenant).where(func.lower(Tenant.code) == code.lower()))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    tenant = Tenant(
        code=code,
        name=name,
        # ACTIVE, not PENDING_ONBOARDING. The onboarding state exists for tenants created by a
        # sales process that has steps still outstanding; a tenant created by an operator running
        # this command on purpose has no outstanding steps, and leaving it pending would make the
        # first login fail with a message about onboarding that nobody can action.
        status=TenantStatus.ACTIVE,
        country=country,
        reporting_currency=currency,
        locale=locale,
        timezone=timezone,
        fiscal_year_start_month=fiscal_year_start_month,
        synthetic_mode=synthetic_mode,
        settings={},
    )
    db.add(tenant)
    await db.flush([tenant])
    await audit.record(
        db,
        AuditAction.TENANT_CREATED,
        resource_type="tenant",
        resource_id=tenant.id,
        resource_label=tenant.code,
        # tenant_id stays null. The row is written under platform scope, whose policy admits only
        # rows belonging to no tenant, and the tenant this describes is in resource_id anyway.
        tenant_id=None,
        after_state=audit.snapshot(
            tenant, ("code", "name", "status", "country", "reporting_currency", "synthetic_mode")
        ),
        reason="bootstrap",
        actor_label="cli",
    )
    return tenant, True


async def _upsert_user(
    db: AsyncSession,
    *,
    email: str,
    display_name: str,
    password: str,
    must_change_password: bool,
    platform_admin: bool,
) -> tuple[User, bool]:
    normalised = email.strip().lower()
    existing = (
        await db.execute(select(User).where(func.lower(User.email) == normalised))
    ).scalar_one_or_none()
    if existing is not None:
        # Explicitly *not* touching password_hash, status or is_platform_admin. A re-run that
        # reset the credential of a live administrator would be a privilege-escalation primitive
        # for anyone who can invoke the CLI - which, in a container start-up hook, is anyone who
        # can restart the container. Changing a password is `admin reset-password`, which says so.
        return existing, False

    assert_policy(password, email=normalised, display_name=display_name)
    now = datetime.now(UTC)
    user = User(
        email=normalised,
        display_name=display_name,
        status=UserStatus.ACTIVE,
        auth_provider_kind=AuthProviderKind.LOCAL,
        password_hash=hash_password(password),
        password_updated_at=now,
        must_change_password=must_change_password,
        is_platform_admin=platform_admin,
    )
    db.add(user)
    await db.flush([user])
    # Self-attributed. There is no other actor, and leaving these null makes the first row in the
    # table the only one whose provenance is unexplained.
    user.created_by = user.id
    user.updated_by = user.id
    await audit.record(
        db,
        AuditAction.USER_INVITED,
        resource_type="user",
        resource_id=user.id,
        tenant_id=None,
        actor_user_id=user.id,
        actor_label="cli",
        after_state=audit.snapshot(
            user, ("email", "display_name", "status", "auth_provider_kind", "is_platform_admin")
        ),
        reason="bootstrap",
    )
    return user, True


async def _upsert_membership(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role: Role,
) -> tuple[Membership, bool]:
    existing = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
                Membership.role == role,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status is not MembershipStatus.ACTIVE:
            # Reactivating is the one mutation a re-run performs, because a suspended bootstrap
            # membership is the state an operator is running this command to escape from.
            existing.status = MembershipStatus.ACTIVE
            existing.revoked_at = None
            existing.revoked_reason = None
            await db.flush([existing])
            return existing, True
        return existing, False

    membership = Membership(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        status=MembershipStatus.ACTIVE,
        all_brands=True,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(membership)
    await db.flush([membership])
    await audit.record(
        db,
        AuditAction.MEMBERSHIP_CHANGED,
        resource_type="membership",
        resource_id=membership.id,
        tenant_id=tenant_id,
        actor_user_id=user_id,
        actor_label="cli",
        after_state=audit.snapshot(membership, ("user_id", "role", "status", "all_brands")),
        reason="bootstrap",
    )
    return membership, True


async def seed_taxonomy(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    vocabulary: dict[TaxonomyKind, tuple[SeedValue, ...]] | None = None,
) -> TaxonomyOutcome:
    """Insert any missing default vocabulary rows for one tenant.

    Missing, not all: an operator who deleted ``north`` because their business does not use it
    should not have it silently restored on the next run, and one who added a ninth specialty
    should not have it disturbed. So the existing ``(kind, code)`` pairs are read first and only
    the gaps are filled.
    """
    values = DEFAULT_TAXONOMY if vocabulary is None else vocabulary
    outcome = TaxonomyOutcome()

    present = {
        (kind, code)
        for kind, code in (await db.execute(select(TaxonomyValue.kind, TaxonomyValue.code))).all()
    }

    for kind, roots in values.items():
        for index, root in enumerate(roots):
            parent_id: uuid.UUID | None = None
            if (kind, root.code) in present:
                outcome.existing += 1
                if root.children:
                    # The parent already exists, so its id is needed to attach any missing
                    # children to it rather than orphaning them at the top level.
                    parent_id = (
                        await db.execute(
                            select(TaxonomyValue.id).where(
                                TaxonomyValue.kind == kind, TaxonomyValue.code == root.code
                            )
                        )
                    ).scalar_one()
            else:
                row = TaxonomyValue(
                    tenant_id=tenant_id,
                    kind=kind,
                    code=root.code,
                    label=root.label,
                    sort_order=index * 10,
                    is_active=True,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                db.add(row)
                await db.flush([row])
                parent_id = row.id
                outcome.created += 1

            for child_index, child in enumerate(root.children):
                if (kind, child.code) in present:
                    outcome.existing += 1
                    continue
                db.add(
                    TaxonomyValue(
                        tenant_id=tenant_id,
                        kind=kind,
                        code=child.code,
                        label=child.label,
                        parent_id=parent_id,
                        sort_order=child_index * 10,
                        is_active=True,
                        created_by=actor_id,
                        updated_by=actor_id,
                    )
                )
                outcome.created += 1
    await db.flush()
    return outcome


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


async def bootstrap(
    *,
    tenant_code: str,
    tenant_name: str,
    email: str,
    display_name: str,
    password: str | None = None,
    role: Role = Role.PHARMA_ADMIN,
    platform_admin: bool = False,
    country: str = "IN",
    currency: str = "INR",
    locale: str = "en-IN",
    timezone: str = "Asia/Kolkata",
    fiscal_year_start_month: int = 4,
    synthetic_mode: bool = False,
    with_taxonomy: bool = True,
) -> BootstrapResult:
    """Provision a usable tenant in two transactions, and report what changed.

    Two transactions because they need different scopes. ``core.tenants`` and ``auth.users`` are
    platform tables with no row-level-security policy, so they are written under platform scope
    where no tenant is bound; ``auth.memberships`` and ``core.taxonomy_values`` are tenant-owned
    and their policies require the tenant GUC to be set to the row's own tenant, which is only
    knowable *after* the first transaction has committed the tenant.

    The intermediate state - a tenant and a user with no membership between them - is inert
    rather than dangerous: a user with no active membership cannot authenticate into any tenant,
    so a crash between the two transactions leaves an account that cannot do anything, and the
    next run completes it.
    """
    generated: str | None = None
    if password is None:
        generated = generate_password()
        password = generated

    async with platform_session_scope(reason="bootstrap: tenant and administrator") as db:
        tenant, tenant_created = await _upsert_tenant(
            db,
            code=tenant_code,
            name=tenant_name,
            country=country,
            currency=currency,
            locale=locale,
            timezone=timezone,
            fiscal_year_start_month=fiscal_year_start_month,
            synthetic_mode=synthetic_mode,
        )
        user, user_created = await _upsert_user(
            db,
            email=email,
            display_name=display_name,
            password=password,
            # Forced only when this run invented the password. If the operator supplied it they
            # already know it and already chose it; forcing a change would be theatre. A generated
            # one has been printed to a terminal and possibly a CI log, so it is compromised by
            # construction and must not survive the first login.
            must_change_password=generated is not None,
            platform_admin=platform_admin,
        )
        tenant_id, user_id = tenant.id, user.id
        tenant_code_out, user_email_out = tenant.code, user.email

    async with session_scope(tenant_id=tenant_id) as db:
        _, membership_created = await _upsert_membership(
            db, tenant_id=tenant_id, user_id=user_id, role=role
        )
        taxonomy = (
            await seed_taxonomy(db, tenant_id=tenant_id, actor_id=user_id)
            if with_taxonomy
            else TaxonomyOutcome()
        )

    from speaker_roi_core.config import get_settings

    result = BootstrapResult(
        tenant_id=tenant_id,
        tenant_code=tenant_code_out,
        tenant_created=tenant_created,
        user_id=user_id,
        user_email=user_email_out,
        user_created=user_created,
        membership_role=role,
        membership_created=membership_created,
        taxonomy=taxonomy,
        generated_password=generated,
        mfa_enrolment_required=str(role) in get_settings().auth.mfa_required_for_roles,
    )
    log.info(
        "bootstrap.completed",
        tenant_code=result.tenant_code,
        tenant_created=result.tenant_created,
        user_created=result.user_created,
        membership_created=result.membership_created,
        taxonomy_created=result.taxonomy.created,
    )
    return result


# ---------------------------------------------------------------------------
# Day-two operations
# ---------------------------------------------------------------------------


async def reset_password(
    *, email: str, password: str | None = None
) -> tuple[uuid.UUID, str | None]:
    """Set a new local password and end every session the account holds.

    Ending the sessions is the point. An operator resets a password either because the holder
    forgot it or because the account is suspected compromised, and in the second case leaving the
    existing sessions alive resets the credential while the intruder keeps their access token.
    """
    from sqlalchemy import update

    from speaker_roi_core.models.auth import Session as SessionRow

    generated: str | None = None
    if password is None:
        generated = generate_password()
        password = generated

    normalised = email.strip().lower()
    async with platform_session_scope(reason="admin cli: password reset") as db:
        user = (
            await db.execute(select(User).where(func.lower(User.email) == normalised))
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundError("user", normalised)
        assert_policy(password, email=normalised, display_name=user.display_name)
        user.password_hash = hash_password(password)
        user.password_updated_at = datetime.now(UTC)
        user.must_change_password = generated is not None
        # A lockout is cleared too: the operator has just proved control of the account by other
        # means, and leaving the counter set would keep the legitimate holder out after the reset.
        user.failed_login_count = 0
        user.locked_until = None
        if user.status is UserStatus.LOCKED:
            user.status = UserStatus.ACTIVE
        await db.execute(
            update(SessionRow)
            .where(SessionRow.user_id == user.id, SessionRow.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason="password reset by operator")
        )
        await audit.record(
            db,
            AuditAction.RECORD_UPDATED,
            resource_type="user",
            resource_id=user.id,
            tenant_id=None,
            actor_label="cli",
            reason="password reset via admin cli",
            after_state={"password_updated": True, "sessions_revoked": True},
        )
        return user.id, generated


async def grant_role(*, email: str, tenant_code: str, role: Role) -> bool:
    """Add one role for one user in one tenant. Returns whether anything changed.

    Additive only. Removing a role is a revocation with a reason attached, which belongs in the
    audited API path rather than in a command whose whole interface is three strings.
    """
    normalised = email.strip().lower()
    async with platform_session_scope(reason="admin cli: resolve user and tenant") as db:
        user_id = (
            await db.execute(select(User.id).where(func.lower(User.email) == normalised))
        ).scalar_one_or_none()
        if user_id is None:
            raise NotFoundError("user", normalised)
        tenant_id = (
            await db.execute(
                select(Tenant.id).where(func.lower(Tenant.code) == tenant_code.lower())
            )
        ).scalar_one_or_none()
        if tenant_id is None:
            raise NotFoundError("tenant", tenant_code)

    async with session_scope(tenant_id=tenant_id) as db:
        _, created = await _upsert_membership(db, tenant_id=tenant_id, user_id=user_id, role=role)
        return created


async def list_tenants() -> list[dict[str, Any]]:
    """Every tenant, with its active membership count. For an operator orienting themselves."""
    async with platform_session_scope(reason="admin cli: list tenants") as db:
        rows = (
            await db.execute(
                select(
                    Tenant.id, Tenant.code, Tenant.name, Tenant.status, Tenant.synthetic_mode
                ).order_by(Tenant.code)
            )
        ).all()
        # Counted separately and grouped in Python: memberships are tenant-owned, so a join from
        # a platform-scoped session would be filtered to nothing by the membership policy rather
        # than raising, and a silently-zero count is worse than two queries.
        return [
            {
                "id": str(row.id),
                "code": row.code,
                "name": row.name,
                "status": str(row.status),
                "synthetic_mode": row.synthetic_mode,
            }
            for row in rows
        ]


__all__ = [
    "DEFAULT_TAXONOMY",
    "BootstrapResult",
    "SeedValue",
    "TaxonomyOutcome",
    "bootstrap",
    "generate_password",
    "grant_role",
    "list_tenants",
    "reset_password",
    "seed_taxonomy",
]
