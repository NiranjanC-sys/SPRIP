"""Tenants, brands, products, vendors and the controlled vocabularies.

Two tenants exist because multi-tenant isolation is a *correctness* property in
plan.md §5, not a configuration flag, and a single-tenant dataset cannot catch a
missing ``WHERE tenant_id = ...``. The two tenants deliberately differ in shape:
different brand counts, different therapeutic areas, different region names and
different source-system ID formats, so a leak shows up as an obviously foreign
value rather than a plausible one.

Every vocabulary value that the platform has an enum for is taken from
``speaker_roi_core.enums`` - status strings are never re-spelled here. The
*content* vocabularies the platform does not enumerate (region names, topic
names, specialty names) are defined below, as data, with the per-row attributes
the DGP needs (region remoteness, specialty therapeutic area).
"""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from speaker_roi_core.enums import TaxonomyKind, VendorStatus

from .config import SyntheticProfile

__all__ = [
    "REGIONS",
    "SPECIALTIES",
    "TOPICS",
    "Taxonomies",
    "TenantSpec",
    "build_taxonomies",
    "stable_uuid",
]

#: Namespace for deterministic UUIDs. Real UUID4s would be re-randomised on
#: every run; uuid5 over a stable business key means the same logical row keeps
#: the same surrogate key across runs, which is what makes the SHA-256 frame
#: checksums in the manifest meaningful.
_UUID_NAMESPACE: Final[uuid.UUID] = uuid.UUID("6f3d0a9e-2b41-5f77-9a6a-0f5b7c9d1e23")


def stable_uuid(*parts: object) -> str:
    """Deterministic surrogate key from a business key."""
    return str(uuid.uuid5(_UUID_NAMESPACE, "|".join(str(p) for p in parts)))


# ---------------------------------------------------------------------------
# Content vocabularies
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegionDef:
    """A sales region. ``remoteness`` in [0, 1] feeds travel friction."""

    code: str
    label: str
    remoteness: float


@dataclass(frozen=True, slots=True)
class SpecialtyDef:
    """A prescriber specialty and the therapeutic areas it treats."""

    code: str
    label: str
    primary_ta: str
    adjacent_tas: tuple[str, ...]
    weight: float


@dataclass(frozen=True, slots=True)
class TopicDef:
    """A program topic. ``ta`` decides topic-fit against a specialty."""

    code: str
    label: str
    ta: str


#: Therapeutic areas. Tenant 1 sells into CARDIO/METABOLIC, tenant 2 into
#: IMMUNOLOGY/RESPIRATORY, so a cross-tenant leak is visible by inspection.
_TA_CARDIO: Final[str] = "CARDIOVASCULAR"
_TA_METABOLIC: Final[str] = "METABOLIC"
_TA_IMMUNOLOGY: Final[str] = "IMMUNOLOGY"
_TA_RESPIRATORY: Final[str] = "RESPIRATORY"
_TA_NEPHROLOGY: Final[str] = "NEPHROLOGY"

REGIONS: Final[tuple[RegionDef, ...]] = (
    RegionDef("NE", "Northeast", 0.20),
    RegionDef("SE", "Southeast", 0.45),
    RegionDef("MW", "Midwest", 0.55),
    RegionDef("SW", "Southwest", 0.70),
    RegionDef("WEST", "West", 0.35),
    RegionDef("MTN", "Mountain", 0.90),
)

