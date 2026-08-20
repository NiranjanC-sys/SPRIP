"""Field specifications shared by more than one dataset contract.

Identity, brand and period columns appear in most of the twelve datasets in
plan.md §10.1, and they have to *agree* — the same normalised header must
resolve to the same concept in an Rx extract and in a marketing extract, or the
conformance step joins on subtly different keys and nobody notices until a lift
number looks wrong.  Defining them once, here, makes that agreement structural
rather than a convention people remember.

Each builder takes the small amount of per-dataset variation (required/optional,
wording of the description) and leaves everything else — dtype, aliases,
examples — fixed.  The alias lists are deliberately generous: real supplier
files arrive as ``HCP ID``, ``hcp_id``, ``PRESCRIBER_ID``, ``Physician Code``
and a dozen other spellings, and every alias we anticipate is one manual
column-mapping step the uploader does not have to perform (plan.md §10.3).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from speaker_roi_analytics.ingestion.contracts import DType, FieldSpec
from speaker_roi_core.enums import TaxonomyKind

__all__ = [
    "MONEY_PRECISION",
    "MONEY_SCALE",
    "brand_code_field",
    "currency_field",
    "index_field",
    "month_field",
    "note_field",
    "region_code_field",
    "source_hcp_id_field",
    "source_system_field",
    "topic_code_field",
]

#: decimal(18, 2) everywhere money is stored. Wide enough for any realistic
#: programme budget in a minor unit, exact so that summing a thousand cost lines
#: reproduces the invoice total to the paisa (PLAN_REVIEW F-14 forbids implicit
#: conversion, so exactness within one currency is the whole guarantee).
MONEY_PRECISION = 18
MONEY_SCALE = 2


def source_system_field(*, required: bool = True) -> FieldSpec:
    """The system of record a supplier identifier came from.

    Identity resolution is scoped per source system (plan.md §9.4): the same
    string ``12345`` is a different prescriber in a CRM export than in an Rx
    panel file.  Carrying the system alongside the id is what makes the
    crosswalk a function rather than a coincidence.
    """
    return FieldSpec(
        name="source_system",
        title="Source System",
        dtype=DType.STRING,
        description=(
            "Code of the system the identifier below came from, e.g. CRM, RXPANEL, "
            "EVENTTOOL. Identifiers are only unique within a source system."
        ),
        required=required,
        nullable=not required,
        max_length=40,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-.]{0,39}$",
        example="CRM",
        aliases=(
            "source",
            "src_system",
            "system",
            "system_code",
            "source_sys",
            "data_source",
            "sourceSystem",
            "SOURCE_SYSTEM",
            "Source System",
            "origin_system",
            "vendor_system",
            "feed",
            "feed_name",
        ),
    )


def source_hcp_id_field(*, required: bool = True, description: str = "") -> FieldSpec:
    """The supplier's own identifier for a healthcare professional.

    Flagged :attr:`FieldSpec.pii`.  It is a pseudonymous identifier rather than
    a name, but it is still personal data under plan.md §15, so it is validated
    normally and never echoed into an error message, a preview or a log line.
    """
    return FieldSpec(
        name="source_hcp_id",
        title="Source HCP ID",
        dtype=DType.STRING,
        description=description
        or (
            "The identifier this source system uses for the healthcare professional. "
            "Never a name — the platform resolves identity through the crosswalk."
        ),
        required=required,
        nullable=not required,
        max_length=80,
        example="CRM-0009182",
        pii=True,
        aliases=(
            "hcp_id",
            "hcp_code",
            "hcp",
            "hcp_identifier",
            "physician_id",
            "physician_code",
            "doctor_id",
            "doctor_code",
            "dr_id",
            "prescriber_id",
            "prescriber_code",
            "customer_id",
            "customer_code",
            "external_hcp_id",
            "src_hcp_id",
            "source_id",
            "sourceHcpId",
            "SOURCE_HCP_ID",
            "HCP ID",
            "HCP Code",
            "Prescriber ID",
        ),
    )


def brand_code_field(*, required: bool = True, description: str = "") -> FieldSpec:
    """Brand the row belongs to, as declared in ``BRAND_PRODUCT_MASTER``."""
    return FieldSpec(
        name="brand_code",
        title="Brand Code",
        dtype=DType.STRING,
        description=description
        or "Brand code exactly as published in the brand/product master for this tenant.",
        required=required,
        nullable=not required,
        max_length=40,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-.]{0,39}$",
        example="BRD-ALPHA",
        aliases=(
            "brand",
            "brand_id",
            "brand_key",
            "brand_cd",
            "product_brand",
            "brandCode",
            "BRAND_CODE",
            "Brand",
            "Brand Code",
            "marketed_brand",
        ),
    )


def month_field(
    *,
    name: str = "month",
    title: str = "Month",
    description: str = "",
    required: bool = True,
    example: str = "2026-03",
) -> FieldSpec:
    """A calendar month, normalised to the first day of that month.

    Accepts ``YYYY-MM``, ``YYYY-MM-DD``, ``MM/YYYY`` and ``Mon-YY`` because all
    four fall out of ordinary Excel and BI exports (plan.md §10.3).  Whatever
    arrives is stored as the first of the month, so a file that dates March as
    ``2026-03-31`` and one that dates it ``2026-03-01`` produce the same key
    instead of two half-populated months.
    """
    return FieldSpec(
        name=name,
        title=title,
        dtype=DType.MONTH,
        description=description
        or (
            "Calendar month of the observation. Accepted forms: 2026-03, 2026-03-01, "
            "03/2026, Mar-26. Stored as the first day of the month."
        ),
        required=required,
        nullable=not required,
        example=example,
        aliases=(
            "period",
            "month_id",
            "year_month",
            "yearmonth",
            "yyyymm",
            "period_month",
            "month_start",
            "cal_month",
            "calendar_month",
            "rx_month",
            "activity_month",
            "MONTH",
            "Month",
            "Period",
        ),
    )


def currency_field(*, required: bool = True, description: str = "") -> FieldSpec:
    """ISO-4217 alphabetic currency code.

    PLAN_REVIEW F-14: the platform performs no implicit currency conversion, so
    the code is not decoration — it is what stops two incompatible amounts being
    added together (see
    :func:`~speaker_roi_analytics.ingestion.validators.single_currency_per_group`).
    """
    return FieldSpec(
        name="currency",
        title="Currency",
        dtype=DType.CURRENCY_CODE,
        description=description
        or (
            "ISO-4217 three-letter currency code of the amount on this row. "
            "Amounts are never converted; totals are reported per currency."
        ),
        required=required,
        nullable=not required,
        max_length=3,
        example="INR",
        aliases=(
            "currency_code",
            "ccy",
            "curr",
            "iso_currency",
            "currencyCode",
            "CURRENCY",
            "Currency",
            "Currency Code",
        ),
    )


def region_code_field(*, required: bool = True, description: str = "") -> FieldSpec:
    """Region as defined by the tenant's own geography taxonomy."""
    return FieldSpec(
        name="region_code",
        title="Region Code",
        dtype=DType.STRING,
        description=description
        or "Region code from this tenant's region taxonomy. Unknown values are flagged, not invented.",
        required=required,
        nullable=not required,
        taxonomy_ref=TaxonomyKind.REGION,
        max_length=40,
        example="IN-WEST",
        aliases=(
            "region",
            "territory",
            "territory_code",
            "geo",
            "geography",
            "zone",
            "zone_code",
            "area",
            "area_code",
            "regionCode",
            "REGION_CODE",
            "Region",
        ),
    )


