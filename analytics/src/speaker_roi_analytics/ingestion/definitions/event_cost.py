"""``EVENT_COST`` — actual programme spend, line by line (plan.md §10.1).

This file is the ROI denominator.  A missing cost line makes a programme look
more efficient than it was, which is the most expensive kind of error this
platform can make: it survives review precisely because the answer is flattering.

Two rules exist because of what the numbers are used for:

* **One currency per event.**  PLAN_REVIEW F-14 forbids implicit currency
  conversion anywhere in the platform.  Two currencies inside one event's cost
  lines would make the event total a meaningless sum, so the group is
  quarantined for the uploader to restate rather than converted at some rate the
  platform picked (see
  :func:`~speaker_roi_analytics.ingestion.validators.single_currency_per_group`).
* **Approved means someone approved it.**  An ``APPROVED`` line with no approver
  cannot be defended in a spend audit, so the platform refuses to record one.

Amounts are ``decimal(18, 2)`` and parsed exactly.  Floating-point money would
make a thousand summed cost lines disagree with the invoice total by a few
paise, and a finance reviewer who finds one discrepancy stops trusting the whole
page.
"""

from __future__ import annotations

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
    EARLIEST_PLAUSIBLE_DATE,
    MONEY_PRECISION,
    MONEY_SCALE,
    currency_field,
    note_field,
)
from speaker_roi_analytics.ingestion.issues import IssueCode
from speaker_roi_analytics.ingestion.validators import (
    approval_requires_approver,
    no_future_period,
    single_currency_per_group,
)
from speaker_roi_core.enums import (
    ApprovalStatus,
    DatasetType,
    IssueSeverity,
    TaxonomyKind,
)

__all__ = ["CONTRACT"]


def _zero_amount_is_reported() -> RowRule:
    """A zero-value cost line is accepted but surfaced.

    Zero-value lines are usually a placeholder awaiting an invoice, or an export
    that lost its amount column.  Both mean the event's total spend is
    understated, and an understated denominator inflates ROI.  Reported as a
    warning so the reviewer can decide whether the line is genuinely free (a
    donated venue does happen) or genuinely missing.
    """

    def _check(row: RowView, _ctx: RuleContext) -> Sequence[RuleViolation]:
        amount = row.get("amount")
        if not isinstance(amount, Decimal) or amount != 0:
            return ()
        return (
            RuleViolation(
                code=IssueCode.RULE_ZERO_QUANTITY,
                field_name="amount",
                severity=IssueSeverity.WARNING,
                params={"field": "amount"},
            ),
        )

    return RowRule(
        name="zero_amount_is_reported",
        code=IssueCode.RULE_ZERO_QUANTITY,
        description="A cost line of zero is accepted but flagged, since it usually means a missing invoice.",
        fields=("amount",),
        check=_check,
    )


