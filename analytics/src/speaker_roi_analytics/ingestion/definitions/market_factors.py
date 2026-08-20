"""``MARKET_FACTORS`` — monthly market context per brand and region (plan.md §10.1).

Prescribing moves for reasons that have nothing to do with speaker programmes:
a formulary win, a competitor launch, a seasonal illness peak, a tender cycle.
Where those movements coincide with programme activity — and they often do,
because brands schedule programmes around exactly these events — an
uncontrolled model will attribute the market's movement to the programme.

These indices are the control.  They are supplied at brand-and-region-month
grain, deliberately *not* at professional grain: this is context, not a
prescriber-level covariate, and keeping the grain coarse means the file carries
no personal data at all.

Each index is normalised around 1.0 and bounded at ``[0, 10]``.  A value outside
that band is a units mistake — a percentage, or a raw count — and would swamp
every covariate it competes with, so it is rejected rather than winsorised.
"""

from __future__ import annotations

from speaker_roi_analytics.ingestion.contracts import (
    Cadence,
    DatasetContract,
    ReferenceSpec,
    ReferenceTarget,
    ScopeKind,
)
from speaker_roi_analytics.ingestion.definitions._common import (
    brand_code_field,
    index_field,
    month_field,
    note_field,
    region_code_field,
)
from speaker_roi_analytics.ingestion.validators import no_future_period
from speaker_roi_core.enums import DatasetType

__all__ = ["CONTRACT"]


CONTRACT = DatasetContract(
    dataset_type=DatasetType.MARKET_FACTORS,
    version="1.0.0",
    title="Market Factors",
    description=(
        "Monthly market context per brand and region — access, seasonality, competitive "
        "pressure and market size — used to separate market movement from programme effect."
    ),
    owner="Commercial Analytics",
    cadence=Cadence.MONTHLY,
    natural_key=("brand_code", "region_code", "month"),
    duplicate_policy="LAST_WINS",
    requires_scope=(ScopeKind.BRAND,),
    fields=(
        brand_code_field(
            description="Brand the context applies to. Must exist in BRAND_PRODUCT_MASTER."
        ),
        region_code_field(
            description="Region the context applies to, from the tenant region taxonomy."
        ),
        month_field(
            description=(
                "Month the indices describe. Accepted forms: 2026-03, 2026-03-01, 03/2026, Mar-26. "
                "Aligned to the Rx month grain."
            ),
            example="2026-03",
        ),
        index_field(
            "access_index",
            "Access Index",
            (
                "Relative formulary or reimbursement access, normalised so that 1.0 is the brand's "
                "own baseline. A formulary win shows up here rather than as unexplained programme lift."
            ),
            example="1.0500",
            aliases=(
                "access",
                "formulary_index",
                "reimbursement_index",
                "coverage_index",
                "access_score",
            ),
        ),
        index_field(
            "seasonality_index",
            "Seasonality Index",
            (
                "Expected seasonal multiplier for the category in this month, 1.0 being an average "
                "month. Without it, a programme run into a seasonal peak looks unusually effective."
            ),
            example="1.1200",
            aliases=("seasonality", "season_index", "seasonal_factor", "seasonal_multiplier"),
        ),
        index_field(
            "competitor_index",
            "Competitor Index",
            (
                "Relative competitive pressure, 1.0 being the baseline. Rises with competitor "
                "launches and promotional surges."
            ),
            example="0.9800",
            aliases=("competition_index", "competitive_pressure", "comp_index", "rival_index"),
        ),
        index_field(
            "market_size_index",
            "Market Size Index",
            (
                "Relative size of the addressable market in this region-month, 1.0 being baseline. "
                "Separates a growing market from a growing share of a flat one."
            ),
            example="1.0300",
            aliases=(
                "market_size",
                "market_index",
                "category_size_index",
                "universe_index",
                "potential_index",
            ),
        ),
        note_field(
            name="notes",
            title="Notes",
            description=(
                "Optional explanation of a notable movement, e.g. 'competitor generic entry from "
                "March'. Shown to reviewers alongside the indices; never used in any calculation."
            ),
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
        no_future_period(
            "month",
            description=(
                "month may run one period ahead for planning, but a far-future row is usually a "
                "stale template."
            ),
        ),
    ),
    sample_rows=(
        {
            "brand_code": "BRD-ALPHA",
            "region_code": "IN-WEST",
            "month": "2026-01",
            "access_index": "1.0000",
            "seasonality_index": "0.9600",
            "competitor_index": "1.0000",
            "market_size_index": "1.0000",
            "notes": "",
        },
        {
            "brand_code": "BRD-ALPHA",
            "region_code": "IN-WEST",
            "month": "2026-02",
            "access_index": "1.0500",
            "seasonality_index": "1.0200",
            "competitor_index": "0.9800",
            "market_size_index": "1.0100",
            "notes": "State formulary listing effective 01 Feb.",
        },
        {
            "brand_code": "BRD-BETA",
            "region_code": "IN-SOUTH",
            "month": "2026-02",
            "access_index": "0.9200",
            "seasonality_index": "1.1200",
            "competitor_index": "1.1500",
            "market_size_index": "1.0300",
            "notes": "Competitor generic entry from February.",
        },
    ),
    notes=(
        "Indices are relative, not absolute: 1.0 means 'as expected', not '100%'. Anything "
        "outside [0, 10] is treated as a units error and rejected.",
        "Cover the full measurement window, including the pre-programme months. A control that "
        "only exists after the event cannot control for anything.",
        "This file is deliberately coarse-grained. It carries no professional-level data and no "
        "personal data of any kind.",
    ),
)
