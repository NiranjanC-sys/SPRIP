"""Tenant, master-data, exposure and outcome tables.

This is the conformed layer: everything here has already passed ingestion
validation and been resolved to master identifiers. Three conventions matter and
are load-bearing for the rest of the product:

**Codes, not names, are the business key.** ``brand_code``, ``event_code`` and
``master_hcp_id`` are tenant-scoped unique; UUIDs are internal (plan.md §9). This
is what lets a customer re-upload a corrected file and have it land on the same
row instead of creating a duplicate.

**Controlled vocabularies live in ``core.taxonomy_values``, not in free text.**
Region, therapeutic area, specialty, topic and cost category are tenant-scoped
lists. Storing the code and validating against the taxonomy is what makes the
"same topic across brands" comparison in the portfolio view mean anything.

**Every outcome row records whether it was observed.** ``hcp_rx_monthly`` carries
``is_observed`` and ``coverage_factor`` because the difference between "this
prescriber wrote nothing" and "this month was not reported" is the difference
between a valid and an invalid causal estimate (plan.md §10.2). A missing row is
missing data; a row with ``nrx = 0, is_observed = true`` is a real zero.

No column in this schema holds a patient identifier, a prescriber phone number, a
postal address or an ABHA number. plan.md §15 forbids ingesting them, and the
ingestion contracts reject files that offer them.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from speaker_roi_core.db.base import (
    ActorMixin,
    Base,
    EffectiveDatedMixin,
    TenantMixin,
    TimestampMixin,
    VersionMixin,
    effective_range_check,
    recency_index,
    tenant_code_unique,
    tenant_lookup_index,
    uuid_pk,
)
from speaker_roi_core.db.types import (
    JSONB,
    Currency,
    Fraction,
    Measure,
    Money,
    Sha256,
    pg_enum,
)
from speaker_roi_core.enums import (
    ApprovalStatus,
    AttendanceStatus,
    AttendanceVerificationSource,
    CampaignStatus,
    EventFormat,
    EventStatus,
    EventWorkflowStatus,
    ExclusionReason,
    FinanceScenario,
    IdentityMatchStatus,
    InvitationChannel,
    MatchMethod,
    TaxonomyKind,
    TenantStatus,
    VendorStatus,
)
from speaker_roi_core.enums import DatasetAccess as DatasetAccessEnum
from speaker_roi_core.enums import DatasetType as DatasetTypeEnum

if TYPE_CHECKING:
    from speaker_roi_core.models.auth import Membership

#: Stands in for "not attributable to any brand" where a nullable brand column
#: would otherwise have to sit in a primary key. The nil UUID matches no row in
#: ``core.brands``, so brand joins simply exclude it rather than silently
#: crediting the pressure to whichever brand sorted first.
UNATTRIBUTED_BRAND_ID = uuid.UUID(int=0)

# ===========================================================================
# Platform reference data
# ===========================================================================


class Currency_(Base, TimestampMixin):
    """ISO-4217 reference list. Platform-wide, read-only to tenants.

    Validating a currency against a real list at ingestion time is cheap and
    stops ``"Rs"`` or ``"INR "`` from reaching the FX join, where it would fail
    silently and drop cost rows out of the ROI denominator.
    """

    __tablename__ = "currencies"
    __rls__: ClassVar[str | None] = None
    __table_args__ = ({"schema": "core"},)

    code: Mapped[str] = mapped_column(Currency, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    #: Number of decimal places the currency actually uses (JPY has 0, INR 2).
    minor_units: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    symbol: Mapped[str | None] = mapped_column(String(8), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class FxRate(Base, TimestampMixin, ActorMixin):
    """Dated exchange rates for cross-currency portfolio roll-ups.

    docs/PLAN_REVIEW.md F-14: a multi-country tenant records costs in local
    currency but reports in one. Converting at *the rate on the cost date* rather
    than today's rate is what makes a historical ROI number reproducible - a
    re-run next quarter must not move because the rupee did.
    """

    __tablename__ = "fx_rates"
    __rls__: ClassVar[str | None] = None
    __table_args__ = (
        UniqueConstraint(
            "base_currency", "quote_currency", "rate_date", name="uq_fx_rates_pair_date"
        ),
        Index("ix_fx_rates_lookup", "quote_currency", "base_currency", "rate_date"),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("base_currency <> quote_currency", name="rate_pair_distinct"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    base_currency: Mapped[str] = mapped_column(Currency, nullable=False)
    quote_currency: Mapped[str] = mapped_column(Currency, nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: Units of ``quote_currency`` per one unit of ``base_currency``.
    rate: Mapped[float] = mapped_column(Measure, nullable=False)
    source: Mapped[str] = mapped_column(String(60), nullable=False, default="MANUAL")


class Tenant(Base, TimestampMixin, ActorMixin, VersionMixin):
    """A customer organisation. The root of every authorization decision.

    ``synthetic_mode`` is not a debug flag - plan.md §11 requires that synthetic
    tenants be visibly labelled on every screen and export, so a demo number can
    never be mistaken for a client's real result. It is stored on the tenant so
    the badge cannot be turned off per-page.
    """

    __tablename__ = "tenants"
    __rls__: ClassVar[str | None] = None
    __table_args__ = (
        UniqueConstraint("code", name="uq_tenants_code"),
        Index("ix_tenants_status", "status"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[TenantStatus] = mapped_column(
        pg_enum(TenantStatus), nullable=False, default=TenantStatus.ACTIVE
    )
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    #: Currency every portfolio and budget figure is presented in.
    reporting_currency: Mapped[str] = mapped_column(Currency, nullable=False, default="INR")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en-IN")
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="Asia/Kolkata")
    fiscal_year_start_month: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=4)

    synthetic_mode: Mapped[bool] = mapped_column(nullable=False, default=False)

    #: Retention window for raw uploads and derived analytics (plan.md §15.2).
    data_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=2555)
    #: Tenant-level overrides: upload limits, MFA policy, evidence thresholds.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    memberships: Mapped[list[Membership]] = relationship(back_populates="tenant")


class FeatureFlag(Base, TenantMixin, TimestampMixin, ActorMixin):
    """Per-tenant capability switches (AI assistant, optimizer, vendor portal)."""

    __tablename__ = "feature_flags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_feature_flags_tenant_key"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)


class TaxonomyValue(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """Tenant-scoped controlled vocabulary (region, specialty, topic, cost category).

    plan.md §4 insists on one shared vocabulary per tenant. Free-text topics make
    "which topics work" unanswerable, so ingestion resolves against this table and
    rejects unknown codes rather than inventing values.

    ``parent_id`` supports hierarchy (city inside region, sub-specialty inside
    specialty) without a second table.
    """

    __tablename__ = "taxonomy_values"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", "code", name="uq_taxonomy_values_tenant_kind_code"),
        tenant_lookup_index("taxonomy_values", "kind", "is_active"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[TaxonomyKind] = mapped_column(pg_enum(TaxonomyKind), nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.taxonomy_values.id", ondelete="SET NULL"),
        nullable=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    #: Free-form extras, e.g. an ISO region code or a GL account for a cost category.
    attributes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


# ===========================================================================
# Commercial master data
# ===========================================================================


class Brand(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """A promoted brand. The unit that owns a budget and an ROI number."""

    __tablename__ = "brands"
    __table_args__ = (
        tenant_code_unique("brands", "code"),
        tenant_lookup_index("brands", "is_active"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Taxonomy code of kind ``THERAPEUTIC_AREA``.
    therapeutic_area_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    molecule: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    launch_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    products: Mapped[list[Product]] = relationship(back_populates="brand")


class Product(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """A sellable presentation of a brand.

    Prescription data usually arrives at product grain while measurement happens
    at brand grain; keeping both means the aggregation is auditable rather than
    assumed.
    """

    __tablename__ = "products"
    __table_args__ = (
        tenant_code_unique("products", "code"),
        tenant_lookup_index("products", "brand_id"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.brands.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    formulation: Mapped[str | None] = mapped_column(String(80), nullable=True)
    strength: Mapped[str | None] = mapped_column(String(60), nullable=True)
    pack_size: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    brand: Mapped[Brand] = relationship(back_populates="products")


class Hcp(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """A healthcare professional, at professional grain only.

    Deliberately absent: name, phone, email, address, ABHA number, any patient
    attribute. plan.md §15 prohibits ingesting them and there is no product
    requirement for them - measurement needs specialty, geography and segment,
    not identity. ``master_hcp_id`` is the tenant's own opaque identifier.
    """

    __tablename__ = "hcps"
    __table_args__ = (
        tenant_code_unique("hcps", "master_hcp_id"),
        tenant_lookup_index("hcps", "specialty_code", "region_code"),
        tenant_lookup_index("hcps", "is_active"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    master_hcp_id: Mapped[str] = mapped_column(String(80), nullable=False)
    specialty_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    practice_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: Tenant's own value tier. Never a model output - see the note on
    #: ``analytics.cohort_members`` about why scores stay out of master data.
    segment: Mapped[str | None] = mapped_column(String(60), nullable=True)
    city_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    first_seen_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class HcpIdentifier(Base, TenantMixin, TimestampMixin, ActorMixin, EffectiveDatedMixin):
    """Crosswalk from a source system's HCP id to the master record.

    Three source systems disagreeing about who a prescriber is, is the normal
    case. ``hcp_id`` is nullable so an unresolved source id can be *recorded*
    rather than dropped, which is what makes the unmatched-rate visible on the
    Data Health page instead of quietly biasing the cohort.

    An id that resolves to two masters is stored as ``AMBIGUOUS`` and never
    auto-picked (plan.md §10.2) - a wrong merge silently corrupts every downstream
    estimate.
    """

    __tablename__ = "hcp_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_system",
            "source_hcp_id",
            "effective_from",
            name="uq_hcp_identifiers_tenant_source_from",
        ),
        tenant_lookup_index("hcp_identifiers", "status"),
        tenant_lookup_index("hcp_identifiers", "hcp_id"),
        effective_range_check(),
        # One source id may only map to one master at a time. Without this the
        # crosswalk join fans out and a single prescriber's Rx history is counted
        # twice, which inflates the estimate rather than failing visibly.
        ExcludeConstraint(
            ("tenant_id", "="),
            ("source_system", "="),
            ("source_hcp_id", "="),
            (literal_column("daterange(effective_from, effective_to, '[)')"), "&&"),
            name="ex_hcp_identifiers_no_overlap",
            using="gist",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_is_probability",
        ),
        CheckConstraint(
            "status <> 'MATCHED' OR hcp_id IS NOT NULL", name="matched_requires_master"
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_system: Mapped[str] = mapped_column(String(60), nullable=False)
    source_hcp_id: Mapped[str] = mapped_column(String(120), nullable=False)
    hcp_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.hcps.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[IdentityMatchStatus] = mapped_column(
        pg_enum(IdentityMatchStatus), nullable=False
    )
    match_method: Mapped[MatchMethod] = mapped_column(pg_enum(MatchMethod), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    #: Populated for AMBIGUOUS rows so a steward can choose; a list of master ids.
    candidate_hcp_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class Vendor(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """An external agency that submits data or is paid for event costs."""

    __tablename__ = "vendors"
    __table_args__ = (
        tenant_code_unique("vendors", "code"),
        tenant_lookup_index("vendors", "status"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[VendorStatus] = mapped_column(
        pg_enum(VendorStatus), nullable=False, default=VendorStatus.ACTIVE
    )
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    #: Email domains permitted to hold a Vendor Contributor membership for this
    #: vendor. Checked at invitation time, not at login, so a compromised
    #: personal address cannot be attached to a vendor scope.
    allowed_email_domains: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    grants: Mapped[list[VendorDatasetGrant]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )


class VendorDatasetGrant(Base, TenantMixin, TimestampMixin, ActorMixin):
    """What a vendor may do with one dataset type - and it is directional.

    docs/PLAN_REVIEW.md F-8: submitting attendance must not confer the right to
    read attendance, because reading it exposes other vendors' submissions and,
    joined with outcomes, approaches a prescriber-level view. ``access`` therefore
    distinguishes write-only from read-back, and the default is write-only.
    """

    __tablename__ = "vendor_dataset_grants"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "vendor_id", "dataset_type", name="uq_vendor_dataset_grants_scope"
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.vendors.id", ondelete="CASCADE"), nullable=False
    )
    dataset_type: Mapped[DatasetTypeEnum] = mapped_column(pg_enum(DatasetTypeEnum), nullable=False)
    access: Mapped[DatasetAccessEnum] = mapped_column(
        pg_enum(DatasetAccessEnum), nullable=False, default=DatasetAccessEnum.WRITE
    )
    granted_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vendor: Mapped[Vendor] = relationship(back_populates="grants")


# ===========================================================================
# Programs
# ===========================================================================


class Campaign(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """A funded set of speaker programs pursuing one objective."""

    __tablename__ = "campaigns"
    __table_args__ = (
        tenant_code_unique("campaigns", "code"),
        tenant_lookup_index("campaigns", "brand_id", "status"),
        tenant_lookup_index("campaigns", "start_date"),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date", name="campaign_dates_ordered"
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.brands.id", ondelete="RESTRICT"), nullable=False
    )
    objective: Mapped[str | None] = mapped_column(String(200), nullable=True)
    topic_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[CampaignStatus] = mapped_column(
        pg_enum(CampaignStatus), nullable=False, default=CampaignStatus.DRAFT
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    planned_budget: Mapped[float | None] = mapped_column(Money, nullable=True)
    currency: Mapped[str | None] = mapped_column(Currency, nullable=True)

    brand: Mapped[Brand] = relationship()
    events: Mapped[list[Event]] = relationship(back_populates="campaign")


class Event(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """One speaker program occurrence. The atomic unit of measurement.

    Two status columns, on purpose:

    ``status`` is the *operational* lifecycle a coordinator manages (planned,
    completed, cancelled). ``workflow_status`` is the *measurement* lifecycle
    (awaiting attendance, awaiting outcomes, measurable, published) driven by data
    availability and review, per plan.md §6.2. Collapsing them would mean a
    cancelled event cannot also be "excluded from measurement with a reason",
    which is information the portfolio view has to show.

    ``measurement_eligible`` plus ``exclusion_reason`` is how an event leaves the
    denominator honestly. An event that is silently dropped inflates portfolio
    ROI; one marked ``INSUFFICIENT_ATTENDANCE`` is a visible, defensible gap.
    """

    __tablename__ = "events"
    __table_args__ = (
        tenant_code_unique("events", "code"),
        tenant_lookup_index("events", "brand_id", "event_date"),
        tenant_lookup_index("events", "campaign_id"),
        tenant_lookup_index("events", "workflow_status"),
        tenant_lookup_index("events", "event_date", "status"),
        Index("ix_events_tenant_topic_format", "tenant_id", "topic_code", "format"),
        CheckConstraint(
            "planned_attendance IS NULL OR planned_attendance >= 0",
            name="planned_attendance_non_negative",
        ),
        CheckConstraint(
            "measurement_eligible OR exclusion_reason IS NOT NULL",
            name="ineligible_event_states_reason",
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.campaigns.id", ondelete="SET NULL"), nullable=True
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.brands.id", ondelete="RESTRICT"), nullable=False
    )

    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(60), nullable=True)

    format: Mapped[EventFormat] = mapped_column(pg_enum(EventFormat), nullable=False)
    topic_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    venue_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    venue_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    speaker_tier: Mapped[str | None] = mapped_column(String(40), nullable=True)
    planned_attendance: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[EventStatus] = mapped_column(
        pg_enum(EventStatus), nullable=False, default=EventStatus.PROPOSED
    )
    workflow_status: Mapped[EventWorkflowStatus] = mapped_column(
        pg_enum(EventWorkflowStatus), nullable=False, default=EventWorkflowStatus.DRAFT
    )
    measurement_eligible: Mapped[bool] = mapped_column(nullable=False, default=True)
    exclusion_reason: Mapped[ExclusionReason | None] = mapped_column(
        pg_enum(ExclusionReason), nullable=True
    )
    exclusion_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    currency: Mapped[str | None] = mapped_column(Currency, nullable=True)
    data_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    campaign: Mapped[Campaign | None] = relationship(back_populates="events")
    brand: Mapped[Brand] = relationship()
    speakers: Mapped[list[EventSpeaker]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventSpeaker(Base, TenantMixin, TimestampMixin, ActorMixin):
    """Who presented, and what they were paid.

    A speaker may be an HCP on the master list or an external expert. Honorarium
    is recorded here *and* mirrored into ``event_costs`` so the ROI denominator
    has a single source; this table exists for the "which speaker tiers perform"
    question, which is a legitimate program-design question about *presenters* -
    distinct from the prohibited ranking of *attendees* by prescribing.
    """

    __tablename__ = "event_speakers"
    __table_args__ = (
        tenant_lookup_index("event_speakers", "event_id"),
        tenant_lookup_index("event_speakers", "hcp_id"),
        CheckConstraint(
            "hcp_id IS NOT NULL OR external_speaker_code IS NOT NULL",
            name="speaker_identified",
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.events.id", ondelete="CASCADE"), nullable=False
    )
    hcp_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.hcps.id", ondelete="SET NULL"), nullable=True
    )
    external_speaker_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(40), nullable=True)
    speaking_role: Mapped[str | None] = mapped_column(String(60), nullable=True)
    honorarium_amount: Mapped[float | None] = mapped_column(Money, nullable=True)
    currency: Mapped[str | None] = mapped_column(Currency, nullable=True)

    event: Mapped[Event] = relationship(back_populates="speakers")


class EventWorkflowTransition(Base, TenantMixin):
    """Append-only measurement-lifecycle history for one event.

    plan.md §6.2 requires the state machine to be auditable. Storing transitions
    rather than only the current state is what lets a reviewer answer "who
    published this, on what evidence, and when" months later.
    """

    __tablename__ = "event_workflow_transitions"
    __rls__: ClassVar[str | None] = "append_only"
    __table_args__ = (
        tenant_lookup_index("event_workflow_transitions", "event_id", "occurred_at"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.events.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[EventWorkflowStatus | None] = mapped_column(
        pg_enum(EventWorkflowStatus), nullable=True
    )
    to_status: Mapped[EventWorkflowStatus] = mapped_column(
        pg_enum(EventWorkflowStatus), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: Null actor means the transition was made by a background job; the run is
    #: named so it is still traceable.
    run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


# ===========================================================================
# Exposure
# ===========================================================================


class EventInvitation(Base, TenantMixin, TimestampMixin, ActorMixin):
    """Who was asked to attend. The source of the comparison group.

    Named ``EventInvitation`` rather than ``Invitation`` because ``auth`` already
    has a user invitation; two classes with one name in the same SQLAlchemy
    registry make string-based relationship resolution ambiguous.

    This table is why the design can support a matched control at all: invited
    non-attendees share the selection process with attendees up to the decision to
    show up, which is a far better starting point than the general prescriber
    population (plan.md §12.1). ``is_eligible`` records whether the invitee was in
    the intended universe, so an accidentally-invited ineligible HCP does not
    pollute the control pool.
    """

    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", "hcp_id", name="uq_invitations_tenant_event_hcp"),
        tenant_lookup_index("invitations", "hcp_id"),
        tenant_lookup_index("invitations", "invited_on"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.events.id", ondelete="CASCADE"), nullable=False
    )
    hcp_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.hcps.id", ondelete="RESTRICT"), nullable=False
    )
    invited_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    channel: Mapped[InvitationChannel | None] = mapped_column(
        pg_enum(InvitationChannel), nullable=True
    )
    is_eligible: Mapped[bool] = mapped_column(nullable=False, default=True)
    eligibility_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    data_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class Attendance(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """Verified participation. The treatment indicator.

    ``verified_attended`` is separate from ``registration_status`` because
    registration is an intention and attendance is a fact; measuring on
    registrations would attribute impact to people who never turned up.

    plan.md §10.2 requires duplicate attendance to be *reconciled*, not
    de-duplicated arbitrarily. The unique key is (event, HCP); when two sources
    disagree, the stronger verification source wins and
    ``reconciliation_note`` records the loser. Two equally strong sources in
    conflict are quarantined at ingestion and never reach this table.
    """

    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", "hcp_id", name="uq_attendance_tenant_event_hcp"),
        tenant_lookup_index("attendance", "event_id", "verified_attended"),
        tenant_lookup_index("attendance", "hcp_id"),
        CheckConstraint(
            "NOT verified_attended OR verification_source <> 'UNVERIFIED'",
            name="verified_requires_source",
        ),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes >= 0",
            name="duration_non_negative",
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.events.id", ondelete="CASCADE"), nullable=False
    )
    hcp_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.hcps.id", ondelete="RESTRICT"), nullable=False
    )
    registration_status: Mapped[AttendanceStatus] = mapped_column(
        pg_enum(AttendanceStatus), nullable=False
    )
    verified_attended: Mapped[bool] = mapped_column(nullable=False, default=False)
    verification_source: Mapped[AttendanceVerificationSource] = mapped_column(
        pg_enum(AttendanceVerificationSource),
        nullable=False,
        default=AttendanceVerificationSource.UNVERIFIED,
    )
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reconciliation_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


# ===========================================================================
# Outcomes and context (partitioned - see the migration)
# ===========================================================================


class HcpRxMonthly(Base, TenantMixin, TimestampMixin):
    """Monthly prescription volume per HCP, product and month.

    The largest table in the product and the one the estimators read. Declared
    ``PARTITION BY RANGE (month)`` in the migration: analysis always asks for a
    pre/post window, so range partitioning turns a full scan into a two-partition
    scan, and dropping an out-of-retention year becomes a metadata operation.

    Because a partitioned table's primary key must contain the partition key, the
    key is (tenant_id, hcp_id, product_id, month) rather than a surrogate UUID -
    which is also the natural key ingestion upserts on.

    ``is_observed`` and ``coverage_factor`` exist because prescription panels are
    samples, not censuses. plan.md §12.4 requires stating coverage rather than
    projecting silently: a 60%-coverage month is usable with a stated caveat, a
    missing month is not usable at all, and the two must never look alike.
    """

    __tablename__ = "hcp_rx_monthly"
    __table_args__ = (
        Index(
            "ix_hcp_rx_monthly_tenant_hcp_brand_month",
            "tenant_id",
            "hcp_id",
            "brand_id",
            "month",
        ),
        Index("ix_hcp_rx_monthly_tenant_brand_month", "tenant_id", "brand_id", "month"),
        CheckConstraint("nrx IS NULL OR nrx >= 0", name="nrx_non_negative"),
        CheckConstraint("trx IS NULL OR trx >= 0", name="trx_non_negative"),
        CheckConstraint(
            "coverage_factor IS NULL OR (coverage_factor > 0 AND coverage_factor <= 1)",
            name="coverage_factor_is_share",
        ),
        # A genuine zero must be marked observed; an unobserved month must not
        # carry a fabricated zero (plan.md §10.2).
        CheckConstraint(
            "NOT (nrx = 0 AND NOT is_observed)",
            name="zero_outcome_must_be_observed",
        ),
        # Suppressed small cells are the only case where an observed month may
        # have a null count.
        CheckConstraint(
            "suppression_flag OR NOT is_observed OR nrx IS NOT NULL",
            name="observed_unsuppressed_has_value",
        ),
        CheckConstraint("date_trunc('month', month) = month", name="month_is_first_of_month"),
        {"schema": "core", "postgresql_partition_by": "RANGE (month)"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.tenants.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    hcp_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    month: Mapped[date] = mapped_column(Date, primary_key=True)

    #: Denormalised from ``products`` so brand-grain aggregation does not need a
    #: join on the hottest table in the system.
    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    nrx: Mapped[float | None] = mapped_column(Measure, nullable=True)
    trx: Mapped[float | None] = mapped_column(Measure, nullable=True)
    competitor_trx: Mapped[float | None] = mapped_column(Measure, nullable=True)
    market_trx: Mapped[float | None] = mapped_column(Measure, nullable=True)

    is_observed: Mapped[bool] = mapped_column(nullable=False, default=True)
    coverage_factor: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    suppression_flag: Mapped[bool] = mapped_column(nullable=False, default=False)
    #: The supplier's own metric definition, preserved verbatim (plan.md §4). A
    #: change here invalidates comparisons across the boundary and shows up as a
    #: definition-change flag on the Data Health page.
    supplier_definition_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    data_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class MarketingActivity(Base, TenantMixin, TimestampMixin):
    """Rep calls, emails and samples per HCP-month. A confounder, not an outcome.

    Without this table the estimator cannot distinguish "the program worked" from
    "the rep visited three times that quarter". Partitioned by month for the same
    reason as the Rx panel.
    """

    __tablename__ = "marketing_activity"
    __table_args__ = (
        Index("ix_marketing_activity_tenant_hcp_month", "tenant_id", "hcp_id", "month"),
        Index("ix_marketing_activity_tenant_brand_month", "tenant_id", "brand_id", "month"),
        CheckConstraint("rep_calls IS NULL OR rep_calls >= 0", name="rep_calls_non_negative"),
        CheckConstraint("date_trunc('month', month) = month", name="month_is_first_of_month"),
        {"schema": "core", "postgresql_partition_by": "RANGE (month)"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.tenants.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    hcp_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    #: Part of the key, because a multi-brand tenant genuinely has brand-specific
    #: promotion in the same HCP-month: emails about one brand and samples of
    #: another are separate confounders and must not collapse into one row.
    #:
    #: Activity that is *not* brand-attributable - a rep call covering the whole
    #: bag - is real and must still be recorded, but a NULL cannot sit in a
    #: primary key. It is stored under :data:`UNATTRIBUTED_BRAND_ID`, the nil
    #: UUID, which by construction matches no row in ``core.brands`` and so falls
    #: out of any brand join instead of silently inflating one brand's pressure.
    #: There is deliberately no foreign key on this column.
    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=text(f"'{UNATTRIBUTED_BRAND_ID}'::uuid"),
    )
    month: Mapped[date] = mapped_column(Date, primary_key=True)

    rep_calls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emails_delivered: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emails_opened: Mapped[int | None] = mapped_column(Integer, nullable=True)
    samples_dropped: Mapped[int | None] = mapped_column(Integer, nullable=True)
    other_event_exposures: Mapped[int | None] = mapped_column(Integer, nullable=True)
    digital_impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class MarketFactor(Base, TenantMixin, TimestampMixin):
    """Brand x region x month market conditions.

    Access changes, tender outcomes and competitor launches move prescribing for
    everyone. Feeding them to the estimator as covariates is what stops a
    formulary win from being reported as speaker-program ROI (plan.md §12.5).
    """

    __tablename__ = "market_factors"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "brand_id", "region_code", "month", name="uq_market_factors_grain"
        ),
        tenant_lookup_index("market_factors", "brand_id", "month"),
        CheckConstraint("date_trunc('month', month) = month", name="month_is_first_of_month"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.brands.id", ondelete="CASCADE"), nullable=False
    )
    region_code: Mapped[str] = mapped_column(String(60), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    access_index: Mapped[float | None] = mapped_column(Measure, nullable=True)
    seasonality_index: Mapped[float | None] = mapped_column(Measure, nullable=True)
    competitor_index: Mapped[float | None] = mapped_column(Measure, nullable=True)
    market_size_index: Mapped[float | None] = mapped_column(Measure, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


# ===========================================================================
# Cost and finance
# ===========================================================================


class EventCost(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """One cost line for one event. The ROI denominator.

    ``amount_base`` is the value converted into the tenant's reporting currency
    using ``fx_rate_id`` - stored, not recomputed, so a historical ROI figure does
    not drift with the exchange rate (docs/PLAN_REVIEW.md F-14).

    ``approval_status`` matters because an unapproved estimate and a settled
    invoice are different numbers, and the Finance view must be able to show ROI
    on approved cost only.
    """

    __tablename__ = "event_costs"
    __table_args__ = (
        tenant_lookup_index("event_costs", "vendor_id"),
        tenant_lookup_index("event_costs", "approval_status"),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "category_code",
            "vendor_id",
            "invoice_reference",
            name="uq_event_costs_natural",
        ),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint(
            "approval_status <> 'APPROVED' OR approved_by IS NOT NULL",
            name="approved_cost_has_approver",
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.events.id", ondelete="CASCADE"), nullable=False
    )
    #: Taxonomy code of kind ``COST_CATEGORY`` (venue, honorarium, travel, ...).
    category_code: Mapped[str] = mapped_column(String(60), nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.vendors.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[float] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(Currency, nullable=False)
    amount_base: Mapped[float | None] = mapped_column(Money, nullable=True)
    fx_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.fx_rates.id", ondelete="SET NULL"), nullable=True
    )
    invoice_reference: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        pg_enum(ApprovalStatus), nullable=False, default=ApprovalStatus.DRAFT
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Flagged by the outlier check at ingestion; kept rather than rejected so the
    #: reviewer decides, but excluded from cost benchmarks until confirmed.
    is_outlier: Mapped[bool] = mapped_column(nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    event: Mapped[Event] = relationship()


class FinanceVersion(Base, TenantMixin, TimestampMixin, ActorMixin):
    """A named, frozen set of finance assumptions.

    plan.md §14 requires every monetary result to name the assumption set it used.
    Without this, "ROI was 2.1x last quarter" and "ROI is 1.4x now" is an
    unresolvable argument - the contribution margin may simply have been revised.
    Publishing a version freezes it; changing an assumption creates a new version.
    """

    __tablename__ = "finance_versions"
    __table_args__ = (
        tenant_code_unique("finance_versions", "code"),
        tenant_lookup_index("finance_versions", "is_active"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Hash over the member assumptions, so a claim of "unchanged" is checkable.
    assumptions_checksum: Mapped[str | None] = mapped_column(Sha256, nullable=True)

    assumptions: Mapped[list[FinanceAssumption]] = relationship(back_populates="finance_version")


class FinanceAssumption(Base, TenantMixin, TimestampMixin, ActorMixin, EffectiveDatedMixin):
    """Contribution per prescription, by brand and scenario, over a date range.

    Effective-dated with a half-open ``[from, to)`` interval and a database-level
    exclusion constraint that forbids overlaps for the same brand, scenario and
    finance version. Overlapping assumptions would make the gross-contribution
    calculation depend on row order, which is exactly the kind of non-determinism
    that destroys trust in a finance report.
    """

    __tablename__ = "finance_assumptions"
    __table_args__ = (
        tenant_lookup_index("finance_assumptions", "brand_id", "scenario", "effective_from"),
        tenant_lookup_index("finance_assumptions", "finance_version_id"),
        effective_range_check(),
        ExcludeConstraint(
            ("tenant_id", "="),
            ("finance_version_id", "="),
            ("brand_id", "="),
            ("scenario", "="),
            (literal_column("daterange(effective_from, effective_to, '[)')"), "&&"),
            name="ex_finance_assumptions_no_overlap",
            using="gist",
        ),
        CheckConstraint("contribution_per_nrx >= 0", name="contribution_non_negative"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    finance_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("core.finance_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.brands.id", ondelete="CASCADE"), nullable=False
    )
    scenario: Mapped[FinanceScenario] = mapped_column(
        pg_enum(FinanceScenario), nullable=False, default=FinanceScenario.BASE
    )
    contribution_per_nrx: Mapped[float] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(Currency, nullable=False)
    #: Optional persistence assumption: how many months of the observed lift are
    #: counted as durable value. Documented as an assumption, never as a finding.
    persistence_months: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    finance_version: Mapped[FinanceVersion] = relationship(back_populates="assumptions")


class CandidateProgram(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """A proposed future program, as design inputs only.

    plan.md §7.4 is explicit: the planner accepts brand, topic, region, format,
    month, expected attendance and cost. It does **not** accept a list of named
    target prescribers, and the ingestion contract rejects such a column. Planning
    is about program design; selecting individuals by predicted prescribing is the
    compliance line this product does not cross.
    """

    __tablename__ = "candidate_programs"
    __table_args__ = (
        tenant_code_unique("candidate_programs", "code"),
        tenant_lookup_index("candidate_programs", "brand_id", "planned_month"),
        CheckConstraint("expected_attendance > 0", name="expected_attendance_positive"),
        CheckConstraint("planned_cost >= 0", name="planned_cost_non_negative"),
        CheckConstraint(
            "date_trunc('month', planned_month) = planned_month",
            name="planned_month_is_first_of_month",
        ),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.brands.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.campaigns.id", ondelete="SET NULL"), nullable=True
    )
    topic_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    format: Mapped[EventFormat] = mapped_column(pg_enum(EventFormat), nullable=False)
    planned_month: Mapped[date] = mapped_column(Date, nullable=False)
    expected_attendance: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_cost: Mapped[float] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(Currency, nullable=False)
    speaker_tier: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Set by a compliance reviewer. A candidate that is not eligible can be
    #: modelled but cannot be selected by the optimizer.
    is_compliance_eligible: Mapped[bool] = mapped_column(nullable=False, default=True)
    compliance_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_version_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    brand: Mapped[Brand] = relationship()


# ===========================================================================
# Workspace conveniences
# ===========================================================================


class SavedView(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """A named filter set for a page. Shareable within the tenant.

    Filters are stored as codes, not resolved ids, so a shared link survives a
    re-seed and cannot be used to smuggle a reference to another tenant's row.
    """

    __tablename__ = "saved_views"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "owner_user_id", "page_key", "name", name="uq_saved_views_owner_page_name"
        ),
        tenant_lookup_index("saved_views", "page_key", "is_shared"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    page_key: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_shared: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(nullable=False, default=False)


class Notification(Base, TenantMixin, TimestampMixin):
    """In-app notification: upload finished, review requested, model promoted."""

    __tablename__ = "notifications"
    __table_args__ = (
        # The unread badge: "how many for me, unread". Partial rather than full,
        # because read notifications are the overwhelming majority within days and
        # the badge never looks at them.
        Index(
            "ix_notifications_tenant_recipient_unread",
            "tenant_id",
            "recipient_user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
        # The bell dropdown: one recipient's newest items, read or not.
        recency_index("notifications", "recipient_user_id"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    link_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Set for notifications that must not be dismissed silently, e.g. a blocked
    #: publication awaiting compliance review.
    requires_action: Mapped[bool] = mapped_column(nullable=False, default=False)


__all__ = [  # noqa: RUF022 - grouped by concern, not alphabetised
    "UNATTRIBUTED_BRAND_ID",
    # reference
    "Currency_",
    "FxRate",
    "Tenant",
    "FeatureFlag",
    "TaxonomyValue",
    # commercial master data
    "Brand",
    "Product",
    "Hcp",
    "HcpIdentifier",
    "Vendor",
    "VendorDatasetGrant",
    # programs
    "Campaign",
    "Event",
    "EventSpeaker",
    "EventWorkflowTransition",
    # exposure
    "EventInvitation",
    "Attendance",
    # outcomes and context
    "HcpRxMonthly",
    "MarketingActivity",
    "MarketFactor",
    # cost and finance
    "EventCost",
    "FinanceVersion",
    "FinanceAssumption",
    "CandidateProgram",
    # workspace
    "SavedView",
    "Notification",
]
