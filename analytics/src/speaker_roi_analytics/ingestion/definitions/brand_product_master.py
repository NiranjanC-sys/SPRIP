"""``BRAND_PRODUCT_MASTER`` — the brand and product reference list (plan.md §10.1).

Everything else in the platform hangs off this file.  A brand code that is not
declared here cannot be referenced by a campaign, a cost line, an Rx row or a
finance assumption, which is deliberate: it is the mechanism that stops four
teams inventing four spellings of the same brand and producing four ROI figures.

One row per *product*; the brand attributes repeat across the products of a
brand and are reconciled on load (a brand whose name differs between two of its
own rows is rejected, because we would otherwise have to pick one silently).
"""

from __future__ import annotations

from collections.abc import Sequence

from speaker_roi_analytics.ingestion.contracts import (
    Cadence,
    DatasetContract,
    DType,
    FieldSpec,
    FrameRule,
    FrameViolation,
    RowView,
    RuleContext,
)
from speaker_roi_analytics.ingestion.definitions._common import EARLIEST_PLAUSIBLE_DATE
from speaker_roi_analytics.ingestion.issues import IssueCode
from speaker_roi_core.enums import DatasetType, IssueSeverity, TaxonomyKind

__all__ = ["CONTRACT"]


def _consistent_brand_attributes() -> FrameRule:
    """A brand code must describe one brand throughout the file.

    Two rows sharing ``brand_code`` but disagreeing on ``brand_name`` mean the
    file has either a typo or two genuinely different brands sharing a code.
    Neither can be resolved by rule, and picking the first occurrence would bake
    a typo into the dimension every downstream report reads, so both rows are
    quarantined for the owner to correct.
    """

    def _check(rows: Sequence[RowView], _ctx: RuleContext) -> Sequence[FrameViolation]:
        seen: dict[str, dict[str, list[int]]] = {}
        for row in rows:
            code = row.get("brand_code")
            name = row.get("brand_name")
            if code is None or name is None:
                continue
            bucket = seen.setdefault(str(code).strip().casefold(), {})
            bucket.setdefault(str(name).strip().casefold(), []).append(row.ordinal)

        out: list[FrameViolation] = []
        for names in seen.values():
            if len(names) < 2:
                continue
            ordinals = tuple(sorted(o for group in names.values() for o in group))
            out.append(
                FrameViolation(
                    code=IssueCode.SCHEMA_AMBIGUOUS_COLUMN_MATCH,
                    ordinals=ordinals,
                    field_name="brand_name",
                    severity=IssueSeverity.QUARANTINE,
                    params={
                        "field": "brand_name",
                        "candidates": "conflicting brand names for one brand_code",
                    },
                    drop_ordinals=ordinals,
                )
            )
        return tuple(out)

    return FrameRule(
        name="consistent_brand_attributes",
        code=IssueCode.SCHEMA_AMBIGUOUS_COLUMN_MATCH,
        description="All rows sharing a brand_code must use the same brand_name.",
        fields=("brand_code", "brand_name"),
        check=_check,
    )


