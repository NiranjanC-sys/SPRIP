"""``FINANCE_ASSUMPTIONS`` — the money rules behind every ROI figure (plan.md §10.1, §11).

Impact is measured; **value is assumed**.  The platform can demonstrate that a
programme moved prescriptions; converting that movement into rupees requires a
contribution-per-NRx that finance owns, not analytics.  Keeping the assumption in
its own versioned, effective-dated file means an ROI number can always be
decomposed into "this much measured lift" times "this much assumed value", and a
disagreement about the money can be settled without re-running any model.

The two structural rules:

* **Half-open effective ranges.**  ``[effective_from, effective_to)``, with an
  empty ``effective_to`` meaning "currently in force" (plan.md §9.2).  Equal
  endpoints describe a zero-length window that no date can match, so they are
  rejected rather than loaded as a silent no-op.

* **No overlaps within a (brand, scenario).**  If two rows for the same brand and
  scenario cover the same day, "the assumption in force on date D" stops being a
  function and every ROI figure over that window depends on row order. That is
  not reproducible and cannot survive a finance review, so both rows are
  quarantined
  (:func:`~speaker_roi_analytics.ingestion.validators.no_overlapping_effective_ranges`).

Scenarios are not a hedge — they are the honest presentation of an assumption.
Every ROI figure in the product is reported against a named scenario so that
"conservative" and "optimistic" are visible choices rather than a single number
whose provenance nobody remembers.
"""

from __future__ import annotations

from decimal import Decimal

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
    MONEY_PRECISION,
    MONEY_SCALE,
    brand_code_field,
    currency_field,
    note_field,
)
from speaker_roi_analytics.ingestion.validators import (
    effective_range_half_open,
    no_overlapping_effective_ranges,
)
from speaker_roi_core.enums import DatasetType, FinanceScenario

__all__ = ["CONTRACT"]