SPECIALTIES: Final[tuple[SpecialtyDef, ...]] = (
    SpecialtyDef("CARD", "Cardiology", _TA_CARDIO, (_TA_METABOLIC, _TA_NEPHROLOGY), 0.20),
    SpecialtyDef("ENDO", "Endocrinology", _TA_METABOLIC, (_TA_CARDIO, _TA_NEPHROLOGY), 0.15),
    SpecialtyDef("IM", "Internal Medicine", _TA_CARDIO, (_TA_METABOLIC, _TA_RESPIRATORY), 0.22),
    SpecialtyDef("NEPH", "Nephrology", _TA_NEPHROLOGY, (_TA_CARDIO, _TA_METABOLIC), 0.08),
    SpecialtyDef("RHEU", "Rheumatology", _TA_IMMUNOLOGY, (_TA_RESPIRATORY,), 0.11),
    SpecialtyDef("PULM", "Pulmonology", _TA_RESPIRATORY, (_TA_IMMUNOLOGY,), 0.10),
    SpecialtyDef("DERM", "Dermatology", _TA_IMMUNOLOGY, (), 0.07),
    SpecialtyDef("FM", "Family Medicine", _TA_METABOLIC, (_TA_CARDIO, _TA_RESPIRATORY), 0.07),
)

TOPICS: Final[tuple[TopicDef, ...]] = (
    TopicDef("LIPID_MGMT", "Advanced Lipid Management", _TA_CARDIO),
    TopicDef("HF_GUIDELINE", "Heart Failure Guideline Update", _TA_CARDIO),
    TopicDef("T2D_INIT", "Type 2 Diabetes Initiation", _TA_METABOLIC),
    TopicDef("OBESITY_CARE", "Obesity Care Pathways", _TA_METABOLIC),
    TopicDef("CKD_SCREEN", "CKD Screening and Referral", _TA_NEPHROLOGY),
    TopicDef("RA_SWITCH", "RA Treatment Sequencing", _TA_IMMUNOLOGY),
    TopicDef("PSO_BIOLOGIC", "Psoriasis Biologic Selection", _TA_IMMUNOLOGY),
    TopicDef("SEVERE_ASTHMA", "Severe Asthma Phenotyping", _TA_RESPIRATORY),
    TopicDef("COPD_EXACERB", "COPD Exacerbation Reduction", _TA_RESPIRATORY),
    TopicDef("SAFETY_REFRESH", "Product Safety Refresher", _TA_CARDIO),
)

_PRACTICE_TYPE_LABELS: Final[dict[str, str]] = {
    "COMMUNITY": "Community Practice",
    "HOSPITAL": "Hospital",
    "ACADEMIC": "Academic Medical Center",
    "INTEGRATED_DELIVERY_NETWORK": "Integrated Delivery Network",
    "TELEHEALTH": "Telehealth",
}

_SEGMENT_LABELS: Final[dict[str, str]] = {
    "TIER_1": "Tier 1 - Highest Potential",
    "TIER_2": "Tier 2 - High Potential",
    "TIER_3": "Tier 3 - Moderate Potential",
    "TIER_4": "Tier 4 - Maintain",
}

_COST_CATEGORY_LABELS: Final[dict[str, str]] = {
    "VENUE": "Venue and Facilities",
    "CATERING": "Catering",
    "SPEAKER_FEE": "Speaker Honoraria",
    "AV_PRODUCTION": "AV and Production",
    "TRAVEL": "Travel and Lodging",
    "MATERIALS": "Materials and Printing",
    "VENDOR_MANAGEMENT": "Vendor Management Fee",
    "COMPLIANCE_REVIEW": "Compliance Review",
}

_MARKETING_CHANNEL_LABELS: Final[dict[str, str]] = {
    "REP_CALL": "Field Rep Call",
    "EMAIL": "Non-Personal Email",
    "SAMPLES": "Sample Drop",
    "OTHER_EXPOSURE": "Other Promotional Exposure",
}


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TenantSpec:
    """Everything downstream modules need to know about one tenant."""

    tenant_id: str
    tenant_code: str
    name: str
    currency: str
    n_brands: int
    n_hcps: int
    therapeutic_areas: tuple[str, ...]
    #: Per-source-system identifier template, e.g. ``"NVX-CRM-{:06d}"``. Distinct
    #: per tenant so a cross-tenant identifier is recognisable on sight.
    source_id_templates: dict[str, str]
    is_primary: bool


