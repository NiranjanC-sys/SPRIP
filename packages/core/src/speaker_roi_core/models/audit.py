"""Audit trail, export log and data-subject erasure requests.

plan.md §15 requires an append-only audit trail covering authentication,
authorization decisions, data changes, uploads, analysis runs, publication and
model promotion. Append-only is enforced by grants in the migration - the
application role holds INSERT and SELECT and nothing else - because a trail the
application can rewrite is not a trail.

Two rules shape every column here:

**The audit records that something happened, never the sensitive content of what
happened.** plan.md §15: *"never log file contents, access tokens or sensitive
free text"*. So ``before_state``/``after_state`` hold whitelisted scalar fields,
IP addresses are hashed, and a failed login records an enumerated reason rather
than what was typed.

**Audit outlives the records it describes.** ``actor_user_id`` and
``resource_id`` are plain UUIDs, not foreign keys: a user tombstoned under an
erasure request (docs/PLAN_REVIEW.md F-15) must not cascade away the evidence of
what they did, and a deleted event must not erase the record of its deletion.

``audit.audit_events`` is range-partitioned on ``created_at``. Retention is then
a partition drop rather than a multi-million-row DELETE that locks the table
during business hours.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from speaker_roi_core.db.base import Base, TimestampMixin, uuid_pk
from speaker_roi_core.db.types import JSONB, Sha256, pg_enum
from speaker_roi_core.enums import AuditAction, AuditOutcome


class AuditEvent(Base):
    """One recorded action. Append-only, partitioned by month on ``created_at``.

    ``tenant_id`` is nullable rather than inherited from ``TenantMixin`` because
    platform-level actions genuinely have no tenant: a failed login against an
    unknown email, a platform admin creating a tenant, a retention job running
    across the estate. Forcing a synthetic tenant onto those rows would make the
    tenant filter lie.

    The RLS policy therefore reads *either* the row belongs to the current tenant
    *or* the caller is a platform admin - it is written explicitly in the
    migration rather than generated from ``__rls__``.

    The primary key includes ``created_at`` because PostgreSQL requires the
    partition key in every unique constraint on a partitioned table.
    """

    __tablename__ = "audit_events"
    __rls__: ClassVar[str | None] = "append_only"
    __table_args__ = (
        Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_events_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_events_action_created", "action", "created_at"),
        Index(
            "ix_audit_events_resource",
            "tenant_id",
            "resource_type",
            "resource_id",
            "created_at",
        ),
        Index("ix_audit_events_correlation", "correlation_id"),
        Index(
            "ix_audit_events_denied",
            "tenant_id",
            "created_at",
            postgresql_where=text("outcome = 'DENIED'"),
        ),
        CheckConstraint(
            "outcome <> 'DENIED' OR reason IS NOT NULL", name="denied_event_states_reason"
        ),
        {"schema": "audit", "postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    #: Part of the primary key: PostgreSQL requires the partition key in any
    #: unique constraint on a partitioned table.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False, server_default=text("now()")
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    action: Mapped[AuditAction] = mapped_column(pg_enum(AuditAction), nullable=False)
    outcome: Mapped[AuditOutcome] = mapped_column(
        pg_enum(AuditOutcome), nullable=False, default=AuditOutcome.SUCCESS
    )

    #: Deliberately not a foreign key - see the module docstring.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: Display label captured at the time, so the trail stays readable after the
    #: user row is tombstoned.
    actor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: The role the actor was acting under. Two people with the same identity and
    #: different roles are different actors for audit purposes.
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Set when a platform admin acted inside a tenant under a time-boxed grant.
    impersonated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    #: ``api_key`` | ``session`` | ``system`` | ``worker``.
    actor_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)

    resource_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: Human-readable identifier of the resource - an event code, a filename.
    resource_label: Mapped[str | None] = mapped_column(String(300), nullable=True)

    #: Whitelisted scalar fields only. Never a raw row, never free text a user
    #: typed, never a file's contents.
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    changed_fields: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    #: Enumerated cause for DENIED and FAILURE outcomes.
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: Hashed, not stored raw: an IP address is personal data under GDPR/DPDP and
    #: the audit use case (spotting one source hammering an endpoint) is served
    #: just as well by a stable hash.
    ip_hash: Mapped[str | None] = mapped_column(Sha256, nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(Sha256, nullable=True)
    http_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    #: Route template (``/api/v1/events/{event_id}``), never the populated path -
    #: a raw path can carry identifiers in query strings.
    route: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ExportLog(Base, TimestampMixin):
    """Every export and every authorized download of a stored object.

    plan.md §15 requires downloads to go through short-lived authorized URLs. This
    table is the other half of that control: knowing a URL was issued, to whom,
    for which object, and how many rows left the system. Exports are the most
    common exfiltration path in an analytics product, and an unlogged export is
    indistinguishable from one that never happened.

    Append-only.
    """

    __tablename__ = "export_log"
    __rls__: ClassVar[str | None] = "append_only"
    __table_args__ = (
        Index("ix_export_log_tenant_created", "tenant_id", "created_at"),
        Index("ix_export_log_user_created", "tenant_id", "user_id", "created_at"),
        Index("ix_export_log_kind", "tenant_id", "export_kind", "created_at"),
        CheckConstraint("row_count IS NULL OR row_count >= 0", name="row_count_non_negative"),
        {"schema": "audit"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: ``CSV`` | ``XLSX`` | ``PDF`` | ``PPTX`` | ``RAW_OBJECT`` | ``ERROR_REPORT``.
    export_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    #: The screen or endpoint the export came from.
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Filters the export was generated under, so a disputed figure can be
    #: reproduced exactly.
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Analysis runs whose results the export contains.
    source_run_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(Sha256, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: True when a signed URL was issued rather than bytes streamed inline.
    url_issued: Mapped[bool] = mapped_column(nullable=False, default=False)
    url_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(Sha256, nullable=True)
    #: Set when the export was blocked - scope violation, evidence not published,
    #: or a row limit exceeded. A refused export is as interesting as a granted
    #: one.
    denied_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ErasureRequest(Base, TimestampMixin):
    """A data-subject deletion or restriction request and how it was satisfied.

    docs/PLAN_REVIEW.md F-15: deletion cannot mean ``DELETE FROM`` here. Published
    causal estimates are derived, aggregate and already reviewed; removing a
    prescriber's rows from under them would silently invalidate figures that
    finance has signed off. The resolution is tombstone plus crypto-shred - the
    identity crosswalk is destroyed so the subject is no longer identifiable,
    while the aggregate results stay reproducible.

    This table records what was requested, what was actually done, and what was
    intentionally retained with the legal basis for retaining it. That last
    column is the one a regulator asks about.
    """

    __tablename__ = "erasure_requests"
    __table_args__ = (
        Index("ix_erasure_requests_tenant_status", "tenant_id", "status"),
        Index("ix_erasure_requests_due", "due_by"),
        CheckConstraint(
            "status <> 'COMPLETED' OR completed_at IS NOT NULL",
            name="completed_request_has_timestamp",
        ),
        CheckConstraint(
            "status <> 'REJECTED' OR rejection_reason IS NOT NULL",
            name="rejected_request_states_reason",
        ),
        {"schema": "audit"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: ``ERASURE`` | ``RESTRICTION`` | ``ACCESS`` | ``RECTIFICATION``.
    request_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="ERASURE")
    #: ``USER`` | ``HCP``. Patient data is never held, so it is not a subject
    #: type here.
    subject_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    subject_hcp_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: Hash of the identifier supplied in the request, so the request can be
    #: matched without storing another copy of the identifier.
    subject_reference_hash: Mapped[str | None] = mapped_column(Sha256, nullable=True)

    #: ``RECEIVED`` | ``VERIFYING`` | ``IN_PROGRESS`` | ``COMPLETED`` |
    #: ``REJECTED`` | ``PARTIALLY_COMPLETED``.
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="RECEIVED")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    #: Statutory deadline. DPDP and GDPR both run on clocks, and a request that
    #: quietly ages past its deadline is the failure mode this column exists to
    #: make visible.
    due_by: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    handled_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    #: Actions taken, table by table: tombstoned, crypto-shredded, hard-deleted,
    #: or retained. Written by the erasure job, not by hand.
    actions_taken: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    identifiers_shredded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_tombstoned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: What was deliberately kept - published aggregates, audit events, financial
    #: records under statutory retention - and why.
    retained_categories: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    legal_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class RetentionPolicyRun(Base, TimestampMixin):
    """One execution of the scheduled retention job.

    plan.md §15 gives each tenant a retention horizon. Something has to enforce
    it on a schedule, and that something has to leave proof: raw uploads expired,
    partitions dropped, objects removed from storage - and objects skipped because
    a legal hold was in force, which is the case that would otherwise look like a
    bug in the job.
    """

    __tablename__ = "retention_policy_runs"
    __table_args__ = (
        Index("ix_retention_policy_runs_tenant_created", "tenant_id", "created_at"),
        {"schema": "audit"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: ``RAW_OBJECTS`` | ``AUDIT_PARTITIONS`` | ``UPLOAD_SESSIONS`` |
    #: ``AI_INTERACTIONS``.
    policy: Mapped[str] = mapped_column(String(40), nullable=False)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cutoff_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    objects_examined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objects_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    objects_skipped_legal_hold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partitions_dropped: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    #: False when the job ran in report-only mode, which is how a new policy is
    #: validated before it is allowed to delete anything.
    executed: Mapped[bool] = mapped_column(nullable=False, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


__all__ = [
    "AuditEvent",
    "ErasureRequest",
    "ExportLog",
    "RetentionPolicyRun",
]
