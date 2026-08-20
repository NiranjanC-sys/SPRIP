"""``ATTENDANCE`` — verified attendance at each event (plan.md §10.1, §4).

Verified attendance is the **treatment variable**.  Everything the platform
claims about programme impact rests on a clean separation between professionals
who were actually in the room (or in the webinar) and professionals who were
not.  Two design decisions follow, and both are enforced here rather than
downstream:

1. **Attendance must carry evidence.**  ``verified_attended = true`` with
   ``verification_source = UNVERIFIED`` is rejected.  Registration is intent;
   attendance is a fact, and only a badge scan, a platform log, a signed sheet
   or a vendor attestation makes it one.

2. **Duplicates are reconciled, not deduplicated.**  The same professional
   legitimately appears twice — once from the registration export, once from the
   door scanner — and those two rows carry *different evidence*.  This contract
   is therefore the only one with ``duplicate_policy = "RECONCILE"``: the
   strongest verification source wins, and two equally strong sources that
   disagree are **quarantined** rather than silently arbitrated.  Picking one by
   file order would place a possibly-absent professional into the treated
   cohort, which is precisely the contamination that makes a lift estimate
   unusable.  See
   :func:`~speaker_roi_analytics.ingestion.validators.resolve_duplicates`.
"""

from __future__ import annotations

from speaker_roi_analytics.ingestion.contracts import (
    Cadence,
    DatasetContract,
    DType,
    FieldSpec,
    ReferenceSpec,
    ReferenceTarget,
    ScopeKind,
)
from speaker_roi_analytics.ingestion.definitions._common import (
    note_field,
    source_hcp_id_field,
    source_system_field,
)
from speaker_roi_analytics.ingestion.validators import (
    attendance_status_consistent,
    verified_requires_strong_source,
)
from speaker_roi_core.enums import (
    AttendanceStatus,
    AttendanceVerificationSource,
    DatasetType,
)

__all__ = ["CONTRACT"]