CONTRACT = DatasetContract(
    dataset_type=DatasetType.BRAND_PRODUCT_MASTER,
    version="1.0.0",
    title="Brand and Product Master",
    description=(
        "The authoritative list of brands and their products for a tenant. Every other "
        "dataset references a brand or product code declared here."
    ),
    owner="Brand / Commercial Operations",
    cadence=Cadence.ONE_TIME,
    natural_key=("brand_code", "product_code"),
    duplicate_policy="REJECT",
    fields=(
        FieldSpec(
            name="brand_code",
            title="Brand Code",
            dtype=DType.STRING,
            description="Stable short code for the brand. Used as the join key by every other dataset.",
            max_length=40,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-.]{0,39}$",
            example="BRD-ALPHA",
            aliases=("brand", "brand_id", "brand_key", "brand_cd", "BRAND_CODE", "Brand Code"),
        ),
        FieldSpec(
            name="brand_name",
            title="Brand Name",
            dtype=DType.STRING,
            description="Marketed brand name as it should appear on dashboards.",
            max_length=200,
            example="Alphamax",
            aliases=("brand_description", "brand_label", "BRAND_NAME", "Brand Name"),
        ),
        FieldSpec(
            name="therapeutic_area_code",
            title="Therapeutic Area Code",
            dtype=DType.STRING,
            description="Therapeutic area from this tenant's taxonomy. Used to group brands in portfolio views.",
            required=False,
            nullable=True,
            taxonomy_ref=TaxonomyKind.THERAPEUTIC_AREA,
            max_length=40,
            example="TA-CARDIO",
            aliases=("therapeutic_area", "ta", "ta_code", "therapy_area", "franchise", "TA_CODE"),
        ),
        FieldSpec(
            name="molecule",
            title="Molecule",
            dtype=DType.STRING,
            description="Active molecule or INN. Informational; not used in any calculation.",
            required=False,
            nullable=True,
            max_length=200,
            example="Alphastatin",
            aliases=("inn", "generic_name", "active_ingredient", "salt", "composition"),
        ),
        FieldSpec(
            name="brand_launch_date",
            title="Brand Launch Date",
            dtype=DType.DATE,
            description=(
                "Date the brand was launched in this market. Used to exclude pre-launch months "
                "from baselines, where a zero is structural rather than behavioural."
            ),
            required=False,
            nullable=True,
            minimum=EARLIEST_PLAUSIBLE_DATE,
            example="2023-04-01",
            aliases=("launch_date", "brand_launch", "date_of_launch", "LAUNCH_DATE"),
        ),
        FieldSpec(
            name="product_code",
            title="Product Code",
            dtype=DType.STRING,
            description="Stable short code for the sellable product (pack/SKU grain). Rx data is supplied at this grain.",
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
        FieldSpec(
            name="product_name",
            title="Product Name",
            dtype=DType.STRING,
            description="Product name including strength and pack, as printed on the pack.",
            max_length=200,
            example="Alphamax 10mg 30s",
            aliases=("product_description", "sku_name", "pack_name", "PRODUCT_NAME"),
        ),
        FieldSpec(
            name="formulation",
            title="Formulation",
            dtype=DType.STRING,
            description="Dosage form, e.g. tablet, capsule, injection.",
            required=False,
            nullable=True,
            max_length=60,
            example="Tablet",
            aliases=("dosage_form", "form", "presentation"),
        ),
        FieldSpec(
            name="strength",
            title="Strength",
            dtype=DType.STRING,
            description="Strength as printed, e.g. 10mg. Free text because units vary by form.",
            required=False,
            nullable=True,
            max_length=60,
            example="10mg",
            aliases=("dose", "dosage", "potency"),
        ),
        FieldSpec(
            name="pack_size",
            title="Pack Size",
            dtype=DType.INTEGER,
            description="Units per pack. Used only for display; the platform counts prescriptions, not units.",
            required=False,
            nullable=True,
            minimum=1,
            maximum=100_000,
            example="30",
            aliases=("pack", "units_per_pack", "pack_qty", "pack_units"),
        ),
        FieldSpec(
            name="is_active",
            title="Is Active",
            dtype=DType.BOOLEAN,
            description=(
                "Whether the product is currently marketed. Inactive products stay in the master so "
                "historical Rx rows keep resolving; they are excluded from new programme planning."
            ),
            required=False,
            nullable=True,
            example="true",
            aliases=("active", "active_flag", "is_current", "status_active", "in_market"),
        ),
    ),
    frame_rules=(_consistent_brand_attributes(),),
    sample_rows=(
        {
            "brand_code": "BRD-ALPHA",
            "brand_name": "Alphamax",
            "therapeutic_area_code": "TA-CARDIO",
            "molecule": "Alphastatin",
            "brand_launch_date": "2023-04-01",
            "product_code": "PRD-ALPHA-10",
            "product_name": "Alphamax 10mg 30s",
            "formulation": "Tablet",
            "strength": "10mg",
            "pack_size": "30",
            "is_active": "true",
        },
        {
            "brand_code": "BRD-ALPHA",
            "brand_name": "Alphamax",
            "therapeutic_area_code": "TA-CARDIO",
            "molecule": "Alphastatin",
            "brand_launch_date": "2023-04-01",
            "product_code": "PRD-ALPHA-20",
            "product_name": "Alphamax 20mg 30s",
            "formulation": "Tablet",
            "strength": "20mg",
            "pack_size": "30",
            "is_active": "true",
        },
        {
            "brand_code": "BRD-BETA",
            "brand_name": "Betacare",
            "therapeutic_area_code": "TA-DIABETES",
            "molecule": "Betagliptin",
            "brand_launch_date": "2024-07-15",
            "product_code": "PRD-BETA-50",
            "product_name": "Betacare 50mg 14s",
            "formulation": "Tablet",
            "strength": "50mg",
            "pack_size": "14",
            "is_active": "true",
        },
        {
            "brand_code": "BRD-BETA",
            "brand_name": "Betacare",
            "therapeutic_area_code": "TA-DIABETES",
            "molecule": "Betagliptin",
            "brand_launch_date": "2024-07-15",
            "product_code": "PRD-BETA-100",
            "product_name": "Betacare 100mg 14s",
            "formulation": "Tablet",
            "strength": "100mg",
            "pack_size": "14",
            "is_active": "false",
        },
    ),
    notes=(
        "Load this file before any other dataset: brand and product codes here are the "
        "reference every other contract validates against.",
        "Retiring a product means setting is_active to false, never deleting the row — "
        "historical Rx and cost rows must keep resolving.",
    ),
)
