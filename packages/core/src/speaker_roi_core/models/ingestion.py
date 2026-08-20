"""Upload sessions, validation issues and data versions.

This schema is the audit trail for *how data got here*, and it is deliberately
separate from the conformed tables in ``core``. The separation buys three things
the product depends on:

**A failed upload leaves no partial data.** Rows are validated into a staging
outcome first; a session that fails its gates commits nothing. plan.md §10.2
requires all-or-nothing per file, because a half-loaded month silently changes
every downstream estimate.

**Every conformed row can name the file it came from.** ``data_versions`` is the
lineage anchor: ``core.hcp_rx_monthly.data_version_id`` resolves to a version,
which resolves to a session, which resolves to an immutable object in storage
with a checksum. plan.md §14 requires that any published number resolve to
exactly this chain.

**The raw file is never mutated.** ``raw_objects`` records an immutable receipt;
reprocessing creates a new session against the same object rather than editing
it.

A note on content handling: plan.md §15 forbids logging file contents. Issues
therefore carry a field name, a rule code and a row number - not the offending
value - except where the contract explicitly marks a field safe to echo. The
quarantine table stores a redacted payload so a steward can still resolve a row.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from speaker_roi_core.db.base import (
    ActorMixin,
    Base,
    TenantMixin,
    TimestampMixin,
    VersionMixin,
    tenant_lookup_index,
    uuid_pk,
)
from speaker_roi_core.db.types import JSONB, Sha256, pg_enum
from speaker_roi_core.enums import (
    DatasetType,
    DataVersionStatus,
    FailureCategory,
    FileFormat,
    IdentityMatchStatus,
    IssueSeverity,
    UploadStatus,
)

if TYPE_CHECKING:
    from speaker_roi_core.models.core import Vendor


class DatasetContract(Base, TimestampMixin, ActorMixin):
    """A published, versioned schema for one dataset type.

    Platform-level, not tenant-level: the contract *is* the product's promise
    about what a file must look like, and a tenant-specific variant would make the
    downloadable template meaningless. Tenant-specific header spellings are
    handled by ``column_mappings`` instead.

    ``schema_json`` is the serialised contract the validator loads, so a stored
    upload can be re-validated later against the exact contract version it was
    accepted under - which is what makes a historical acceptance defensible.
    """

    __tablename__ = "dataset_contracts"
    __rls__: ClassVar[str | None] = None
    __table_args__ = (
        UniqueConstraint("dataset_type", "version", name="uq_dataset_contracts_type_version"),
        Index("ix_dataset_contracts_active", "dataset_type", "is_active"),
        {"schema": "ingestion"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    dataset_type: Mapped[DatasetType] = mapped_column(pg_enum(DatasetType), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    checksum: Mapped[str] = mapped_column(Sha256, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Storage keys of the generated CSV/XLSX templates offered for download.
    template_object_keys: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class RawObject(Base, TenantMixin, TimestampMixin):
    """Immutable receipt for a file placed in object storage.

    Separate from ``upload_sessions`` because the *object* and the *attempt to
    process it* have different lifetimes: a file may be reprocessed after a
    contract fix, and the retention clock runs on the object.

    The checksum is the deduplication key (plan.md §10.2). Re-uploading a
    byte-identical file returns the existing object rather than creating a second
    copy, which is what stops a nervous user clicking twice from doubling a
    month's prescriptions.
    """

    __tablename__ = "raw_objects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "checksum_sha256", name="uq_raw_objects_tenant_checksum"),
        UniqueConstraint("object_key", name="uq_raw_objects_object_key"),
        tenant_lookup_index("raw_objects", "created_at"),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        {"schema": "ingestion"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: Deterministic key: ``raw/{tenant}/{dataset_type}/{yyyy}/{mm}/{uuid}_{name}``
    #: (plan.md §8.3). Deterministic layout means a lifecycle rule can target a
    #: tenant or a month without a database lookup.
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    bucket: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(Sha256, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: Retention boundary derived from ``tenants.data_retention_days``; the
    #: purge job reads this rather than recomputing policy per object.
    retention_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    legal_hold: Mapped[bool] = mapped_column(nullable=False, default=False)


class UploadSession(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """One attempt to bring one file into one dataset.

    The state machine is ``UploadStatus`` (plan.md §10.2). Counts are recorded per
    disposition because "1,000 rows uploaded" is not an answer a data steward can
    act on - they need accepted, rejected and quarantined separately, and the sum
    must reconcile to the parsed total.

    ``idempotency_key`` lets a client retry a submission after a network failure
    without risking a duplicate load.
    """

    __tablename__ = "upload_sessions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_upload_sessions_tenant_idempotency"
        ),
        tenant_lookup_index("upload_sessions", "dataset_type", "status"),
        tenant_lookup_index("upload_sessions", "created_at"),
        tenant_lookup_index("upload_sessions", "vendor_id"),
        tenant_lookup_index("upload_sessions", "status"),
        CheckConstraint(
            "row_count_accepted + row_count_rejected + row_count_quarantined "
            "<= COALESCE(row_count_total, 0)",
            name="row_dispositions_reconcile",
        ),
        CheckConstraint(
            "status <> 'FAILED' OR failure_category IS NOT NULL",
            name="failed_session_states_category",
        ),
        {"schema": "ingestion"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    dataset_type: Mapped[DatasetType] = mapped_column(pg_enum(DatasetType), nullable=False)
    status: Mapped[UploadStatus] = mapped_column(
        pg_enum(UploadStatus), nullable=False, default=UploadStatus.CREATED
    )
    contract_version: Mapped[str] = mapped_column(String(20), nullable=False)

    raw_object_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ingestion.raw_objects.id", ondelete="RESTRICT"),
        nullable=True,
    )

    # --- submission scope -------------------------------------------------
    #: A vendor upload is bound to the vendor at session creation, from the
    #: caller's membership scope - never from a form field (plan.md §5.5).
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.vendors.id", ondelete="RESTRICT"), nullable=True
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # --- parse settings, confirmed by the user rather than guessed --------
    file_format: Mapped[FileFormat | None] = mapped_column(pg_enum(FileFormat), nullable=True)
    detected_encoding: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detected_delimiter: Mapped[str | None] = mapped_column(String(4), nullable=True)
    confirmed_delimiter: Mapped[str | None] = mapped_column(String(4), nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    header_row_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Source header -> contract field. Persisted so a re-run reproduces the same
    #: interpretation of an ambiguous file.
    column_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # --- outcome ----------------------------------------------------------
    row_count_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_count_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count_quarantined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Downloadable row-level error workbook (plan.md §10.3). Held in the private
    #: bucket and served through a short-lived authorized URL.
    error_report_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Wall-clock processing time, kept for the ingestion SLO dashboard.
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    failure_category: Mapped[FailureCategory | None] = mapped_column(
        pg_enum(FailureCategory), nullable=True
    )
    #: Operator-facing summary. Never contains a row value.
    failure_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Celery task id, so a stuck session can be traced to a worker.
    task_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    raw_object: Mapped[RawObject | None] = relationship()
    vendor: Mapped[Vendor | None] = relationship()
    issues: Mapped[list[UploadIssue]] = relationship(
        back_populates="upload_session", cascade="all, delete-orphan"
    )


class UploadIssue(Base, TenantMixin):
    """One validation finding, anchored to the original spreadsheet row.

    ``source_row_number`` is the number the user sees in Excel (1-based, counting
    the header), not a zero-based parser offset - plan.md §10.3 requires the error
    report to be actionable in the user's own file.

    Append-only: an issue is a historical fact about a validation run. Fixing the
    file produces a new session, not an edited issue.
    """

    __tablename__ = "upload_issues"
    __rls__: ClassVar[str | None] = "append_only"
    __table_args__ = (
        tenant_lookup_index("upload_issues", "upload_session_id", "severity"),
        Index("ix_upload_issues_session_row", "upload_session_id", "source_row_number"),
        Index("ix_upload_issues_code", "tenant_id", "code"),
        {"schema": "ingestion"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    upload_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ingestion.upload_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Null for file-level findings (missing column, wrong encoding).
    source_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Stable catalogue code, e.g. ``TYPE_INVALID_DATE``. The UI groups on this
    #: so a thousand identical failures read as one fixable problem.
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[IssueSeverity] = mapped_column(pg_enum(IssueSeverity), nullable=False)
    #: Rendered from a catalogue template. Names the field and the rule; echoes a
    #: value only when the contract marks that field safe (never for PII).
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    remediation: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    upload_session: Mapped[UploadSession] = relationship(back_populates="issues")


class QuarantineRow(Base, TenantMixin, TimestampMixin, ActorMixin):
    """A row held back for human judgement rather than rejected outright.

    Quarantine exists for the cases where dropping data is as wrong as accepting
    it: an ambiguous HCP crosswalk, two conflicting attendance records, a cost
    four times the category median. plan.md §10.2 requires these to surface for a
    steward rather than be resolved by a coin flip.

    ``payload_redacted`` holds the row with contract-flagged sensitive fields
    removed, which is the minimum needed to make a decision without persisting
    content the platform is not allowed to keep.
    """

    __tablename__ = "quarantine_rows"
    __table_args__ = (
        tenant_lookup_index("quarantine_rows", "upload_session_id", "resolved_at"),
        tenant_lookup_index("quarantine_rows", "reason_code"),
        {"schema": "ingestion"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    upload_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ingestion.upload_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_type: Mapped[DatasetType] = mapped_column(pg_enum(DatasetType), nullable=False)
    source_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_redacted: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: Candidate resolutions offered to the steward, e.g. the competing masters
    #: for an ambiguous crosswalk.
    options: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: ``ACCEPTED`` / ``DISCARDED`` / ``REASSIGNED`` plus the chosen option.
    resolution: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class DataVersion(Base, TenantMixin, TimestampMixin, ActorMixin):
    """An immutable, numbered state of one dataset for one tenant.

    This is the lineage anchor named in every analytical result (plan.md §14).
    Re-running an analysis against the same data version must reproduce the same
    number; that guarantee is only meaningful because versions are never edited -
    a correction supersedes rather than mutates.

    ``superseded_by_id`` forms the chain, so the Data Health page can show "you
    are looking at v7; v5 was the version behind the published Q2 result".
    """

    __tablename__ = "data_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "dataset_type", "version_number", name="uq_data_versions_tenant_type_num"
        ),
        tenant_lookup_index("data_versions", "dataset_type", "status"),
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint("row_count >= 0", name="row_count_non_negative"),
        {"schema": "ingestion"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    dataset_type: Mapped[DatasetType] = mapped_column(pg_enum(DatasetType), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DataVersionStatus] = mapped_column(
        pg_enum(DataVersionStatus), nullable=False, default=DataVersionStatus.DRAFT
    )
    upload_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ingestion.upload_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Business period the file covers, distinct from when it was loaded. A
    #: December file arriving in February is normal and must not be treated as
    #: February data.
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ingestion.data_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Hash over the committed rows. Lets a reproducibility check prove the data
    #: behind a published result has not moved.
    content_checksum: Mapped[str | None] = mapped_column(Sha256, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ColumnMappingTemplate(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """A saved source-header-to-contract-field mapping.

    Vendors send the same badly-named columns every month. Saving the mapping
    turns a ten-minute wizard into one click and, more importantly, makes the
    interpretation consistent across months - an inconsistent mapping is a silent
    data-quality defect that no validation gate can catch.
    """

    __tablename__ = "column_mapping_templates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "dataset_type", "name", name="uq_column_mapping_templates_scope_name"
        ),
        tenant_lookup_index("column_mapping_templates", "dataset_type", "is_default"),
        {"schema": "ingestion"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    dataset_type: Mapped[DatasetType] = mapped_column(pg_enum(DatasetType), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("core.vendors.id", ondelete="CASCADE"), nullable=True
    )
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: Parse hints that travel with the mapping: delimiter, encoding, sheet.
    parse_options: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_default: Mapped[bool] = mapped_column(nullable=False, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IdentityResolutionTask(Base, TenantMixin, TimestampMixin, ActorMixin):
    """A source identifier awaiting a steward's decision.

    Unmatched and ambiguous identifiers are the single largest silent source of
    bias in this kind of measurement: every unresolved prescriber is a person
    dropped from either the treated or the control arm. Queuing them makes the
    loss visible and fixable rather than invisible and permanent.
    """

    __tablename__ = "identity_resolution_tasks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_system",
            "source_hcp_id",
            name="uq_identity_resolution_tasks_source",
        ),
        tenant_lookup_index("identity_resolution_tasks", "status", "created_at"),
        {"schema": "ingestion"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_system: Mapped[str] = mapped_column(String(60), nullable=False)
    source_hcp_id: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[IdentityMatchStatus] = mapped_column(
        pg_enum(IdentityMatchStatus), nullable=False
    )
    #: Ranked master candidates with scores, for the steward's review UI.
    candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    #: How many conformed rows are blocked on this decision - the queue is sorted
    #: by impact, not by arrival.
    affected_row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    resolved_hcp_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)


__all__ = [  # noqa: RUF022 - grouped by concern, not alphabetised
    "DatasetContract",
    "RawObject",
    "UploadSession",
    "UploadIssue",
    "QuarantineRow",
    "DataVersion",
    "ColumnMappingTemplate",
    "IdentityResolutionTask",
]