_TENANT_BLUEPRINT: Final[tuple[dict[str, object], ...]] = (
    {
        "code": "NORTHWIND",
        "name": "Northwind Therapeutics",
        "currency": "USD",
        "tas": (_TA_CARDIO, _TA_METABOLIC, _TA_NEPHROLOGY),
        "templates": {
            "CRM": "NW-CRM-{:06d}",
            "RXVENDOR": "RXNW{:08d}",
            "EVENTVENDOR": "nw.evt.{:05d}",
        },
    },
    {
        "code": "HELIOSBIO",
        "name": "Helios Biosciences",
        "currency": "EUR",
        "tas": (_TA_IMMUNOLOGY, _TA_RESPIRATORY),
        "templates": {
            "CRM": "HB{:07d}",
            "RXVENDOR": "HELIOS-RX-{:06d}",
            "EVENTVENDOR": "EVT/HB/{:05d}",
        },
    },
)


def build_tenant_specs(profile: SyntheticProfile) -> tuple[TenantSpec, ...]:
    """The two tenants, sized from the profile."""
    specs: list[TenantSpec] = []
    for index, blueprint in enumerate(_TENANT_BLUEPRINT):
        code = str(blueprint["code"])
        is_primary = index == 0
        specs.append(
            TenantSpec(
                tenant_id=stable_uuid("tenant", code),
                tenant_code=code,
                name=str(blueprint["name"]),
                currency=str(blueprint["currency"]),
                n_brands=profile.n_brands_primary if is_primary else profile.n_brands_secondary,
                n_hcps=profile.n_hcps_per_tenant,
                therapeutic_areas=tuple(blueprint["tas"]),  # type: ignore[arg-type]
                source_id_templates=dict(blueprint["templates"]),  # type: ignore[arg-type]
                is_primary=is_primary,
            )
        )
    return tuple(specs)


# ---------------------------------------------------------------------------
# Brand and product naming
# ---------------------------------------------------------------------------

_BRAND_NAMES: Final[dict[str, tuple[str, ...]]] = {
    "NORTHWIND": ("Cardivex", "Lipovance", "Glucoreta", "Renastat", "Cardivex XR"),
    "HELIOSBIO": ("Immunexa", "Respiraze", "Dermovia"),
}

_PRODUCT_FORMS: Final[tuple[str, ...]] = ("10 mg Tablet", "20 mg Tablet", "Autoinjector")