CONTRACT = DatasetContract(
    dataset_type=DatasetType.FINANCE_ASSUMPTIONS,
    version="1.0.0",
    title="Finance Assumptions",
    description=(
        "Effective-dated financial assumptions per brand and scenario: contribution per new "
        "prescription, currency and persistence. Converts measured lift into monetary value."
    ),
    owner="Finance",
    cadence=Cadence.QUARTERLY,
    natural_key=("finance_version_label", "brand_code", "scenario", "effective_from"),
    duplicate_policy="REJECT",
    requires_scope=(ScopeKind.BRAND,),
    fields=(
        FieldSpec(
            name="finance_version_label",
            title="Finance Version Label",
            dtype=DType.STRING,
            description=(
                "Label of the assumption set this row belongs to, e.g. FY27-BUDGET. Every ROI "
                "figure the platform publishes names the version it was computed against, so a "
                "restated assumption never silently rewrites a number someone already presented."
            ),
            max_length=60,
            example="FY27-BUDGET",
            aliases=(
                "version_label",
                "finance_version",
                "assumption_set",
                "budget_version",
                "plan_version",
                "version",
            ),
        ),
        brand_code_field(
            description="Brand the assumption applies to. Must exist in BRAND_PRODUCT_MASTER."
        ),
        FieldSpec(
            name="scenario",
            title="Scenario",
            dtype=DType.ENUM,
            description=(
                "Which assumption scenario this row describes. Every published ROI figure is "
                "labelled with its scenario; the platform never blends scenarios into one number."
            ),
            enum_ref=FinanceScenario,
            example="BASE",
            aliases=("case", "scenario_name", "assumption_scenario", "sensitivity", "SCENARIO"),
        ),
        FieldSpec(
            name="contribution_per_nrx",
            title="Contribution per NRx",
            dtype=DType.DECIMAL,
            description=(
                "Gross margin contribution attributed to one new prescription, in the currency "
                "below. This is the multiplier that turns measured lift into value; it is an "
                "assumption owned by finance and is always reported alongside the result."
            ),
            precision=MONEY_PRECISION,
            scale=MONEY_SCALE,
            minimum=Decimal("0"),
            unit="currency per prescription",
            example="1450.00",
            aliases=(
                "contribution",
                "margin_per_nrx",
                "value_per_nrx",
                "contribution_per_script",
                "gross_margin_per_nrx",
                "cm_per_nrx",
                "revenue_per_nrx",
            ),
        ),
        currency_field(
            description="ISO-4217 code for contribution_per_nrx. Never converted by the platform."
        ),
        FieldSpec(
            name="persistence_months",
            title="Persistence Months",
            dtype=DType.INTEGER,
            description=(
                "How many months of the observed lift finance is willing to count as durable "
                "value. Documented as an assumption and shown as one — the platform never "
                "presents a persistence multiplier as a finding."
            ),
            required=False,
            nullable=True,
            minimum=0,
            maximum=120,
            unit="months",
            example="6",
            aliases=(
                "persistence",
                "durability_months",
                "carryover_months",
                "retention_months",
                "months_persisted",
            ),
        ),
        FieldSpec(
            name="effective_from",
            title="Effective From",
            dtype=DType.DATE,
            description="First day this assumption applies. Half-open range: [effective_from, effective_to).",
            example="2026-04-01",
            aliases=("valid_from", "start_date", "from_date", "effective_start", "EFFECTIVE_FROM"),
        ),
        FieldSpec(
            name="effective_to",
            title="Effective To",
            dtype=DType.DATE,
            description=(
                "First day this assumption no longer applies (exclusive). Leave blank for the "
                "assumption currently in force."
            ),
            required=False,
            nullable=True,
            example="",
            aliases=("valid_to", "end_date", "to_date", "effective_end", "EFFECTIVE_TO"),
        ),
        note_field(
            description=(
                "Optional note recording where the assumption came from, e.g. the finance paper "
                "or committee that approved it."
            )
        ),
    ),
    references=(
        ReferenceSpec(
            field_name="brand_code",
            target=ReferenceTarget.BRAND,
            description="Must be a brand declared in BRAND_PRODUCT_MASTER for this tenant.",
        ),
    ),
    row_rules=(effective_range_half_open(),),
    frame_rules=(
        no_overlapping_effective_ranges(
            key_fields=("brand_code", "scenario"),
            description=(
                "For any brand and scenario, at most one assumption may be in force on a given "
                "day. Overlapping ranges would make ROI depend on row order."
            ),
        ),
    ),
    sample_rows=(
        {
            "finance_version_label": "FY27-BUDGET",
            "brand_code": "BRD-ALPHA",
            "scenario": "BASE",
            "contribution_per_nrx": "1450.00",
            "currency": "INR",
            "persistence_months": "6",
            "effective_from": "2026-04-01",
            "effective_to": "",
            "note": "Approved at the March finance committee.",
        },
        {
            "finance_version_label": "FY27-BUDGET",
            "brand_code": "BRD-ALPHA",
            "scenario": "CONSERVATIVE",
            "contribution_per_nrx": "1100.00",
            "currency": "INR",
            "persistence_months": "3",
            "effective_from": "2026-04-01",
            "effective_to": "",
            "note": "",
        },
        {
            "finance_version_label": "FY27-BUDGET",
            "brand_code": "BRD-ALPHA",
            "scenario": "OPTIMISTIC",
            "contribution_per_nrx": "1780.00",
            "currency": "INR",
            "persistence_months": "9",
            "effective_from": "2026-04-01",
            "effective_to": "",
            "note": "",
        },
        {
            "finance_version_label": "FY27-BUDGET",
            "brand_code": "BRD-BETA",
            "scenario": "BASE",
            "contribution_per_nrx": "980.00",
            "currency": "INR",
            "persistence_months": "6",
            "effective_from": "2026-04-01",
            "effective_to": "2026-10-01",
            "note": "Superseded from October after the price revision.",
        },
        {
            "finance_version_label": "FY27-BUDGET",
            "brand_code": "BRD-BETA",
            "scenario": "BASE",
            "contribution_per_nrx": "1040.00",
            "currency": "INR",
            "persistence_months": "6",
            "effective_from": "2026-10-01",
            "effective_to": "",
            "note": "Post price-revision contribution.",
        },
    ),
    notes=(
        "Ranges are half-open. To supersede an assumption, close the old row with an "
        "effective_to equal to the new row's effective_from — no gap, no overlap.",
        "Supply all three scenarios where you can. A single number invites the reader to treat "
        "an assumption as a measurement.",
        "The platform never converts currencies (PLAN_REVIEW F-14). Assumptions and costs must "
        "be stated in the currency the programme was actually run in.",
    ),
)
