"""``MARKETING_ACTIVITY`` — non-programme promotional exposure per month (plan.md §10.1, §9.3).

Speaker programmes do not run in isolation.  In the months around an event the
same professional is also being called on by a representative, emailed, sampled
and invited to other meetings.  If those exposures are not measured, every one
of them is absorbed into the programme's estimated effect — and since brands
tend to concentrate *all* their activity on the same high-potential
professionals, the omission systematically inflates measured programme impact.
This file is what lets the models hold that other activity constant (plan.md
§11).

The grain is month-by-professional-by-brand and the measures are wide rather
than a channel/quantity long format.  That matches the conformed
``marketing_activity`` table and, more importantly, matches how the source
systems export: a CRM gives you call counts per month, a marketing-automation
platform gives you sends and opens per month, and asking teams to melt those
into a long file by hand is where the errors come from.
"""

from __future__ import annotations

from collections.abc import Sequence

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
    brand_code_field,
    month_field,
    source_hcp_id_field,
    source_system_field,
)
from speaker_roi_analytics.ingestion.issues import IssueCode
from speaker_roi_analytics.ingestion.validators import no_future_period
from speaker_roi_core.enums import DatasetType, IssueSeverity

__all__ = ["CONTRACT"]


def _measure(
    name: str,
    title: str,
    description: str,
    *,
    aliases: tuple[str, ...],
    example: str,
    unit: str,
) -> FieldSpec:
    """A non-negative monthly activity count.

    Optional and nullable: almost no tenant has every channel wired up on day
    one, and a contract that demanded all six would block the upload of the two
    that are available.  A blank means "this channel is not supplied"; a zero
    means "supplied, and there was none" — the same missing-versus-zero
    distinction the Rx contract makes, applied to covariates.
    """
    return FieldSpec(
        name=name,
        title=title,
        dtype=DType.INTEGER,
        description=description,
        required=False,
        nullable=True,
        minimum=0,
        maximum=1_000_000,
        unit=unit,
        example=example,
        aliases=aliases,
    )


def _opens_not_above_sends() -> RowRule:
    """Email opens cannot exceed emails delivered.

    A violation means the two columns were mapped the wrong way round, or opens
    are being counted per-open rather than per-recipient.  Either way the
    engagement covariate is on a different scale from the delivery one, so it is
    surfaced as a warning for the uploader to confirm before the number is used
    to explain away programme effect.
    """

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        sent = row.get("emails_delivered")
        opened = row.get("emails_opened")
        if not isinstance(sent, int) or not isinstance(opened, int):
            return ()
        if opened <= sent:
            return ()
        return (
            RuleViolation(
                code=IssueCode.VALUE_OUT_OF_RANGE,
                field_name="emails_opened",
                severity=IssueSeverity.WARNING,
                params={"field": "emails_opened", "range": "at most emails_delivered"},
            ),
        )

    return RowRule(
        name="opens_not_above_sends",
        code=IssueCode.VALUE_OUT_OF_RANGE,
        description="emails_opened must not exceed emails_delivered.",
        fields=("emails_delivered", "emails_opened"),
        check=_check,
    )


def _row_carries_some_activity() -> RowRule:
    """A row where every measure is blank carries no information.

    Not an error — a supplier may legitimately emit a placeholder row — but it is
    reported so a file that is *entirely* placeholder rows is visibly empty on
    the Data Health page rather than appearing as a successful load of ten
    thousand rows of nothing.
    """
    measures = (
        "rep_calls",
        "emails_delivered",
        "emails_opened",
        "samples_dropped",
        "other_event_exposures",
        "digital_impressions",
    )

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        if any(row.get(name) is not None for name in measures):
            return ()
        return (
            RuleViolation(
                code=IssueCode.RULE_ZERO_QUANTITY,
                field_name="rep_calls",
                severity=IssueSeverity.INFO,
                params={"field": "all activity measures"},
            ),
        )

    return RowRule(
        name="row_carries_some_activity",
        code=IssueCode.RULE_ZERO_QUANTITY,
        description="At least one activity measure should carry a value; an all-blank row is reported.",
        fields=measures,
        check=_check,
    )


