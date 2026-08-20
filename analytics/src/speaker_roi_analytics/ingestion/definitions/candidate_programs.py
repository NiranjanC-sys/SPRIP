"""``CANDIDATE_PROGRAMS`` — proposed programme *designs* awaiting forecast (plan.md §10.1, §7.4).

This file feeds the planning workflow: a set of candidate programmes described
by their **design** — topic, region, format, month, expected size and cost — for
which the platform produces an expected-impact range and, in the optimiser, a
recommended portfolio under a budget.

The defining constraint of this contract is what it refuses.

Plan.md §7.4 is explicit: *"Do not accept named target HCPs as prediction
inputs."*  Plan.md §15 reinforces it: *"Prohibit named-HCP prescribing rankings
for speaker/attendee selection."*  A file that carries ``target_hcp_ids``, a
prescriber list, an NPI column or a decile ranking is asking the platform to
rank named clinicians by their commercial value, and the platform will not do
that — not with a warning, not with a filtered column, but by refusing the file
at the header with
:data:`~speaker_roi_analytics.ingestion.issues.IssueCode.POLICY_NAMED_HCP_TARGETING`
and a message that says why.

This is not squeamishness about a feature request.  A programme forecast
conditioned on named high-value prescribers is a targeting model wearing a
planning model's clothes, and it converts an analytics platform into a
compliance liability for the customer who runs it.  The refusal is enforced by
:data:`~speaker_roi_analytics.ingestion.contracts.NAMED_TARGETING_FORBIDDEN_HEADERS`
and covered by a dedicated test.

Forecasts are produced for designs.  Who is invited to the resulting programme
remains a decision for the brand team and their compliance function.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from speaker_roi_analytics.ingestion.contracts import (
    NAMED_TARGETING_FORBIDDEN_HEADERS,
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
    month_field,
    region_code_field,
    topic_code_field,
)
from speaker_roi_analytics.ingestion.issues import IssueCode
from speaker_roi_analytics.ingestion.validators import dependent_field_required
from speaker_roi_core.enums import DatasetType, EventFormat, IssueSeverity

__all__ = ["CONTRACT"]


def _planned_month_is_forward_looking() -> RowRule:
    """A candidate programme planned in the past is a stale planning file.

    Unlike every other dataset, forward dates here are correct and *backward*
    ones are suspect: a candidate whose planned month has already passed either
    ran (and belongs in CAMPAIGN_EVENT_MASTER) or was dropped.  Forecasting it
    would produce a recommendation nobody can act on, so the row is flagged.
    Warning rather than rejection — planning cycles legitimately re-forecast the
    current month.
    """

    def _check(row: RowView, ctx: RuleContext) -> Sequence[RuleViolation]:
        planned = row.get("planned_month")
        if not isinstance(planned, dt.date):
            return ()
        current_month_start = ctx.today.replace(day=1)
        if planned >= current_month_start:
            return ()
        return (
            RuleViolation(
                code=IssueCode.RULE_STALE_CANDIDATE_DATE,
                field_name="planned_month",
                severity=IssueSeverity.WARNING,
                params={"field": "planned_month", "current_month": current_month_start.isoformat()},
            ),
        )

    return RowRule(
        name="planned_month_is_forward_looking",
        code=IssueCode.RULE_STALE_CANDIDATE_DATE,
        description="planned_month should be the current month or later; past months are stale candidates.",
        fields=("planned_month",),
        check=_check,
    )


CONTRACT = DatasetContract(
    dataset_type=DatasetType.CANDIDATE_PROGRAMS,
    version="1.0.0",
    title="Candidate Programmes",
    description=(
        "Proposed programme designs awaiting an impact forecast: topic, region, format, planned "
        "month, expected attendance and planned cost. Designs only — never named prescribers."
    ),
    owner="Speaker Programme Operations / Planning",
    cadence=Cadence.AD_HOC,
    natural_key=("candidate_code",),
    duplicate_policy="REJECT",
    requires_scope=(ScopeKind.BRAND,),
    forbidden_headers=NAMED_TARGETING_FORBIDDEN_HEADERS,
    fields=(
        FieldSpec(
            name="candidate_code",
            title="Candidate Code",
            dtype=DType.STRING,
            description="Your own reference for the proposed programme. Used to match forecasts back to your plan.",
            max_length=40,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-.]{0,39}$",
            example="CAND-2026-041",
            aliases=(
                "candidate",
                "candidate_id",
                "proposal_code",
                "proposal_id",
                "plan_code",
                "scenario_code",
                "ref",
            ),
        ),
        FieldSpec(
            name="candidate_name",
            title="Candidate Name",
            dtype=DType.STRING,
            description="Working title of the proposed programme.",
            max_length=200,
            example="Lipid Management Roundtable - Pune",
            aliases=("name", "title", "proposal_name", "programme_name", "program_name"),
        ),
        brand_code_field(
            description="Brand the proposed programme would promote. Must exist in BRAND_PRODUCT_MASTER."
        ),
        FieldSpec(
            name="campaign_code",
            title="Campaign Code",
            dtype=DType.STRING,
            description=(
                "Existing campaign the proposal would sit under, if any. Leave blank for a "
                "standalone proposal."
            ),
            required=False,
            nullable=True,
            max_length=40,
            example="CMP-ALPHA-2026H1",
            aliases=("campaign", "campaign_id", "programme_code", "program_code"),
        ),
        topic_code_field(
            description="Proposed topic, from the tenant topic taxonomy. A primary design lever."
        ),
        region_code_field(
            description="Region the programme would run in, from the tenant region taxonomy."
        ),
        FieldSpec(
            name="event_format",
            title="Event Format",
            dtype=DType.ENUM,
            description=(
                "Proposed delivery format. Format drives both expected reach and cost, and is one "
                "of the levers the optimiser trades off."
            ),
            enum_ref=EventFormat,
            example="ROUNDTABLE",
            aliases=(
                "format",
                "delivery_format",
                "meeting_format",
                "mode",
                "proposed_format",
                "FORMAT",
            ),
        ),
        month_field(
            name="planned_month",
            title="Planned Month",
            description=(
                "Month the programme would run. Accepted forms: 2026-09, 2026-09-01, 09/2026, "
                "Sep-26. Seasonality and market factors are read for this month."
            ),
            example="2026-09",
        ),
        FieldSpec(
            name="expected_attendance",
            title="Expected Attendance",
            dtype=DType.INTEGER,
            description=(
                "How many professionals the programme is expected to reach. An aggregate count — "
                "the platform does not accept, and does not need, a list of who they would be."
            ),
            minimum=1,
            maximum=100_000,
            unit="professionals",
            example="18",
            aliases=(
                "planned_attendance",
                "expected_attendees",
                "audience_size",
                "reach",
                "seats",
                "capacity",
            ),
        ),
        FieldSpec(
            name="planned_cost",
            title="Planned Cost",
            dtype=DType.DECIMAL,
            description=(
                "Estimated total cost of the programme in the currency below. The optimiser's "
                "budget constraint is built from this."
            ),
            precision=MONEY_PRECISION,
            scale=MONEY_SCALE,
            minimum=Decimal("0"),
            unit="currency",
            example="240000.00",
            aliases=("estimated_cost", "budget", "planned_spend", "cost_estimate", "expected_cost"),
        ),
        currency_field(
            description="ISO-4217 code for planned_cost. Never converted by the platform."
        ),
        FieldSpec(
            name="speaker_tier",
            title="Speaker Tier",
            dtype=DType.STRING,
            description=(
                "Proposed speaker classification, e.g. NATIONAL / REGIONAL / LOCAL. A design "
                "attribute and a cost driver — never an individual speaker's name."
            ),
            required=False,
            nullable=True,
            max_length=40,
            example="LOCAL",
            aliases=("tier", "speaker_level", "speaker_category", "faculty_tier", "proposed_tier"),
        ),
        FieldSpec(
            name="is_compliance_eligible",
            title="Is Compliance Eligible",
            dtype=DType.BOOLEAN,
            description=(
                "Whether compliance has cleared the design. Ineligible candidates can still be "
                "modelled — seeing the forecast is often what settles the discussion — but the "
                "optimiser will not select them."
            ),
            required=False,
            nullable=True,
            example="true",
            aliases=(
                "compliance_eligible",
                "eligible",
                "cleared",
                "compliance_cleared",
                "is_eligible",
            ),
        ),
        # Written out rather than built from ``note_field`` because this contract
        # already has a ``notes`` column, and the shared helper's generic aliases
        # ("notes", "comment", ...) would then be claimed by two different fields.
        FieldSpec(
            name="compliance_note",
            title="Compliance Note",
            dtype=DType.STRING,
            description=(
                "Why the design was cleared or blocked. Required whenever is_compliance_eligible "
                "is false, so a block is always explainable."
            ),
            required=False,
            nullable=True,
            max_length=500,
            example="",
            pii=True,
            aliases=("compliance_reason", "compliance_comment", "review_note", "compliance_remark"),
        ),
        FieldSpec(
            name="notes",
            title="Notes",
            dtype=DType.STRING,
            description="Optional free-text planning note. Not used in any calculation.",
            required=False,
            nullable=True,
            max_length=2000,
            example="",
            pii=True,
            aliases=("planning_notes", "comments_free_text", "additional_notes"),
        ),
    ),
    references=(
        ReferenceSpec(
            field_name="brand_code",
            target=ReferenceTarget.BRAND,
            description="Must be a brand declared in BRAND_PRODUCT_MASTER for this tenant.",
        ),
        ReferenceSpec(
            field_name="campaign_code",
            target=ReferenceTarget.CAMPAIGN,
            description="Must be a campaign declared in CAMPAIGN_EVENT_MASTER, when supplied.",
            required=False,
        ),
    ),
    row_rules=(
        _planned_month_is_forward_looking(),
        dependent_field_required(
            trigger_field="is_compliance_eligible",
            required_field="compliance_note",
            when=lambda value: value is False,
            trigger_text="is_compliance_eligible is false",
            description="compliance_note is required when a candidate is marked compliance-ineligible.",
        ),
    ),
    sample_rows=(
        {
            "candidate_code": "CAND-2026-041",
            "candidate_name": "Lipid Management Roundtable - Pune",
            "brand_code": "BRD-ALPHA",
            "campaign_code": "CMP-ALPHA-2026H1",
            "topic_code": "TOP-CARDIO-01",
            "region_code": "IN-WEST",
            "event_format": "ROUNDTABLE",
            "planned_month": "2026-09",
            "expected_attendance": "18",
            "planned_cost": "240000.00",
            "currency": "INR",
            "speaker_tier": "LOCAL",
            "is_compliance_eligible": "true",
            "compliance_note": "",
            "notes": "",
        },
        {
            "candidate_code": "CAND-2026-042",
            "candidate_name": "Lipid Management Webinar - National",
            "brand_code": "BRD-ALPHA",
            "campaign_code": "CMP-ALPHA-2026H1",
            "topic_code": "TOP-CARDIO-01",
            "region_code": "IN-NATIONAL",
            "event_format": "VIRTUAL",
            "planned_month": "2026-09",
            "expected_attendance": "140",
            "planned_cost": "310000.00",
            "currency": "INR",
            "speaker_tier": "NATIONAL",
            "is_compliance_eligible": "true",
            "compliance_note": "",
            "notes": "Alternative to CAND-2026-041; compare cost per verified attendee.",
        },
        {
            "candidate_code": "CAND-2026-043",
            "candidate_name": "Diabetes Titration Series - Chennai",
            "brand_code": "BRD-BETA",
            "campaign_code": "",
            "topic_code": "TOP-DIAB-02",
            "region_code": "IN-SOUTH",
            "event_format": "IN_PERSON",
            "planned_month": "2026-10",
            "expected_attendance": "35",
            "planned_cost": "420000.00",
            "currency": "INR",
            "speaker_tier": "REGIONAL",
            "is_compliance_eligible": "false",
            "compliance_note": "Venue category pending compliance review.",
            "notes": "",
        },
    ),
    notes=(
        "Designs only. This file must not contain target HCP identifiers, prescriber lists, NPI "
        "numbers, decile rankings or named attendees. A file carrying any of those columns is "
        "rejected outright (plan.md §7.4, §15) — forecasts are produced for programme designs, "
        "never for named clinicians.",
        "expected_attendance is an aggregate. If you do not know it, use the historical average "
        "for the format and region rather than deriving it from a prescriber list.",
        "Candidates that compliance has not cleared can still be forecast, but the optimiser "
        "will not select them into a recommended portfolio.",
    ),
)
