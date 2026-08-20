"""``HCP_MASTER`` — the healthcare-professional reference list (plan.md §10.1).

This contract carries the *attributes* the platform is allowed to know about a
prescriber: specialty, region, practice type and segment.  Those are the
covariates that make a matched control group credible (plan.md §11) — comparing
a cardiologist in a metro to a general practitioner in a small town produces a
lift number that measures geography, not the programme.

What this contract will **not** accept is at least as important as what it will.
:data:`~speaker_roi_analytics.ingestion.contracts.HCP_CONTACT_FORBIDDEN_HEADERS`
is attached here on top of the platform-wide patient-data refusals, so a CRM
export carrying phone numbers, email addresses, postal addresses or dates of
birth is rejected **before any row is read** rather than being loaded and
quietly trimmed.  Plan.md §15 states the requirement; refusing at the header is
what makes it true of the bytes on disk and not just of the database columns.

The identifier itself (``source_hcp_id``) is pseudonymous but still personal
data, so it is marked :attr:`FieldSpec.pii` and never appears in an error
message, a preview or a log line.
"""

from __future__ import annotations

from speaker_roi_analytics.ingestion.contracts import (
    HCP_CONTACT_FORBIDDEN_HEADERS,
    Cadence,
    DatasetContract,
    DType,
    FieldSpec,
)
from speaker_roi_analytics.ingestion.definitions._common import (
    EARLIEST_PLAUSIBLE_DATE,
    region_code_field,
    source_hcp_id_field,
    source_system_field,
)
from speaker_roi_analytics.ingestion.validators import no_future_period
from speaker_roi_core.enums import DatasetType, TaxonomyKind

__all__ = ["CONTRACT"]


