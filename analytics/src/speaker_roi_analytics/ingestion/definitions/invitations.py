"""``INVITATIONS`` — who was invited to each event, and through which channel (plan.md §10.1).

Invitations are what make a credible control group possible.  The strongest
comparison the platform can draw is *invited-and-attended* versus
*invited-but-did-not-attend*: both groups were selected by the same brand team,
for the same event, using the same criteria, so the selection effect that
plagues attendee-versus-everyone comparisons largely cancels (plan.md §11).
Without this file the platform can still report descriptive numbers, but the
evidence grade for any causal claim drops — which is why the upload wizard
recommends it even though attendance alone will load.

``is_eligible`` records the compliance screen: an invitee who was screened out
never had the opportunity to attend and must be excluded from the control group
rather than counted as a decliner.
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
    EARLIEST_PLAUSIBLE_DATE,
    source_hcp_id_field,
    source_system_field,
)
from speaker_roi_analytics.ingestion.issues import IssueCode
from speaker_roi_analytics.ingestion.validators import dependent_field_required, no_future_period
from speaker_roi_core.enums import DatasetType, InvitationChannel, InvitationStatus

__all__ = ["CONTRACT"]


CONTRACT = DatasetContract(
    dataset_type=DatasetType.INVITATIONS,
    version="1.0.0",
    title="Event Invitations",
    description=(
        "One row per healthcare professional invited to an event, with the channel used and "
        "the compliance eligibility decision. The basis for the invited-but-did-not-attend "
        "control group."
    ),
    owner="Speaker Programme Operations",
    cadence=Cadence.PER_EVENT,
    natural_key=("event_code", "source_system", "source_hcp_id", "channel"),
    duplicate_policy="LAST_WINS",
    requires_scope=(ScopeKind.EVENT,),
    fields=(
        FieldSpec(
            name="event_code",
            title="Event Code",
            dtype=DType.STRING,
            description="Event the invitation was for. Must exist in CAMPAIGN_EVENT_MASTER.",
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
            description="Identifier of the invited professional in the source system named above."
        ),
        FieldSpec(
            name="invited_on",
            title="Invited On",
            dtype=DType.DATE,
            description=(
                "Date the invitation was sent. Used to establish that the invitation preceded the "
                "event, and to bound how far before the event the control group was formed."
            ),
            minimum=EARLIEST_PLAUSIBLE_DATE,
            example="2026-02-20",
            aliases=(
                "invite_date",
                "invitation_date",
                "sent_on",
                "sent_date",
                "date_invited",
                "INVITED_ON",
            ),
        ),
        FieldSpec(
            name="channel",
            title="Invitation Channel",
            dtype=DType.ENUM,
            description=(
                "How the invitation was delivered. Channel is part of the natural key because the "
                "same professional is frequently invited by both a rep and an email campaign, and "
                "collapsing those loses the reach picture."
            ),
            enum_ref=InvitationChannel,
            example="EMAIL",
            aliases=(
                "invitation_channel",
                "invite_channel",
                "medium",
                "contact_channel",
                "CHANNEL",
            ),
        ),
        FieldSpec(
            name="invitation_status",
            title="Invitation Status",
            dtype=DType.ENUM,
            description=(
                "State of the invitation itself, distinct from whether the professional attended. "
                "An ACCEPTED invitation is not evidence of attendance."
            ),
            required=False,
            nullable=True,
            enum_ref=InvitationStatus,
            example="ACCEPTED",
            aliases=("invite_status", "rsvp", "rsvp_status", "response", "response_status"),
        ),
        FieldSpec(
            name="is_eligible",
            title="Is Eligible",
            dtype=DType.BOOLEAN,
            description=(
                "Whether the professional passed the compliance screen for this event. Ineligible "
                "invitees are excluded from the control group: they never had the opportunity to "
                "attend, so treating them as decliners would bias the comparison."
            ),
            example="true",
            aliases=(
                "eligible",
                "eligibility",
                "eligible_flag",
                "compliance_eligible",
                "is_compliant",
            ),
        ),
        FieldSpec(
            name="eligibility_reason",
            title="Eligibility Reason",
            dtype=DType.STRING,
            description=(
                "Why the professional was screened out. Required whenever is_eligible is false, so "
                "an exclusion is always explainable in a compliance review."
            ),
            required=False,
            nullable=True,
            max_length=300,
            example="",
            aliases=(
                "reason",
                "exclusion_reason",
                "ineligibility_reason",
                "compliance_reason",
                "eligibility_note",
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
        no_future_period("invited_on", description="invited_on should not be dated in the future."),
        dependent_field_required(
            trigger_field="is_eligible",
            required_field="eligibility_reason",
            when=lambda value: value is False,
            trigger_text="is_eligible is false",
            code=IssueCode.RULE_ELIGIBILITY_REASON_REQUIRED,
            description=(
                "eligibility_reason is required when is_eligible is false, so that every "
                "compliance exclusion carries its justification."
            ),
        ),
    ),
    sample_rows=(
        {
            "event_code": "EVT-2026-0417",
            "source_system": "CRM",
            "source_hcp_id": "CRM-0009182",
            "invited_on": "2026-02-20",
            "channel": "EMAIL",
            "invitation_status": "ACCEPTED",
            "is_eligible": "true",
            "eligibility_reason": "",
        },
        {
            "event_code": "EVT-2026-0417",
            "source_system": "CRM",
            "source_hcp_id": "CRM-0009182",
            "invited_on": "2026-02-24",
            "channel": "REP",
            "invitation_status": "ACCEPTED",
            "is_eligible": "true",
            "eligibility_reason": "",
        },
        {
            "event_code": "EVT-2026-0417",
            "source_system": "CRM",
            "source_hcp_id": "CRM-0011044",
            "invited_on": "2026-02-20",
            "channel": "EMAIL",
            "invitation_status": "PENDING",
            "is_eligible": "true",
            "eligibility_reason": "",
        },
        {
            "event_code": "EVT-2026-0418",
            "source_system": "EVENTTOOL",
            "source_hcp_id": "ET-55210",
            "invited_on": "2026-03-10",
            "channel": "PORTAL",
            "invitation_status": "REVOKED",
            "is_eligible": "false",
            "eligibility_reason": "Speaker agreement pending; excluded by compliance.",
        },
    ),
    notes=(
        "Send the full invitation list, not just acceptances. The professionals who were "
        "invited and did not attend are the control group.",
        "Duplicate invitations for the same event, professional and channel are treated as "
        "restatements: the last row wins and the earlier one is reported as superseded.",
    ),
)