def topic_code_field(*, required: bool = True, description: str = "") -> FieldSpec:
    """Clinical/therapeutic topic from the tenant's topic taxonomy."""
    return FieldSpec(
        name="topic_code",
        title="Topic Code",
        dtype=DType.STRING,
        description=description or "Programme topic code from this tenant's topic taxonomy.",
        required=required,
        nullable=not required,
        taxonomy_ref=TaxonomyKind.TOPIC,
        max_length=40,
        example="TOP-CARDIO-01",
        aliases=(
            "topic",
            "subject",
            "theme",
            "programme_topic",
            "program_topic",
            "session_topic",
            "topicCode",
            "TOPIC_CODE",
            "Topic",
        ),
    )


def index_field(
    name: str,
    title: str,
    description: str,
    *,
    example: str = "1.00",
    aliases: tuple[str, ...] = (),
) -> FieldSpec:
    """A market index normalised around 1.0.

    Bounded at ``[0, 10]``: an index outside that range is not a strong signal,
    it is a units mistake (someone supplied a percentage or a raw count), and
    letting it through would swamp every covariate it competes with.
    """
    return FieldSpec(
        name=name,
        title=title,
        dtype=DType.DECIMAL,
        description=description,
        required=False,
        nullable=True,
        precision=9,
        scale=4,
        minimum=Decimal("0"),
        maximum=Decimal("10"),
        example=example,
        aliases=aliases,
    )


def note_field(
    *,
    name: str = "note",
    title: str = "Note",
    description: str = "",
    max_length: int = 500,
) -> FieldSpec:
    """Optional free text.

    Free text is never rendered back into an error message and never logged
    (plan.md §10.2): the uploader controls its contents and it is the most
    likely place for a stray patient detail to arrive despite the column-level
    refusals.
    """
    return FieldSpec(
        name=name,
        title=title,
        dtype=DType.STRING,
        description=description or "Optional free-text note. Not used in any calculation.",
        required=False,
        nullable=True,
        max_length=max_length,
        example="",
        pii=True,
        aliases=("notes", "comment", "comments", "remark", "remarks", "description"),
    )


#: A conservative floor for any date the platform accepts. Anything earlier is a
#: two-digit-year misparse or an Excel serial-number accident, not history.
EARLIEST_PLAUSIBLE_DATE = dt.date(2015, 1, 1)