CONTRACT = DatasetContract(
    dataset_type=DatasetType.MARKETING_ACTIVITY,
    version="1.0.0",
    title="Marketing Activity",
    description=(
        "Monthly non-programme promotional exposure per healthcare professional and brand: "
        "representative calls, email, samples, other event exposures and digital impressions. "
        "Used to hold other activity constant when estimating programme impact."
    ),
    owner="Omnichannel / Commercial Operations",
    cadence=Cadence.MONTHLY,
    natural_key=("source_system", "source_hcp_id", "brand_code", "month"),
    duplicate_policy="LAST_WINS",
    requires_scope=(ScopeKind.BRAND,),
    fields=(
        source_system_field(),
        source_hcp_id_field(
            description="The activity system's identifier for the professional. Resolved through HCP_CROSSWALK."
        ),
        brand_code_field(
            description="Brand the activity promoted. Must exist in BRAND_PRODUCT_MASTER."
        ),
        month_field(
            description=(
                "Month the activity took place in. Accepted forms: 2026-03, 2026-03-01, 03/2026, "
                "Mar-26. Aligned to the Rx month grain so exposure and outcome line up."
            ),
            example="2026-03",
        ),
        _measure(
            "rep_calls",
            "Rep Calls",
            (
                "Face-to-face or virtual detailing calls in the month. Typically the strongest "
                "confounder: reps call most often on the professionals most likely to be invited."
            ),
            aliases=(
                "calls",
                "detail_calls",
                "sales_calls",
                "visits",
                "rep_visits",
                "call_count",
                "details",
                "REP_CALLS",
            ),
            example="2",
            unit="calls",
        ),
        _measure(
            "emails_delivered",
            "Emails Delivered",
            "Marketing emails successfully delivered in the month (sends minus bounces).",
            aliases=(
                "emails",
                "emails_sent",
                "email_sends",
                "email_delivered",
                "sends",
                "delivered",
                "EMAILS_DELIVERED",
            ),
            example="4",
            unit="emails",
        ),
        _measure(
            "emails_opened",
            "Emails Opened",
            (
                "Delivered emails that were opened. An engagement signal rather than a reach "
                "signal, so it is modelled separately from delivery."
            ),
            aliases=("opens", "email_opens", "opened", "unique_opens", "EMAILS_OPENED"),
            example="1",
            unit="emails",
        ),
        _measure(
            "samples_dropped",
            "Samples Dropped",
            "Sample packs left with the professional in the month.",
            aliases=(
                "samples",
                "sample_drops",
                "sampling",
                "samples_given",
                "sample_units",
                "SAMPLES_DROPPED",
            ),
            example="0",
            unit="packs",
        ),
        _measure(
            "other_event_exposures",
            "Other Event Exposures",
            (
                "Attendance at company events other than the speaker programmes being measured — "
                "conferences, advisory boards, webinars. Without this, a professional who attends "
                "everything looks like a programme success story."
            ),
            aliases=(
                "other_events",
                "other_meetings",
                "conference_attendance",
                "other_event_count",
                "non_programme_events",
            ),
            example="1",
            unit="events",
        ),
        _measure(
            "digital_impressions",
            "Digital Impressions",
            "Served digital advertising impressions attributable to the professional in the month.",
            aliases=(
                "impressions",
                "digital_ads",
                "ad_impressions",
                "banner_impressions",
                "programmatic_impressions",
            ),
            example="240",
            unit="impressions",
        ),
    ),
    references=(
        ReferenceSpec(
            field_name="brand_code",
            target=ReferenceTarget.BRAND,
            description="Must be a brand declared in BRAND_PRODUCT_MASTER for this tenant.",
        ),
        ReferenceSpec(
            field_name="source_system",
            target=ReferenceTarget.SOURCE_SYSTEM,
            description="Must be a source system registered for this tenant.",
        ),
    ),
    row_rules=(
        no_future_period(
            "month", description="month should not be dated beyond the current period."
        ),
        _opens_not_above_sends(),
        _row_carries_some_activity(),
    ),
    sample_rows=(
        {
            "source_system": "CRM",
            "source_hcp_id": "CRM-0009182",
            "brand_code": "BRD-ALPHA",
            "month": "2026-01",
            "rep_calls": "2",
            "emails_delivered": "4",
            "emails_opened": "1",
            "samples_dropped": "0",
            "other_event_exposures": "0",
            "digital_impressions": "240",
        },
        {
            "source_system": "CRM",
            "source_hcp_id": "CRM-0009182",
            "brand_code": "BRD-ALPHA",
            "month": "2026-02",
            "rep_calls": "1",
            "emails_delivered": "3",
            "emails_opened": "2",
            "samples_dropped": "2",
            "other_event_exposures": "1",
            "digital_impressions": "180",
        },
        {
            "source_system": "CRM",
            "source_hcp_id": "CRM-0011044",
            "brand_code": "BRD-BETA",
            "month": "2026-02",
            "rep_calls": "0",
            "emails_delivered": "2",
            "emails_opened": "0",
            "samples_dropped": "0",
            "other_event_exposures": "0",
            "digital_impressions": "",
        },
    ),
    notes=(
        "Supply the channels you have. A blank measure means the channel is not supplied; a "
        "zero means it was supplied and there was no activity. The two are modelled differently.",
        "Cover the same months as the Rx file, including the months before the programme — the "
        "pre-period is what the comparison is built on.",
    ),
)