CONTRACT = DatasetContract(
    dataset_type=DatasetType.HCP_MASTER,
    version="1.0.0",
    title="HCP Master",
    description=(
        "Professional attributes of the healthcare professionals referenced by the other "
        "datasets: specialty, region, practice type and segment. No contact details, ever."
    ),
    owner="Data Management / Master Data",
    cadence=Cadence.ONE_TIME,
    natural_key=("source_system", "source_hcp_id"),
    duplicate_policy="REJECT",
    forbidden_headers=HCP_CONTACT_FORBIDDEN_HEADERS,
    fields=(
        source_system_field(),
        source_hcp_id_field(
            description=(
                "The identifier this source system uses for the professional. Pseudonymous by "
                "design: the platform never receives or stores a prescriber's name."
            )
        ),
        FieldSpec(
            name="master_hcp_id",
            title="Master HCP ID",
            dtype=DType.STRING,
            description=(
                "Optional. Supply only if your organisation already operates a master identifier. "
                "Leaving it blank is normal — the platform resolves identity through HCP_CROSSWALK."
            ),
            required=False,
            nullable=True,
            max_length=80,
            example="",
            pii=True,
            aliases=("mdm_id", "golden_id", "master_id", "universal_hcp_id", "enterprise_hcp_id"),
        ),
        FieldSpec(
            name="specialty_code",
            title="Specialty Code",
            dtype=DType.STRING,
            description=(
                "Primary specialty from this tenant's specialty taxonomy. One of the strongest "
                "covariates for matching a control group, so an unmapped value is flagged rather "
                "than folded into an 'OTHER' bucket."
            ),
            taxonomy_ref=TaxonomyKind.SPECIALTY,
            max_length=40,
            example="SPEC-CARDIO",
            aliases=(
                "specialty",
                "speciality",
                "speciality_code",
                "primary_specialty",
                "spec",
                "SPECIALTY",
                "Specialty",
            ),
        ),
        region_code_field(
            description="Region the professional practises in, from the tenant region taxonomy."
        ),
        FieldSpec(
            name="city_code",
            title="City Code",
            dtype=DType.STRING,
            description=(
                "Coded city or micro-market. A code, not a postal address: it locates the "
                "professional's market, not their premises."
            ),
            required=False,
            nullable=True,
            max_length=40,
            example="CITY-MUM",
            aliases=("city", "city_key", "town_code", "micro_market", "brick", "brick_code"),
        ),
        FieldSpec(
            name="practice_type",
            title="Practice Type",
            dtype=DType.STRING,
            description=(
                "Practice setting from the tenant taxonomy, e.g. hospital, clinic, corporate. "
                "Setting drives prescribing volume independently of any programme."
            ),
            required=False,
            nullable=True,
            taxonomy_ref=TaxonomyKind.PRACTICE_TYPE,
            max_length=40,
            example="PRAC-HOSPITAL",
            aliases=(
                "practice",
                "practice_setting",
                "setting",
                "institution_type",
                "practice_type_code",
                "channel_type",
            ),
        ),
        FieldSpec(
            name="segment",
            title="Segment",
            dtype=DType.STRING,
            description=(
                "The tenant's own commercial segment for the professional. Used as a matching "
                "covariate only; the platform never publishes a prescriber-level ranking."
            ),
            required=False,
            nullable=True,
            taxonomy_ref=TaxonomyKind.HCP_SEGMENT,
            max_length=40,
            example="SEG-A",
            aliases=("hcp_segment", "segment_code", "customer_segment", "tier", "class", "grade"),
        ),
        FieldSpec(
            name="is_active",
            title="Is Active",
            dtype=DType.BOOLEAN,
            description=(
                "Whether the professional is currently in scope for engagement. Inactive rows are "
                "retained so historical measurement stays reproducible."
            ),
            required=False,
            nullable=True,
            example="true",
            aliases=("active", "active_flag", "is_current", "in_scope", "status_active"),
        ),
        FieldSpec(
            name="first_seen_on",
            title="First Seen On",
            dtype=DType.DATE,
            description=(
                "Date the professional first entered your systems. Used to avoid treating a "
                "newly-onboarded professional's empty history as a genuine zero baseline."
            ),
            required=False,
            nullable=True,
            minimum=EARLIEST_PLAUSIBLE_DATE,
            example="2024-02-01",
            aliases=("first_seen", "onboarded_on", "created_date", "added_on", "start_date"),
        ),
    ),
    row_rules=(
        no_future_period(
            "first_seen_on",
            description="first_seen_on should not be dated in the future.",
        ),
    ),
    sample_rows=(
        {
            "source_system": "CRM",
            "source_hcp_id": "CRM-0009182",
            "master_hcp_id": "",
            "specialty_code": "SPEC-CARDIO",
            "region_code": "IN-WEST",
            "city_code": "CITY-MUM",
            "practice_type": "PRAC-HOSPITAL",
            "segment": "SEG-A",
            "is_active": "true",
            "first_seen_on": "2024-02-01",
        },
        {
            "source_system": "CRM",
            "source_hcp_id": "CRM-0011044",
            "master_hcp_id": "",
            "specialty_code": "SPEC-ENDO",
            "region_code": "IN-SOUTH",
            "city_code": "CITY-BLR",
            "practice_type": "PRAC-CLINIC",
            "segment": "SEG-B",
            "is_active": "true",
            "first_seen_on": "2023-11-14",
        },
        {
            "source_system": "EVENTTOOL",
            "source_hcp_id": "ET-55210",
            "master_hcp_id": "",
            "specialty_code": "SPEC-GP",
            "region_code": "IN-NORTH",
            "city_code": "CITY-DEL",
            "practice_type": "PRAC-CLINIC",
            "segment": "SEG-C",
            "is_active": "false",
            "first_seen_on": "2022-08-30",
        },
    ),
    notes=(
        "This file must not contain names, phone numbers, email addresses, postal addresses, "
        "postal codes or dates of birth. A file carrying any of those columns is rejected "
        "outright before any row is read (plan.md §15).",
        "Identifiers are only unique within a source system. Two systems may use the same "
        "string for different professionals, which is what HCP_CROSSWALK exists to resolve.",
    ),
)