CONTRACT = DatasetContract(
    dataset_type=DatasetType.EVENT_COST,
    version="1.0.0",
    title="Event Costs",
    description=(
        "Actual cost lines per event: venue, speaker fees, travel, catering, agency and "
        "materials. The denominator of every ROI figure the platform reports."
    ),
    owner="Finance / Event Operations",
    cadence=Cadence.PER_EVENT,
    natural_key=("event_code", "cost_category_code", "invoice_reference"),
    duplicate_policy="LAST_WINS",
    requires_scope=(ScopeKind.EVENT,),
    fields=(
        FieldSpec(
            name="event_code",
            title="Event Code",
            dtype=DType.STRING,
            description="Event the cost belongs to. Must exist in CAMPAIGN_EVENT_MASTER.",
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
            name="cost_category_code",
            title="Cost Category Code",
            dtype=DType.STRING,
            description=(
                "Category from this tenant's cost taxonomy, e.g. venue, speaker fee, travel, "
                "catering. Categories are what make per-event cost benchmarking possible."
            ),
            taxonomy_ref=TaxonomyKind.COST_CATEGORY,
            max_length=40,
            example="COST-VENUE",
            aliases=(
                "category_code",
                "cost_category",
                "category",
                "expense_category",
                "cost_type",
                "gl_category",
                "COST_CATEGORY",
            ),
        ),
        FieldSpec(
            name="vendor_code",
            title="Vendor Code",
            dtype=DType.STRING,
            description=(
                "Supplier the cost was paid to. Optional, but it is what allows vendor-level cost "
                "benchmarking and duplicate-invoice detection across events."
            ),
            required=False,
            nullable=True,
            max_length=40,
            example="VND-CATER-01",
            aliases=("vendor", "vendor_id", "supplier_code", "supplier", "payee", "agency_code"),
        ),
        FieldSpec(
            name="amount",
            title="Amount",
            dtype=DType.DECIMAL,
            description=(
                "Cost of this line in the currency below, exclusive of nothing — supply the amount "
                "actually incurred. Must be zero or positive; refunds and credits belong on their "
                "own line with a credit-note reference, not as a negative on the original line."
            ),
            precision=MONEY_PRECISION,
            scale=MONEY_SCALE,
            minimum=Decimal("0"),
            unit="currency",
            example="185000.00",
            aliases=(
                "cost",
                "value",
                "spend",
                "amount_local",
                "line_amount",
                "invoice_amount",
                "total",
                "AMOUNT",
                "Amount",
            ),
        ),
        currency_field(
            description="ISO-4217 code for the amount on this line. All lines for one event must agree."
        ),
        FieldSpec(
            name="invoice_reference",
            title="Invoice Reference",
            dtype=DType.STRING,
            description=(
                "The supplier's invoice or credit-note number. Part of the natural key: it is what "
                "distinguishes a genuine second catering invoice from an accidental re-upload."
            ),
            max_length=80,
            example="INV-2026-118842",
            aliases=(
                "invoice_no",
                "invoice_number",
                "invoice_id",
                "inv_ref",
                "document_number",
                "bill_number",
                "po_number",
            ),
        ),
        FieldSpec(
            name="invoice_date",
            title="Invoice Date",
            dtype=DType.DATE,
            description="Date on the invoice. Used to attribute spend to a financial period.",
            required=False,
            nullable=True,
            minimum=EARLIEST_PLAUSIBLE_DATE,
            example="2026-03-20",
            aliases=("invoice_dt", "bill_date", "document_date", "date"),
        ),
        FieldSpec(
            name="approval_status",
            title="Approval Status",
            dtype=DType.ENUM,
            description=(
                "Where the line sits in the approval workflow. Only APPROVED lines are treated as "
                "confirmed spend; the rest are shown as pending so a total is never quietly "
                "provisional."
            ),
            required=False,
            nullable=True,
            enum_ref=ApprovalStatus,
            example="APPROVED",
            aliases=("status", "approval", "approval_state", "workflow_status", "APPROVAL_STATUS"),
        ),
        FieldSpec(
            name="approved_by",
            title="Approved By",
            dtype=DType.STRING,
            description=(
                "Who approved the line. Required once approval_status is APPROVED so that every "
                "confirmed cost is attributable in an audit."
            ),
            required=False,
            nullable=True,
            max_length=120,
            example="r.iyer",
            aliases=(
                "approver",
                "approved_by_user",
                "authorised_by",
                "authorized_by",
                "sign_off_by",
            ),
        ),
        note_field(
            description="Optional note on the cost line, e.g. what a miscellaneous charge covered."
        ),
    ),
    references=(
        ReferenceSpec(
            field_name="event_code",
            target=ReferenceTarget.EVENT,
            description="Must be an event declared in CAMPAIGN_EVENT_MASTER for this tenant.",
        ),
        ReferenceSpec(
            field_name="vendor_code",
            target=ReferenceTarget.VENDOR,
            description="Must be a vendor registered for this tenant, when supplied.",
            required=False,
        ),
    ),
    row_rules=(
        approval_requires_approver(),
        no_future_period(
            "invoice_date", description="invoice_date should not be dated in the future."
        ),
        _zero_amount_is_reported(),
    ),
    frame_rules=(single_currency_per_group(group_fields=("event_code",)),),
    sample_rows=(
        {
            "event_code": "EVT-2026-0417",
            "cost_category_code": "COST-VENUE",
            "vendor_code": "VND-HOTEL-04",
            "amount": "185000.00",
            "currency": "INR",
            "invoice_reference": "INV-2026-118842",
            "invoice_date": "2026-03-20",
            "approval_status": "APPROVED",
            "approved_by": "r.iyer",
            "note": "",
        },
        {
            "event_code": "EVT-2026-0417",
            "cost_category_code": "COST-SPEAKER-FEE",
            "vendor_code": "VND-FACULTY-11",
            "amount": "120000.00",
            "currency": "INR",
            "invoice_reference": "INV-2026-118901",
            "invoice_date": "2026-03-22",
            "approval_status": "APPROVED",
            "approved_by": "r.iyer",
            "note": "Honorarium per fair-market-value schedule.",
        },
        {
            "event_code": "EVT-2026-0417",
            "cost_category_code": "COST-TRAVEL",
            "vendor_code": "VND-TRAVEL-02",
            "amount": "43250.50",
            "currency": "INR",
            "invoice_reference": "INV-2026-119010",
            "invoice_date": "2026-03-25",
            "approval_status": "SUBMITTED",
            "approved_by": "",
            "note": "",
        },
        {
            "event_code": "EVT-2026-0418",
            "cost_category_code": "COST-PLATFORM",
            "vendor_code": "VND-WEBINAR-01",
            "amount": "26000.00",
            "currency": "INR",
            "invoice_reference": "INV-2026-119344",
            "invoice_date": "2026-04-08",
            "approval_status": "APPROVED",
            "approved_by": "s.menon",
            "note": "",
        },
    ),
    notes=(
        "Send every line, including small ones. An incomplete cost file makes a programme look "
        "more efficient than it was, and that error is rarely questioned.",
        "All cost lines for one event must use the same currency. The platform never converts "
        "between currencies (PLAN_REVIEW F-14); mixed-currency events are quarantined for restatement.",
        "Credits and refunds go on their own line with the credit-note reference. Negative "
        "amounts are rejected so that a sign error cannot quietly reduce an event total.",
    ),
)