CONTRACT = DatasetContract(
    dataset_type=DatasetType.ATTENDANCE,
    version="1.0.0",
    title="Event Attendance",
    description=(
        "One row per attendance record per event, with the evidence that supports it. "
        "Verified attendance is the treatment variable for every impact estimate, so each "
        "row must name how attendance was verified."
    ),
    owner="Speaker Programme Operations",
    cadence=Cadence.PER_EVENT,
    natural_key=("event_code", "source_system", "source_hcp_id"),
    duplicate_policy="RECONCILE",
    requires_scope=(ScopeKind.EVENT,),
    fields=(
        FieldSpec(
            name="event_code",
            title="Event Code",
            dtype=DType.STRING,
            description="Event attended. Must exist in CAMPAIGN_EVENT_MASTER.",
            max_length=40,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-.]{0,39}$",
            example="EVT-2026-0417",
            aliases=(
                "event",
                "event_id",
                "meeting_code",
                "meeting_id",
                "session_code",
                "programme_id",
                "EVENT_CODE",
            ),
        ),
        source_system_field(),
        source_hcp_id_field(
            description="Identifier of the attending professional in the source system named above."
        ),
        FieldSpec(
            name="registration_status",
            title="Registration Status",
            dtype=DType.ENUM,
            description=(
                "State of the registration record. Distinct from verified attendance: a "
                "REGISTERED professional may not have arrived, and a walk-in may never have "
                "registered at all."
            ),
            required=False,
            nullable=True,
            enum_ref=AttendanceStatus,
            example="REGISTERED",
            aliases=("reg_status", "registration", "attendee_status", "rsvp_status", "status"),
        ),
        FieldSpec(
            name="verified_attended",
            title="Verified Attended",
            dtype=DType.BOOLEAN,
            description=(
                "Whether attendance was actually verified. This is the treatment flag: only "
                "true rows enter the treated cohort. Set it to false for registrations that "
                "did not result in attendance — do not omit the row."
            ),
            example="true",
            aliases=(
                "attended",
                "is_attended",
                "attendance_flag",
                "did_attend",
                "present",
                "attended_flag",
                "verified",
                "ATTENDED",
                "Attended",
            ),
        ),
        FieldSpec(
            name="verification_source",
            title="Verification Source",
            dtype=DType.ENUM,
            description=(
                "How attendance was established. Badge scans and webinar platform logs are "
                "treated as strong evidence; sign-in sheets and vendor attestations as weaker. "
                "UNVERIFIED is only valid alongside verified_attended = false."
            ),
            enum_ref=AttendanceVerificationSource,
            example="BADGE_SCAN",
            aliases=(
                "verification",
                "attendance_source",
                "evidence_source",
                "proof",
                "proof_type",
                "verification_method",
                "source_of_truth",
                "VERIFICATION_SOURCE",
            ),
        ),
        FieldSpec(
            name="check_in_at",
            title="Check-in Timestamp",
            dtype=DType.STRING,
            description=(
                "Local check-in timestamp as recorded by the door or platform, ISO-8601 "
                "(YYYY-MM-DDTHH:MM). Evidence detail only; measurement uses the event date."
            ),
            required=False,
            nullable=True,
            max_length=32,
            pattern=r"^\d{4}-\d{2}-\d{2}[T ]([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$",
            example="2026-03-12T18:41",
            aliases=(
                "check_in",
                "checkin_time",
                "scan_time",
                "entry_time",
                "joined_at",
                "login_time",
            ),
        ),
        FieldSpec(
            name="duration_minutes",
            title="Duration (minutes)",
            dtype=DType.INTEGER,
            description=(
                "Minutes present, where the platform or scanner reports it. Used to distinguish "
                "a full attendance from a two-minute webinar drop-in, which are not the same "
                "exposure."
            ),
            required=False,
            nullable=True,
            minimum=0,
            maximum=1440,
            unit="minutes",
            example="95",
            aliases=("duration", "minutes", "time_in_session", "attendance_minutes", "watch_time"),
        ),
        note_field(
            name="reconciliation_note",
            title="Reconciliation Note",
            description=(
                "Optional note explaining a manual reconciliation, e.g. why a scanner record was "
                "overridden. Read by reviewers, never used in any calculation."
            ),
        ),
    ),
    references=(
        ReferenceSpec(
            field_name="event_code",
            target=ReferenceTarget.EVENT,
            description="Must be an event declared in CAMPAIGN_EVENT_MASTER for this tenant.",
        ),
    ),
    row_rules=(
        verified_requires_strong_source(),
        attendance_status_consistent(),
    ),
    sample_rows=(
        {
            "event_code": "EVT-2026-0417",
            "source_system": "EVENTTOOL",
            "source_hcp_id": "ET-55210",
            "registration_status": "ATTENDED",
            "verified_attended": "true",
            "verification_source": "BADGE_SCAN",
            "check_in_at": "2026-03-12T18:41",
            "duration_minutes": "95",
            "reconciliation_note": "",
        },
        {
            "event_code": "EVT-2026-0417",
            "source_system": "EVENTTOOL",
            "source_hcp_id": "ET-55211",
            "registration_status": "NO_SHOW",
            "verified_attended": "false",
            "verification_source": "UNVERIFIED",
            "check_in_at": "",
            "duration_minutes": "",
            "reconciliation_note": "",
        },
        {
            "event_code": "EVT-2026-0418",
            "source_system": "EVENTTOOL",
            "source_hcp_id": "ET-55219",
            "registration_status": "REGISTERED",
            "verified_attended": "true",
            "verification_source": "WEBINAR_PLATFORM_LOG",
            "check_in_at": "2026-04-02T19:02",
            "duration_minutes": "68",
            "reconciliation_note": "",
        },
        {
            "event_code": "EVT-2026-0418",
            "source_system": "EVENTTOOL",
            "source_hcp_id": "ET-55223",
            "registration_status": "NOT_REGISTERED",
            "verified_attended": "true",
            "verification_source": "SIGN_IN_SHEET",
            "check_in_at": "",
            "duration_minutes": "",
            "reconciliation_note": "Walk-in; captured on the paper sheet only.",
        },
    ),
    notes=(
        "Send non-attendees too. A registration that did not convert is evidence, and omitting "
        "it makes the control group smaller and the comparison weaker.",
        "Duplicate rows for the same event and professional are reconciled by evidence strength: "
        "badge scan and webinar platform log beat sign-in sheet and vendor attestation. Two "
        "strong sources that disagree are quarantined for a human decision — the platform will "
        "not choose between them.",
        "UNVERIFIED is a legitimate value, but only for rows where verified_attended is false.",
    ),
)