def _ascii_code(text: str) -> str:
    """A CSV-safe uppercase code from a display name."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return "".join(ch if ch.isalnum() else "_" for ch in folded).upper().strip("_")


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Taxonomies:
    """The reference layer plus the lookups the DGP needs.

    ``frames`` are the gold outputs. The remaining fields are *derived indexes*
    kept in numpy form so every downstream module can stay vectorised.
    """

    tenants: pd.DataFrame
    brands: pd.DataFrame
    products: pd.DataFrame
    taxonomy: pd.DataFrame
    vendors: pd.DataFrame
    specs: tuple[TenantSpec, ...]
    #: Per-tenant region codes actually in use (all tenants use all regions).
    region_codes: tuple[str, ...]
    #: Per-tenant topic codes, restricted to the tenant's therapeutic areas.
    topic_codes_by_tenant: dict[str, tuple[str, ...]]
    specialty_codes_by_tenant: dict[str, tuple[str, ...]]
    #: topic_fit lookup: (specialty_code, topic_code) -> float in [0, 1].
    topic_fit: dict[tuple[str, str], float]
    #: region_code -> remoteness in [0, 1].
    region_remoteness: dict[str, float]
    #: brand_id -> per-brand DGP draws that never reach gold (they are structural
    #: parameters, not observed data): level and annual trend on the log scale.
    brand_log_level: dict[str, float]
    brand_log_trend: dict[str, float]
    #: product_id -> log-scale level offset.
    product_log_offset: dict[str, float]


def _taxonomy_rows(
    spec: TenantSpec,
    topic_codes: tuple[str, ...],
    specialty_codes: tuple[str, ...],
) -> list[dict[str, object]]:
    """One tenant's controlled vocabulary, as plain dicts.

    ``TaxonomyKind`` is imported from ``speaker_roi_core.enums`` so the kind
    strings can never drift from the platform's own vocabulary (plan.md §9.2:
    the taxonomy table is the single source of reference data).
    """
    rows: list[dict[str, object]] = []

    def add(kind: TaxonomyKind, code: str, label: str, order: int, numeric: float | None) -> None:
        rows.append(
            {
                "tenant_id": spec.tenant_id,
                "taxonomy_id": stable_uuid("taxonomy", spec.tenant_code, kind.value, code),
                "kind": kind.value,
                "code": code,
                "label": label,
                "sort_order": order,
                "numeric_attribute": numeric,
                "is_active": True,
            }
        )

    for i, region in enumerate(REGIONS):
        add(TaxonomyKind.REGION, region.code, region.label, i, region.remoteness)
    for i, ta in enumerate(spec.therapeutic_areas):
        add(TaxonomyKind.THERAPEUTIC_AREA, ta, ta.title().replace("_", " "), i, None)
    for i, code in enumerate(topic_codes):
        topic = next(t for t in TOPICS if t.code == code)
        add(TaxonomyKind.TOPIC, topic.code, topic.label, i, None)
    for i, code in enumerate(specialty_codes):
        specialty = next(s for s in SPECIALTIES if s.code == code)
        add(TaxonomyKind.SPECIALTY, specialty.code, specialty.label, i, specialty.weight)
    for i, (code, label) in enumerate(_PRACTICE_TYPE_LABELS.items()):
        add(TaxonomyKind.PRACTICE_TYPE, code, label, i, None)
    for i, (code, label) in enumerate(_SEGMENT_LABELS.items()):
        add(TaxonomyKind.HCP_SEGMENT, code, label, i, None)
    for i, (code, label) in enumerate(_COST_CATEGORY_LABELS.items()):
        add(TaxonomyKind.COST_CATEGORY, code, label, i, None)
    for i, (code, label) in enumerate(_MARKETING_CHANNEL_LABELS.items()):
        add(TaxonomyKind.MARKETING_CHANNEL, code, label, i, None)
    return rows


def build_taxonomies(profile: SyntheticProfile, generator: np.random.Generator) -> Taxonomies:
    """Build the whole reference layer for both tenants."""
    specs = build_tenant_specs(profile)
    outcome = profile.outcome
    selection = profile.selection

    tenant_rows: list[dict[str, object]] = []
    brand_rows: list[dict[str, object]] = []
    product_rows: list[dict[str, object]] = []
    taxonomy_rows: list[dict[str, object]] = []
    vendor_rows: list[dict[str, object]] = []

    topic_by_tenant: dict[str, tuple[str, ...]] = {}
    specialty_by_tenant: dict[str, tuple[str, ...]] = {}
    brand_log_level: dict[str, float] = {}
    brand_log_trend: dict[str, float] = {}
    product_log_offset: dict[str, float] = {}

    for spec in specs:
        tas = set(spec.therapeutic_areas)
        topics = tuple(t.code for t in TOPICS if t.ta in tas)
        specialties = tuple(
            s.code for s in SPECIALTIES if s.primary_ta in tas or set(s.adjacent_tas) & tas
        )
        topic_by_tenant[spec.tenant_id] = topics
        specialty_by_tenant[spec.tenant_id] = specialties

        tenant_rows.append(
            {
                "tenant_id": spec.tenant_id,
                "tenant_code": spec.tenant_code,
                "name": spec.name,
                "currency_code": spec.currency,
                "status": "ACTIVE",
                "is_primary": spec.is_primary,
            }
        )
        taxonomy_rows.extend(_taxonomy_rows(spec, topics, specialties))

        names = _BRAND_NAMES[spec.tenant_code][: spec.n_brands]
        for b_index, brand_name in enumerate(names):
            brand_code = _ascii_code(brand_name)
            brand_id = stable_uuid("brand", spec.tenant_code, brand_code)
            brand_ta = spec.therapeutic_areas[b_index % len(spec.therapeutic_areas)]
            brand_rows.append(
                {
                    "tenant_id": spec.tenant_id,
                    "brand_id": brand_id,
                    "brand_code": brand_code,
                    "brand_name": brand_name,
                    "therapeutic_area": brand_ta,
                    "is_active": True,
                }
            )
            brand_log_level[brand_id] = float(generator.normal(0.0, outcome.brand_level_sd))
            brand_log_trend[brand_id] = float(
                generator.normal(outcome.brand_trend_mean, outcome.brand_trend_sd)
            )
            # The flagship brand of each tenant carries three SKUs, the rest two.
            # plan.md §9 models Rx at product grain, and the row minimums in
            # PLAN_REVIEW F-2 are unreachable at one product per brand.
            n_products = 3 if b_index == 0 else 2
            for p_index in range(n_products):
                form = _PRODUCT_FORMS[p_index]
                product_code = f"{brand_code}_{p_index + 1}"
                product_id = stable_uuid("product", spec.tenant_code, product_code)
                is_flagship = p_index == 0
                product_rows.append(
                    {
                        "tenant_id": spec.tenant_id,
                        "product_id": product_id,
                        "brand_id": brand_id,
                        "product_code": product_code,
                        "product_name": f"{brand_name} {form}",
                        "dosage_form": form,
                        "is_flagship": is_flagship,
                        "is_active": True,
                    }
                )
                offset = float(generator.normal(0.0, outcome.product_level_sd))
                if not is_flagship:
                    offset += outcome.non_flagship_product_offset
                product_log_offset[product_id] = offset

        for v_index, system in enumerate(("CRM", "RXVENDOR", "EVENTVENDOR")):
            vendor_rows.append(
                {
                    "tenant_id": spec.tenant_id,
                    "vendor_id": stable_uuid("vendor", spec.tenant_code, system),
                    "vendor_code": f"{spec.tenant_code}_{system}",
                    "vendor_name": f"{spec.name} {system.title()} Feed",
                    "source_system": system,
                    "status": VendorStatus.ACTIVE.value,
                    "sort_order": v_index,
                }
            )

    # topic_fit is a pure function of the two vocabularies, so it is materialised
    # once as a dict rather than recomputed per invitation row.
    fit: dict[tuple[str, str], float] = {}
    for specialty in SPECIALTIES:
        for topic in TOPICS:
            if topic.ta == specialty.primary_ta:
                fit[(specialty.code, topic.code)] = selection.topic_fit_match
            elif topic.ta in specialty.adjacent_tas:
                fit[(specialty.code, topic.code)] = selection.topic_fit_adjacent
            else:
                fit[(specialty.code, topic.code)] = selection.topic_fit_mismatch

    return Taxonomies(
        tenants=pd.DataFrame(tenant_rows),
        brands=pd.DataFrame(brand_rows),
        products=pd.DataFrame(product_rows),
        taxonomy=pd.DataFrame(taxonomy_rows),
        vendors=pd.DataFrame(vendor_rows),
        specs=specs,
        region_codes=tuple(r.code for r in REGIONS),
        topic_codes_by_tenant=topic_by_tenant,
        specialty_codes_by_tenant=specialty_by_tenant,
        topic_fit=fit,
        region_remoteness={r.code: r.remoteness for r in REGIONS},
        brand_log_level=brand_log_level,
        brand_log_trend=brand_log_trend,
        product_log_offset=product_log_offset,
    )
