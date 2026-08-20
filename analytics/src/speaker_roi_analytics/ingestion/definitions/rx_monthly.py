"""``RX_MONTHLY`` — monthly prescription measures per professional and product (plan.md §10.1).

This is the outcome variable.  Every impact and ROI figure the platform produces
is ultimately a statement about the numbers in this file, so the contract is
stricter here than anywhere else.

Three properties matter more than the rest:

**Missing is not zero.**  A month with ``nrx = 0`` says the professional wrote
nothing.  A month the supplier did not cover says nothing at all.  Averaging the
two together drags every lift estimate towards zero, and the bias is invisible —
the result simply looks disappointing.  ``is_observed`` is therefore *required*,
and :func:`~speaker_roi_analytics.ingestion.validators.distinguish_missing_from_zero`
rejects the contradictory combination ``nrx = 0`` with ``is_observed = false``.
Plan.md §10.2 makes this its own validation gate.

**Suppression is declared, not inferred.**  Rx suppliers withhold small-cell
counts for privacy.  That is a legitimate reason for a blank measure on an
observed month, but it must be flagged: an undeclared blank is
indistinguishable from a broken export, and the two are modelled differently.

**The supplier's definition travels with the data.**  Plan.md §4: "Preserve the
supplier definition."  NRx means different things to different panels — new
patient starts, new-to-brand, first fills — and a definition change mid-series
looks exactly like a behaviour change.  ``supplier_definition_version`` is
required so that a change is a visible fact on the Data Health page rather than
a mysterious step in a trend line.
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
    brand_code_field,
    month_field,
    source_hcp_id_field,
    source_system_field,
)
from speaker_roi_analytics.ingestion.validators import (
    coverage_factor_sufficient,
    distinguish_missing_from_zero,
    no_future_period,
    suppression_consistent,
    trx_not_below_nrx,
)
from speaker_roi_core.enums import DatasetType

__all__ = ["CONTRACT"]


def _count_field(
    name: str,
    title: str,
    description: str,
    *,
    aliases: tuple[str, ...],
    example: str,
    required: bool = True,
) -> FieldSpec:
    """A non-negative prescription count.

    Nullable because suppression and unobserved periods are both real; the row
    rules decide whether a particular blank is acceptable.  Capped at a million
    per professional-month: a larger value is a units error (a market total
    pasted into a professional-level column), and admitting one would dominate
    every aggregate it touches.

    ``required=False`` is used for the market-context measures.  Most panel
    licences cover the brand's own NRx/TRx and nothing else, and refusing a
    file for the absence of a covariate the models treat as optional would
    block the primary outcome series over a nice-to-have.
    """
    return FieldSpec(
        name=name,
        title=title,
        dtype=DType.INTEGER,
        description=description,
        required=required,
        nullable=True,
        minimum=0,
        maximum=1_000_000,
        unit="prescriptions",
        example=example,
        aliases=aliases,
    )


CONTRACT = DatasetContract(
    dataset_type=DatasetType.RX_MONTHLY,
    version="1.0.0",
    title="Monthly Prescription Measures",
    description=(
        "Monthly NRx and TRx per healthcare professional and product, with explicit coverage, "
        "suppression and observation flags. The outcome variable for every impact estimate."
    ),
    owner="Rx Data Supplier / Commercial Analytics",
    cadence=Cadence.MONTHLY,
    natural_key=("source_system", "source_hcp_id", "product_code", "month"),
    duplicate_policy="LAST_WINS",
    requires_scope=(ScopeKind.BRAND,),
    fields=(
        source_system_field(),
        source_hcp_id_field(
            description="The panel's identifier for the prescriber. Resolved through HCP_CROSSWALK."
        ),
        FieldSpec(
            name="product_code",
            title="Product Code",
            dtype=DType.STRING,
            description=(
                "Product the measures relate to. Must exist in BRAND_PRODUCT_MASTER; the brand "
                "is derived from it and cross-checked against brand_code."
            ),
            max_length=40,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-.]{0,39}$",
            example="PRD-ALPHA-10",
            aliases=(
                "product",
                "product_id",
                "sku",
                "sku_code",
                "pack_code",
                "material_code",
                "PRODUCT_CODE",
            ),
        ),
        brand_code_field(
            description=(
                "Brand the product belongs to. Supplied redundantly so a mis-mapped product code "
                "is caught at intake rather than after aggregation."
            )
        ),
        month_field(
            description=(
                "Month the measures cover. Accepted forms: 2026-03, 2026-03-01, 03/2026, Mar-26. "
                "Stored as the first day of the month so partial-month dating cannot split a period."
            ),
            example="2026-03",
        ),
        _count_field(
            "nrx",
            "NRx",
            (
                "New prescriptions in the month, using your panel's own definition. Leave blank "
                "only when the month was not observed or the cell is suppressed — a genuine zero "
                "must be written as 0 with is_observed = true."
            ),
            aliases=(
                "new_rx",
                "new_prescriptions",
                "nrx_count",
                "n_rx",
                "newscripts",
                "new_scripts",
                "NRX",
                "NRx",
            ),
            example="4",
        ),
        _count_field(
            "trx",
            "TRx",
            (
                "Total prescriptions in the month, using your panel's own definition. TRx "
                "normally includes NRx, so a TRx below NRx is flagged as a probable column swap."
            ),
            aliases=(
                "total_rx",
                "total_prescriptions",
                "trx_count",
                "t_rx",
                "totalscripts",
                "total_scripts",
                "TRX",
                "TRx",
            ),
            example="17",
        ),
        _count_field(
            "competitor_trx",
            "Competitor TRx",
            (
                "Total prescriptions the professional wrote for competing products in the same "
                "class. Used as a control for market-level movement, so that a category-wide "
                "shift is not reported as programme impact."
            ),
            aliases=(
                "comp_trx",
                "competitor_total_rx",
                "competitive_trx",
                "other_brand_trx",
                "rival_trx",
            ),
            example="52",
            required=False,
        ),
        _count_field(
            "market_trx",
            "Market TRx",
            (
                "Total prescriptions across the whole class for this professional. Provides the "
                "denominator for share-based outcomes, which are far more robust to panel "
                "coverage changes than raw counts."
            ),
            aliases=(
                "class_trx",
                "category_trx",
                "total_market_rx",
                "market_total_rx",
                "universe_trx",
            ),
            example="69",
            required=False,
        ),
        FieldSpec(
            name="is_observed",
            title="Is Observed",
            dtype=DType.BOOLEAN,
            description=(
                "Whether your panel actually covered this professional and product in this month. "
                "Required, and the single most important flag in the file: it is what separates "
                "'wrote nothing' from 'we do not know'."
            ),
            required=True,
            nullable=False,
            example="true",
            aliases=(
                "observed",
                "is_covered",
                "covered",
                "has_data",
                "in_panel",
                "panel_covered",
                "data_available",
                "OBSERVED",
                "IS_OBSERVED",
            ),
        ),
        FieldSpec(
            name="coverage_factor",
            title="Coverage Factor",
            dtype=DType.DECIMAL,
            description=(
                "Share of this professional's prescribing your panel sees, in (0, 1]. 1 means "
                "full capture. Values below the review threshold are flagged: the projection "
                "multiplier becomes large enough that panel noise dominates the estimate."
            ),
            required=False,
            nullable=True,
            precision=6,
            scale=4,
            minimum=Decimal("0"),
            min_exclusive=True,
            maximum=Decimal("1"),
            example="0.8500",
            aliases=(
                "coverage",
                "panel_coverage",
                "projection_factor",
                "capture_rate",
                "coverage_pct",
                "coverage_ratio",
                "COVERAGE_FACTOR",
            ),
        ),
        FieldSpec(
            name="suppression_flag",
            title="Suppression Flag",
            dtype=DType.BOOLEAN,
            description=(
                "True when the supplier withheld the value for small-cell privacy reasons. A "
                "suppressed cell is known-small; a missing cell is unknown, and the two are "
                "modelled differently. A suppressed row must leave the measures blank. "
                "Optional: a panel that never suppresses simply omits the column, and every "
                "row is read as not suppressed."
            ),
            required=False,
            nullable=True,
            example="false",
            aliases=(
                "suppressed",
                "is_suppressed",
                "small_cell",
                "small_cell_flag",
                "privacy_suppressed",
                "masked",
                "SUPPRESSION_FLAG",
            ),
        ),
        FieldSpec(
            name="supplier_definition_version",
            title="Supplier Definition Version",
            dtype=DType.STRING,
            description=(
                "The version label of your own NRx/TRx definition. Preserved verbatim (plan.md §4): "
                "a definition change mid-series looks identical to a behaviour change, so the "
                "platform surfaces it as a definition-change flag rather than silently comparing "
                "across the boundary."
            ),
            required=True,
            nullable=False,
            max_length=60,
            example="PANEL-NRX-2026.01",
            aliases=(
                "definition_version",
                "metric_definition",
                "metric_version",
                "supplier_version",
                "supplier_def_ver",
                "supplier_def_version",
                "data_definition_version",
                "panel_definition_version",
                "rx_definition_version",
                "methodology_version",
                "spec_version",
                "DEFINITION_VERSION",
            ),
        ),
    ),
    references=(
        ReferenceSpec(
            field_name="product_code",
            target=ReferenceTarget.PRODUCT,
            description="Must be a product declared in BRAND_PRODUCT_MASTER for this tenant.",
        ),
        ReferenceSpec(
            field_name="brand_code",
            target=ReferenceTarget.BRAND,
            description="Must be the brand that owns the product code on the same row.",
        ),
        ReferenceSpec(
            field_name="source_system",
            target=ReferenceTarget.SOURCE_SYSTEM,
            description="Must be a source system registered for this tenant.",
        ),
    ),
    row_rules=(
        distinguish_missing_from_zero(),
        # Only the brand's own measures are held to the suppression rule.
        # competitor_trx and market_trx are optional enrichments that many panels
        # simply do not license, and demanding them would reject perfectly
        # loadable files for a covariate the models treat as nice-to-have.
        suppression_consistent(measure_fields=("nrx", "trx")),
        trx_not_below_nrx(),
        coverage_factor_sufficient(),
        no_future_period(
            "month", description="month should not be dated beyond the current period."
        ),
    ),
    sample_rows=(
        {
            "source_system": "RXPANEL",
            "source_hcp_id": "RX-77213",
            "product_code": "PRD-ALPHA-10",
            "brand_code": "BRD-ALPHA",
            "month": "2026-01",
            "nrx": "4",
            "trx": "17",
            "competitor_trx": "52",
            "market_trx": "69",
            "is_observed": "true",
            "coverage_factor": "0.8500",
            "suppression_flag": "false",
            "supplier_definition_version": "PANEL-NRX-2026.01",
        },
        {
            "source_system": "RXPANEL",
            "source_hcp_id": "RX-77213",
            "product_code": "PRD-ALPHA-10",
            "brand_code": "BRD-ALPHA",
            "month": "2026-02",
            "nrx": "0",
            "trx": "12",
            "competitor_trx": "55",
            "market_trx": "67",
            "is_observed": "true",
            "coverage_factor": "0.8500",
            "suppression_flag": "false",
            "supplier_definition_version": "PANEL-NRX-2026.01",
        },
        {
            "source_system": "RXPANEL",
            "source_hcp_id": "RX-77213",
            "product_code": "PRD-ALPHA-10",
            "brand_code": "BRD-ALPHA",
            "month": "2026-03",
            "nrx": "",
            "trx": "",
            "competitor_trx": "",
            "market_trx": "",
            "is_observed": "false",
            "coverage_factor": "",
            "suppression_flag": "false",
            "supplier_definition_version": "PANEL-NRX-2026.01",
        },
        {
            "source_system": "RXPANEL",
            "source_hcp_id": "RX-90881",
            "product_code": "PRD-BETA-50",
            "brand_code": "BRD-BETA",
            "month": "2026-03",
            "nrx": "",
            "trx": "",
            "competitor_trx": "",
            "market_trx": "",
            "is_observed": "true",
            "coverage_factor": "0.6200",
            "suppression_flag": "true",
            "supplier_definition_version": "PANEL-NRX-2026.01",
        },
    ),
    notes=(
        "Send a row for every professional-product-month in scope, including months with no "
        "prescribing. Omitting a month is not the same as reporting a zero, and the platform "
        "cannot tell the difference from the file alone — which is why is_observed is required.",
        "A genuine zero is nrx = 0 with is_observed = true. An unobserved month is a blank nrx "
        "with is_observed = false. The combination nrx = 0 with is_observed = false is rejected.",
        "Change supplier_definition_version whenever your NRx or TRx definition changes. The "
        "platform will not compare across a definition boundary without flagging it.",
    ),
)
