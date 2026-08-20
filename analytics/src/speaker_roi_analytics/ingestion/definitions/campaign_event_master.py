"""``CAMPAIGN_EVENT_MASTER`` — speaker programmes and their events (plan.md §10.1).

One row per **event**, with its campaign's attributes repeated.  Programme teams
maintain this in a spreadsheet where a campaign is a block of rows, so asking
them to upload two files instead of one is the fastest way to get a stale
campaign file.  Denormalising here costs a consistency rule and saves a whole
class of "the campaign wasn't uploaded yet" support tickets.

``event_date`` is the anchor for every pre/post window in the platform, which is
why the date rules below are hard rejections: an event mis-dated by a month
silently moves prescriptions from the post period into the pre period and drives
measured lift towards zero (plan.md §11).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from speaker_roi_analytics.ingestion.contracts import (
    Cadence,
    DatasetContract,
    DType,
    FieldSpec,
    ReferenceSpec,
    ReferenceTarget,
    RowRule,
    RowView,
    RuleContext,
    RuleViolation,
    ScopeKind,
)
from speaker_roi_analytics.ingestion.definitions._common import (
    MONEY_PRECISION,
    MONEY_SCALE,
    brand_code_field,
    currency_field,
    region_code_field,
    topic_code_field,
)
from speaker_roi_analytics.ingestion.issues import IssueCode
from speaker_roi_analytics.ingestion.validators import date_order
from speaker_roi_core.enums import (
    CampaignStatus,
    DatasetType,
    EventFormat,
    EventStatus,
    IssueSeverity,
)

__all__ = ["CONTRACT"]


def _event_inside_campaign_window() -> RowRule:
    """The event must fall inside its campaign's declared window.

    An event outside its campaign's dates means one of the two is wrong, and
    both feed attribution: the campaign window bounds which events count towards
    a campaign's ROI, so an out-of-window event is either double-counted
    elsewhere or dropped from every rollup.  Quarantined rather than rejected —
    it is frequently the campaign end date that needs extending, which is a
    business decision, not a parse error.
    """

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        event_date = row.get("event_date")
        start = row.get("campaign_start_date")
        end = row.get("campaign_end_date")
        if not isinstance(event_date, dt.date):
            return ()
        if isinstance(start, dt.date) and event_date < start:
            return (
                RuleViolation(
                    code=IssueCode.RULE_EVENT_OUTSIDE_CAMPAIGN_WINDOW,
                    field_name="event_date",
                    params={"boundary": "campaign_start_date"},
                ),
            )
        if isinstance(end, dt.date) and event_date > end:
            return (
                RuleViolation(
                    code=IssueCode.RULE_EVENT_OUTSIDE_CAMPAIGN_WINDOW,
                    field_name="event_date",
                    params={"boundary": "campaign_end_date"},
                ),
            )
        return ()

    return RowRule(
        name="event_inside_campaign_window",
        code=IssueCode.RULE_EVENT_OUTSIDE_CAMPAIGN_WINDOW,
        description="event_date must fall within [campaign_start_date, campaign_end_date].",
        fields=("event_date", "campaign_start_date", "campaign_end_date"),
        check=_check,
    )


def _event_status_matches_date() -> RowRule:
    """``COMPLETED`` in the future, or ``PROPOSED`` far in the past, is a stale export.

    Programme trackers are edited by hand and statuses lag reality.  The check is
    a warning because the correct action is a human refresh of the source
    system, not a rejected upload — but it has to be visible, because a
    ``PROPOSED`` event that already happened will be excluded from measurement
    and nobody will ask why.
    """

    def _check(row: RowView, ctx: RuleContext) -> Sequence[RuleViolation]:
        status = row.get("event_status")
        event_date = row.get("event_date")
        if status is None or not isinstance(event_date, dt.date):
            return ()
        token = str(status).strip().upper()
        if token == EventStatus.COMPLETED.value and event_date > ctx.today:
            return (
                RuleViolation(
                    code=IssueCode.RULE_EVENT_STATUS_DATE_CONFLICT,
                    field_name="event_status",
                    severity=IssueSeverity.WARNING,
                    params={"status": token, "reason": "marked completed but dated in the future"},
                ),
            )
        if token in {
            EventStatus.PROPOSED.value,
            EventStatus.SCHEDULED.value,
        } and event_date < ctx.today - dt.timedelta(days=45):
            return (
                RuleViolation(
                    code=IssueCode.RULE_EVENT_STATUS_DATE_CONFLICT,
                    field_name="event_status",
                    severity=IssueSeverity.WARNING,
                    params={
                        "status": token,
                        "reason": "still pending more than 45 days after the event date",
                    },
                ),
            )
        return ()

    return RowRule(
        name="event_status_matches_date",
        code=IssueCode.RULE_EVENT_STATUS_DATE_CONFLICT,
        description="event_status must be consistent with event_date (no completed-in-future, no long-stale proposals).",
        fields=("event_status", "event_date"),
        check=_check,
    )


CONTRACT = DatasetContract(
    dataset_type=DatasetType.CAMPAIGN_EVENT_MASTER,
    version="1.0.0",
    title="Campaign and Event Master",
    description=(
        "One row per speaker-programme event, carrying its campaign's attributes. "
        "event_date anchors every pre/post measurement window in the platform."
    ),
    owner="Speaker Programme Operations",
    cadence=Cadence.PER_EVENT,
    natural_key=("event_code",),
    duplicate_policy="REJECT",
    requires_scope=(ScopeKind.BRAND,),
    fields=(
        FieldSpec(
            name="campaign_code",
            title="Campaign Code",
            dtype=DType.STRING,
            description="Stable short code for the campaign this event belongs to.",
            max_length=40,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-.]{0,39}$",
            example="CMP-ALPHA-2026H1",
            aliases=("campaign", "campaign_id", "programme_code", "program_code", "CAMPAIGN_CODE"),
        ),
        FieldSpec(
            name="campaign_name",
            title="Campaign Name",
            dtype=DType.STRING,
            description="Human-readable campaign name for dashboards.",
            max_length=200,
            example="Alphamax Cardiology Series H1 2026",
            aliases=("campaign_title", "programme_name", "program_name", "CAMPAIGN_NAME"),
        ),
        brand_code_field(
            description="Brand the campaign promotes. Must exist in the brand/product master."
        ),
        FieldSpec(
            name="objective",
            title="Campaign Objective",
            dtype=DType.STRING,
            description="What the campaign is meant to achieve, in the team's own words. Informational.",
            required=False,
            nullable=True,
            max_length=500,
            example="Build familiarity with the new dosing guideline among cardiologists.",
            aliases=("campaign_objective", "goal", "purpose", "aim"),
        ),
        FieldSpec(
            name="campaign_topic_code",
            title="Campaign Topic Code",
            dtype=DType.STRING,
            description="Overall topic of the campaign, from the tenant topic taxonomy.",
            required=False,
            nullable=True,
            max_length=40,
            example="TOP-CARDIO-01",
            aliases=("campaign_topic", "programme_topic_code"),
        ),
        FieldSpec(
            name="campaign_start_date",
            title="Campaign Start Date",
            dtype=DType.DATE,
            description="First day of the campaign window. Bounds which events roll up to the campaign.",
            example="2026-01-01",
            aliases=("campaign_start", "start_date", "campaign_from", "CAMPAIGN_START_DATE"),
        ),
        FieldSpec(
            name="campaign_end_date",
            title="Campaign End Date",
            dtype=DType.DATE,
            description="Last day of the campaign window, inclusive.",
            example="2026-06-30",
            aliases=("campaign_end", "end_date", "campaign_to", "CAMPAIGN_END_DATE"),
        ),
        FieldSpec(
            name="campaign_status",
            title="Campaign Status",
            dtype=DType.ENUM,
            description="Lifecycle state of the campaign.",
            required=False,
            nullable=True,
            enum_ref=CampaignStatus,
            example="ACTIVE",
            aliases=("campaign_state", "camp_status"),
        ),
        FieldSpec(
            name="planned_budget",
            title="Planned Budget",
            dtype=DType.DECIMAL,
            description=(
                "Approved campaign budget. Compared against actual cost from EVENT_COST; "
                "never used as a substitute for actual spend in any ROI figure."
            ),
            required=False,
            nullable=True,
            precision=MONEY_PRECISION,
            scale=MONEY_SCALE,
            minimum=Decimal("0"),
            unit="currency",
            example="4500000.00",
            aliases=("budget", "campaign_budget", "planned_spend", "approved_budget"),
        ),
        currency_field(
            required=False,
            description="ISO-4217 code for planned_budget. Required whenever a budget is supplied.",
        ),
        FieldSpec(
            name="event_code",
            title="Event Code",
            dtype=DType.STRING,
            description=(
                "Stable short code for the event. This is the key attendance, invitation and "
                "cost files join on, so it must not be recycled between events."
            ),
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
        FieldSpec(
            name="event_name",
            title="Event Name",
            dtype=DType.STRING,
            description="Title of the individual event.",
            max_length=200,
            example="Advances in Lipid Management — Mumbai",
            aliases=("event_title", "meeting_name", "session_name", "EVENT_NAME"),
        ),
        FieldSpec(
            name="event_date",
            title="Event Date",
            dtype=DType.DATE,
            description=(
                "Date the event took place or is scheduled for. This is the index date for every "
                "pre/post window; an error here shifts prescriptions between periods."
            ),
            example="2026-03-12",
            aliases=(
                "date",
                "meeting_date",
                "session_date",
                "programme_date",
                "held_on",
                "EVENT_DATE",
            ),
        ),
        FieldSpec(
            name="start_time",
            title="Start Time",
            dtype=DType.STRING,
            description="Local start time as HH:MM (24h). Informational; not used in measurement.",
            required=False,
            nullable=True,
            max_length=8,
            pattern=r"^([01]?\d|2[0-3]):[0-5]\d(:[0-5]\d)?$",
            example="18:30",
            aliases=("event_start_time", "from_time", "begin_time"),
        ),
        FieldSpec(
            name="end_time",
            title="End Time",
            dtype=DType.STRING,
            description="Local end time as HH:MM (24h).",
            required=False,
            nullable=True,
            max_length=8,
            pattern=r"^([01]?\d|2[0-3]):[0-5]\d(:[0-5]\d)?$",
            example="20:30",
            aliases=("event_end_time", "to_time", "finish_time"),
        ),
        FieldSpec(
            name="timezone",
            title="Timezone",
            dtype=DType.STRING,
            description="IANA timezone name for the times above, e.g. Asia/Kolkata.",
            required=False,
            nullable=True,
            max_length=60,
            example="Asia/Kolkata",
            aliases=("tz", "time_zone", "event_timezone"),
        ),
        FieldSpec(
            name="event_format",
            title="Event Format",
            dtype=DType.ENUM,
            description=(
                "Delivery format. Format drives which verification sources are credible: a virtual "
                "event cannot produce a badge scan, an in-person one cannot produce a platform log."
            ),
            enum_ref=EventFormat,
            example="IN_PERSON",
            aliases=("format", "delivery_format", "meeting_format", "mode", "event_type", "FORMAT"),
        ),
        topic_code_field(
            description="Topic of this specific event, from the tenant topic taxonomy."
        ),
        region_code_field(description="Region the event serves, from the tenant region taxonomy."),
        FieldSpec(
            name="venue_city",
            title="Venue City",
            dtype=DType.STRING,
            description="City the event was held in. Blank for virtual events.",
            required=False,
            nullable=True,
            max_length=120,
            example="Mumbai",
            aliases=("city", "event_city", "location_city"),
        ),
        FieldSpec(
            name="venue_name",
            title="Venue Name",
            dtype=DType.STRING,
            description="Venue or platform name.",
            required=False,
            nullable=True,
            max_length=200,
            example="Hotel Marine Plaza",
            aliases=("venue", "location", "event_venue", "hotel"),
        ),
        FieldSpec(
            name="speaker_tier",
            title="Speaker Tier",
            dtype=DType.STRING,
            description=(
                "The tenant's own speaker classification, e.g. NATIONAL / REGIONAL / LOCAL. Used as a "
                "programme-design covariate, never as an individual speaker rating."
            ),
            required=False,
            nullable=True,
            max_length=40,
            example="REGIONAL",
            aliases=("tier", "speaker_level", "speaker_category", "faculty_tier"),
        ),
        FieldSpec(
            name="planned_attendance",
            title="Planned Attendance",
            dtype=DType.INTEGER,
            description="Expected number of attendees at planning time. Compared against verified attendance.",
            required=False,
            nullable=True,
            minimum=0,
            maximum=100_000,
            example="45",
            aliases=(
                "expected_attendance",
                "planned_attendees",
                "target_attendance",
                "capacity",
                "seats",
            ),
        ),
        FieldSpec(
            name="event_status",
            title="Event Status",
            dtype=DType.ENUM,
            description=(
                "Lifecycle state of the event. Only COMPLETED events contribute to measured ROI; "
                "CANCELLED events keep their costs, which is why they are not simply deleted."
            ),
            enum_ref=EventStatus,
            example="COMPLETED",
            aliases=("status", "event_state", "meeting_status", "STATUS"),
        ),
    ),
    references=(
        ReferenceSpec(
            field_name="brand_code",
            target=ReferenceTarget.BRAND,
            description="Must be a brand declared in BRAND_PRODUCT_MASTER for this tenant.",
        ),
    ),
    row_rules=(
        date_order(
            earlier_field="campaign_start_date",
            later_field="campaign_end_date",
            description="campaign_start_date must be on or before campaign_end_date.",
        ),
        _event_inside_campaign_window(),
        _event_status_matches_date(),
    ),
    sample_rows=(
        {
            "campaign_code": "CMP-ALPHA-2026H1",
            "campaign_name": "Alphamax Cardiology Series H1 2026",
            "brand_code": "BRD-ALPHA",
            "objective": "Build familiarity with the revised dosing guideline among cardiologists.",
            "campaign_topic_code": "TOP-CARDIO-01",
            "campaign_start_date": "2026-01-01",
            "campaign_end_date": "2026-06-30",
            "campaign_status": "ACTIVE",
            "planned_budget": "4500000.00",
            "currency": "INR",
            "event_code": "EVT-2026-0417",
            "event_name": "Advances in Lipid Management - Mumbai",
            "event_date": "2026-03-12",
            "start_time": "18:30",
            "end_time": "20:30",
            "timezone": "Asia/Kolkata",
            "event_format": "IN_PERSON",
            "topic_code": "TOP-CARDIO-01",
            "region_code": "IN-WEST",
            "venue_city": "Mumbai",
            "venue_name": "Hotel Marine Plaza",
            "speaker_tier": "REGIONAL",
            "planned_attendance": "45",
            "event_status": "COMPLETED",
        },
        {
            "campaign_code": "CMP-ALPHA-2026H1",
            "campaign_name": "Alphamax Cardiology Series H1 2026",
            "brand_code": "BRD-ALPHA",
            "objective": "Build familiarity with the revised dosing guideline among cardiologists.",
            "campaign_topic_code": "TOP-CARDIO-01",
            "campaign_start_date": "2026-01-01",
            "campaign_end_date": "2026-06-30",
            "campaign_status": "ACTIVE",
            "planned_budget": "4500000.00",
            "currency": "INR",
            "event_code": "EVT-2026-0418",
            "event_name": "Advances in Lipid Management - Webinar",
            "event_date": "2026-04-02",
            "start_time": "19:00",
            "end_time": "20:15",
            "timezone": "Asia/Kolkata",
            "event_format": "VIRTUAL",
            "topic_code": "TOP-CARDIO-01",
            "region_code": "IN-NORTH",
            "venue_city": "",
            "venue_name": "Zoom Webinar",
            "speaker_tier": "NATIONAL",
            "planned_attendance": "120",
            "event_status": "COMPLETED",
        },
        {
            "campaign_code": "CMP-BETA-2026Q2",
            "campaign_name": "Betacare Diabetes Roundtables",
            "brand_code": "BRD-BETA",
            "objective": "Discuss real-world titration experience with endocrinologists.",
            "campaign_topic_code": "TOP-DIAB-02",
            "campaign_start_date": "2026-04-01",
            "campaign_end_date": "2026-06-30",
            "campaign_status": "ACTIVE",
            "planned_budget": "1200000.00",
            "currency": "INR",
            "event_code": "EVT-2026-0501",
            "event_name": "Betacare Roundtable - Bengaluru",
            "event_date": "2026-05-20",
            "start_time": "19:30",
            "end_time": "21:00",
            "timezone": "Asia/Kolkata",
            "event_format": "ROUNDTABLE",
            "topic_code": "TOP-DIAB-02",
            "region_code": "IN-SOUTH",
            "venue_city": "Bengaluru",
            "venue_name": "The Oberoi",
            "speaker_tier": "LOCAL",
            "planned_attendance": "18",
            "event_status": "SCHEDULED",
        },
    ),
    notes=(
        "One row per event. Campaign columns repeat for every event in the campaign and "
        "must agree across those rows.",
        "Cancelled events stay in the file: their costs are real and belong in ROI denominators.",
    ),
)
