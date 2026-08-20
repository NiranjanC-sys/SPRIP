"""The declarative intake contract model and the versioned contract registry.

Why a declarative model
-----------------------
plan.md §7.0.1 is explicit that "Bulk upload always uses the central ingestion
contracts; pages must not implement independent parsing logic", and §10.3
requires downloadable templates and data dictionaries "for every supported
dataset". Those artifacts and the validator must agree exactly, forever. The only
way to guarantee that is to make the contract *data*: a :class:`DatasetContract`
is the single object from which the template CSV, the formatted XLSX, the JSON
Schema, the data dictionary, the column-mapping wizard and the row validator are
all derived. Nothing about a dataset is written down twice.

Two consequences that look like over-engineering and are not:

* ``FieldSpec.enum_ref`` holds the *actual* enum class from
  ``speaker_roi_core.enums``. The list of permitted values in the template's
  dropdown, in the JSON Schema, in the data dictionary and in the validator is
  therefore literally the same object the database enum is generated from. A
  vocabulary cannot drift between the file the vendor fills in and the column it
  lands in.
* ``FieldSpec.taxonomy_ref`` holds a :class:`TaxonomyKind` rather than a list,
  because region/topic/specialty are *tenant-scoped* controlled lists. The
  contract declares which list applies; the value is resolved at validation time
  through an injected resolver, so this module never touches a database.

Versioning
----------
Each contract carries a semantic ``version``. Field additions that are optional
are a minor bump; anything that can reject a file that previously passed is a
major bump. ``data_contracts/{DATASET_TYPE}/v{version}/`` is generated per
version and committed, so a vendor who filled in last quarter's template can be
told precisely which version they used.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import Any, Final, Literal

from speaker_roi_analytics.ingestion.issues import IssueCode
from speaker_roi_core.enums import DatasetType, IssueSeverity, StrEnumBase, TaxonomyKind

__all__ = [
    "GLOBAL_FORBIDDEN_HEADERS",
    "Cadence",
    "DType",
    "DatasetContract",
    "DuplicatePolicy",
    "FieldSpec",
    "ForbiddenHeaderPattern",
    "FrameRule",
    "FrameViolation",
    "ReferenceSpec",
    "ReferenceTarget",
    "RowRule",
    "RowView",
    "RuleContext",
    "RuleOptions",
    "RuleViolation",
    "ScopeKind",
    "all_contracts",
    "contract_registry",
    "get_contract",
    "normalise_header",
]


# ===========================================================================
# Small vocabularies that belong to the intake layer only
# ===========================================================================


class DType(StrEnum):
    """Logical field types.

    Deliberately smaller than the set of Python types: ``month`` exists as its own
    type because plan.md §9.3 stores Rx at month grain and §10.2 requires "Missing
    period versus genuine zero outcome" to be decidable - which is impossible if a
    month is quietly widened into a timestamp. ``currency_code`` is separate from
    ``string`` because §10.2 gates on "valid currency".
    """

    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    MONTH = "month"
    ENUM = "enum"
    CURRENCY_CODE = "currency_code"


class ScopeKind(StrEnum):
    """Scope an upload session must name before bytes are accepted.

    plan.md §10.2 step 1-2: "Request an upload session with dataset type and
    scoped campaign/event" then "Authorize vendor assignment". The contract
    declares which of these the session must carry so the API can refuse to open
    a session that could not be authorised.
    """

    BRAND = "BRAND"
    CAMPAIGN = "CAMPAIGN"
    EVENT = "EVENT"
    VENDOR = "VENDOR"


class Cadence(StrEnum):
    """Expected delivery rhythm, feeding ``source_expectations`` (plan.md §9.4)."""

    ONE_TIME = "ONE_TIME"
    AD_HOC = "AD_HOC"
    PER_EVENT = "PER_EVENT"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


#: How rows sharing a natural key are handled.
#:
#: ``RECONCILE`` exists for attendance only (plan.md §19.1 "Duplicate attendance
#: reconciliation"): two vendors can both legitimately report the same person at
#: the same event, and the right answer is to prefer the stronger evidence rather
#: than to reject both or to keep whichever arrived last.
DuplicatePolicy = Literal["REJECT", "LAST_WINS", "FIRST_WINS", "RECONCILE"]


class ReferenceTarget(StrEnum):
    """Tenant-scoped objects an intake row may point at.

    These are *declared* here and *resolved* elsewhere: this package never opens a
    database (plan.md §17). ``validate.py`` takes a ``reference_resolver`` callable
    and the API supplies one backed by the repository layer.
    """

    BRAND = "BRAND"
    PRODUCT = "PRODUCT"
    CAMPAIGN = "CAMPAIGN"
    EVENT = "EVENT"
    VENDOR = "VENDOR"
    HCP_IDENTIFIER = "HCP_IDENTIFIER"
    SOURCE_SYSTEM = "SOURCE_SYSTEM"


#: Which issue code an unresolved reference raises. Keeping this a table rather
#: than a formatted string means the UI can group "unknown event" separately from
#: "unresolved HCP", which are very different remediation stories.
REFERENCE_ISSUE_CODES: Final[Mapping[ReferenceTarget, IssueCode]] = {
    ReferenceTarget.BRAND: IssueCode.REF_UNKNOWN_BRAND_CODE,
    ReferenceTarget.PRODUCT: IssueCode.REF_UNKNOWN_PRODUCT_CODE,
    ReferenceTarget.CAMPAIGN: IssueCode.REF_UNKNOWN_CAMPAIGN_CODE,
    ReferenceTarget.EVENT: IssueCode.REF_UNKNOWN_EVENT_CODE,
    ReferenceTarget.VENDOR: IssueCode.REF_UNKNOWN_VENDOR_CODE,
    ReferenceTarget.HCP_IDENTIFIER: IssueCode.REF_UNKNOWN_HCP_IDENTIFIER,
    ReferenceTarget.SOURCE_SYSTEM: IssueCode.REF_UNKNOWN_SOURCE_SYSTEM,
}


# ===========================================================================
# Header normalisation
# ===========================================================================

_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def normalise_header(raw: object) -> str:
    """Fold a supplier header down to a comparison key.

    ``"HCP ID"``, ``"hcp_id"``, ``"HCP-Id"``, ``"  HCP   ID  "`` and ``"HCP.ID"``
    all normalise to ``hcp_id``. This is what lets ``FieldSpec.aliases`` stay a
    short list of genuinely different *words* rather than a combinatorial list of
    spellings.
    """
    text = "" if raw is None else str(raw)
    return _NON_ALNUM.sub("_", text.strip().lower()).strip("_")


# ===========================================================================
# Forbidden headers - the compliance gate that runs before any row is parsed
# ===========================================================================


@dataclass(frozen=True, slots=True)
class ForbiddenHeaderPattern:
    """A column that must never appear, matched against the normalised header.

    plan.md §15 forbids ingesting patient identifiers outright, and §7.4 forbids
    accepting "named target HCPs as prediction inputs". Both are file-level
    refusals, not row-level ones: the moment such a column exists the file is a
    liability, so it is rejected before a single data row is read. The reason
    string is surfaced verbatim to the uploader.
    """

    pattern: str
    code: IssueCode
    reason: str

    @property
    def regex(self) -> re.Pattern[str]:
        return _compiled_pattern(self.pattern)

    def matches(self, normalised_header: str) -> bool:
        return bool(self.regex.fullmatch(normalised_header))


@lru_cache(maxsize=512)
def _compiled_pattern(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def _pii(pattern: str, reason: str) -> ForbiddenHeaderPattern:
    return ForbiddenHeaderPattern(pattern, IssueCode.POLICY_FORBIDDEN_PII_COLUMN, reason)


#: Applied to **every** contract. plan.md §15: "Do not ingest patient names,
#: phone numbers, addresses, prescription images or ABHA identifiers for this use
#: case." A speaker-programme ROI platform has no lawful need for any of these,
#: so the safest possible posture is to refuse the file rather than to drop the
#: column silently and leave the bytes sitting in the raw object store.
GLOBAL_FORBIDDEN_HEADERS: Final[tuple[ForbiddenHeaderPattern, ...]] = (
    _pii(r".*patient.*", "Patient-level data is out of scope for programme measurement."),
    _pii(r".*abha.*", "ABHA health-account identifiers must never be ingested."),
    _pii(r".*aadhaar.*|.*aadhar.*|.*uidai.*", "National identity numbers must never be ingested."),
    _pii(r"mrn|.*medical_record.*", "Medical record numbers identify patients."),
    _pii(
        r".*prescription_image.*|.*rx_image.*|.*script_image.*",
        "Prescription images are patient records.",
    ),
    _pii(r".*diagnosis.*|icd|icd_?\d*_?code", "Diagnosis data is patient clinical data."),
    _pii(r".*ssn.*|.*social_security.*", "Government identity numbers must never be ingested."),
)

#: Extra refusals for the HCP master, which is where a CRM export would most
#: plausibly carry contact details. None of these are needed to measure a
#: programme, so accepting them would fail data minimisation for no benefit.
HCP_CONTACT_FORBIDDEN_HEADERS: Final[tuple[ForbiddenHeaderPattern, ...]] = (
    _pii(
        r"(hcp_)?(mobile|phone|telephone|contact_number|whatsapp).*",
        "Contact telephone numbers are not required to measure programmes.",
    ),
    _pii(
        r"(hcp_)?(email|email_address|e_mail).*",
        "Contact email addresses are not required to measure programmes.",
    ),
    _pii(
        r"(hcp_)?(address|street|address_line_?\d*|city_address|postal_address).*",
        "Postal addresses are not required to measure programmes.",
    ),
    _pii(
        r"(hcp_)?(pincode|pin_code|postcode|postal_code|zip|zip_code)",
        "Postal codes narrow to an individual and are not required.",
    ),
    _pii(
        r"(hcp_)?(dob|date_of_birth|birth_date|birthdate)",
        "Dates of birth are not required to measure programmes.",
    ),
    _pii(
        r"(hcp_)?(passport|pan|pan_number|national_id).*",
        "Government identity numbers must never be ingested.",
    ),
)


def _targeting(pattern: str, reason: str) -> ForbiddenHeaderPattern:
    return ForbiddenHeaderPattern(pattern, IssueCode.POLICY_NAMED_HCP_TARGETING, reason)


#: plan.md §7.4: "Do not accept named target HCPs as prediction inputs", and §15:
#: "Prohibit named-HCP prescribing rankings for speaker/attendee selection". A
#: candidate-programme file that carries a prescriber list is an attempt - however
#: innocent - to get the platform to rank named clinicians, so it is refused with
#: a message that says so.
NAMED_TARGETING_FORBIDDEN_HEADERS: Final[tuple[ForbiddenHeaderPattern, ...]] = (
    _targeting(
        r"target_hcp.*|.*_target_hcp.*",
        "Programme forecasts are produced for designs, never for named prescribers.",
    ),
    _targeting(
        r"target_prescriber.*|prescriber.*|.*_prescriber(_.*)?",
        "Named prescribers are not accepted as forecast inputs.",
    ),
    _targeting(
        r"(source_)?hcp_id|hcp_ids|hcp_code|master_hcp_id|npi|npi_number",
        "Individual HCP identifiers are not accepted as forecast inputs.",
    ),
    _targeting(
        r"hcp_list|hcp_names?|attendee_names?|invitee_names?|named_hcps?",
        "Named attendee lists are not accepted as forecast inputs.",
    ),
    _targeting(
        r"top_prescribers?|.*decile.*|.*prescriber_rank.*",
        "Prescriber rankings must not drive programme selection.",
    ),
)


# ===========================================================================
# Field specification
# ===========================================================================


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One column of an intake contract."""

    name: str
    title: str
    dtype: DType
    description: str
    required: bool = True
    #: Whether a *present* column may carry a blank cell. ``required`` is about
    #: the column existing; ``nullable`` is about the cell being empty. A field
    #: can be required-and-nullable (the column must be there, blanks allowed) -
    #: that combination is how "the supplier must tell us it had nothing" is
    #: expressed, as opposed to "the supplier may omit the concept entirely".
    nullable: bool = False
    enum_ref: type[StrEnumBase] | None = None
    taxonomy_ref: TaxonomyKind | None = None
    minimum: Decimal | int | date | None = None
    maximum: Decimal | int | date | None = None
    min_exclusive: bool = False
    max_exclusive: bool = False
    max_length: int | None = None
    pattern: str | None = None
    unit: str | None = None
    example: str = ""
    aliases: tuple[str, ...] = ()
    #: The value is personal data. It is validated normally but never echoed into
    #: an issue message, a preview or a log (plan.md §10.2, §15). It is *not* the
    #: same thing as a forbidden column - see :class:`ForbiddenHeaderPattern`.
    pii: bool = False
    precision: int | None = None
    scale: int | None = None
    #: Free-text methodological note rendered under the field in the dictionary.
    note: str = ""

    def __post_init__(self) -> None:
        if self.dtype is DType.ENUM and self.enum_ref is None:
            raise ValueError(f"{self.name}: enum fields must declare enum_ref")
        if self.enum_ref is not None and self.dtype is not DType.ENUM:
            raise ValueError(f"{self.name}: enum_ref is only meaningful for DType.ENUM")
        if self.dtype is DType.DECIMAL and (self.precision is None or self.scale is None):
            raise ValueError(f"{self.name}: decimal fields must declare precision and scale")
        if self.scale is not None and self.precision is not None and self.scale > self.precision:
            raise ValueError(f"{self.name}: scale cannot exceed precision")
        if not self.required and not self.nullable:
            # An optional column whose cells may not be blank is unfillable in a
            # template, because the template ships the column.
            raise ValueError(f"{self.name}: optional fields must be nullable")

    # -- derived ---------------------------------------------------------
    @property
    def allowed_values(self) -> tuple[str, ...]:
        """Permitted values, generated from the enum class - never typed twice."""
        return tuple(self.enum_ref.values()) if self.enum_ref is not None else ()

    @property
    def normalised_name(self) -> str:
        return normalise_header(self.name)

    @property
    def match_keys(self) -> tuple[str, ...]:
        """Every normalised spelling that resolves to this field.

        The canonical name and the human title are always accepted, so an alias
        list only has to carry genuinely different vendor wording.
        """
        keys = [normalise_header(self.name), normalise_header(self.title)]
        keys.extend(normalise_header(a) for a in self.aliases)
        seen: dict[str, None] = {}
        for key in keys:
            if key:
                seen.setdefault(key, None)
        return tuple(seen)

    @property
    def range_text(self) -> str:
        """Human-readable range, used in messages and in the dictionary."""
        if self.minimum is None and self.maximum is None:
            return ""
        low = "-inf" if self.minimum is None else str(self.minimum)
        high = "+inf" if self.maximum is None else str(self.maximum)
        return (
            f"{'(' if self.min_exclusive else '['}{low}, {high}{')' if self.max_exclusive else ']'}"
        )

    def json_schema(self) -> dict[str, Any]:
        """JSON Schema (draft 2020-12) fragment for a single value."""
        base: dict[str, Any] = {"title": self.title, "description": self.description}
        types: list[str]
        if self.dtype is DType.INTEGER:
            types = ["integer"]
        elif self.dtype is DType.DECIMAL:
            types = ["number"]
            base["x-precision"] = self.precision
            base["x-scale"] = self.scale
        elif self.dtype is DType.BOOLEAN:
            types = ["boolean"]
        else:
            types = ["string"]

        if self.dtype is DType.DATE:
            base["format"] = "date"
        elif self.dtype is DType.MONTH:
            base["pattern"] = r"^\d{4}-(0[1-9]|1[0-2])$"
            base["x-grain"] = "month"
        elif self.dtype is DType.CURRENCY_CODE:
            base["pattern"] = r"^[A-Z]{3}$"
            base["x-standard"] = "ISO 4217"
        elif self.dtype is DType.ENUM:
            base["enum"] = list(self.allowed_values)

        if self.nullable:
            types.append("null")
        base["type"] = types if len(types) > 1 else types[0]

        if self.max_length is not None:
            base["maxLength"] = self.max_length
        if self.pattern is not None and "pattern" not in base:
            base["pattern"] = self.pattern
        if self.minimum is not None and self.dtype in {DType.INTEGER, DType.DECIMAL}:
            key = "exclusiveMinimum" if self.min_exclusive else "minimum"
            base[key] = float(self.minimum)  # type: ignore[arg-type]
        if self.maximum is not None and self.dtype in {DType.INTEGER, DType.DECIMAL}:
            key = "exclusiveMaximum" if self.max_exclusive else "maximum"
            base[key] = float(self.maximum)  # type: ignore[arg-type]
        if self.unit:
            base["x-unit"] = self.unit
        if self.taxonomy_ref is not None:
            base["x-taxonomy"] = self.taxonomy_ref.value
        if self.pii:
            base["x-pii"] = True
        if self.example:
            base["examples"] = [self.example]
        if self.aliases:
            base["x-aliases"] = list(self.aliases)
        return base


# ===========================================================================
# Rules
# ===========================================================================


@dataclass(frozen=True, slots=True)
class RuleOptions:
    """Tunable thresholds referenced by shared rules.

    They live in one object so a tenant can raise or lower a threshold without a
    code change, and so a test can assert a boundary without monkey-patching.
    """

    #: A probabilistic crosswalk match accepted below this is flagged for review.
    probabilistic_review_threshold: Decimal = Decimal("0.80")
    #: Rx coverage below this is retained but warned about (plan.md §10.2
    #: "outcome-coverage thresholds").
    coverage_warning_threshold: Decimal = Decimal("0.50")
    #: How far past ``today`` an outcome period may sit before it is impossible.
    future_period_grace_days: int = 31


@dataclass(frozen=True, slots=True)
class RowView:
    """A coerced row as the rules see it.

    ``row_number`` is the original 1-based file row (plan.md §10.3). ``ordinal``
    is the 0-based index among data rows and is what frame rules address, because
    two rows can share a row number only if something upstream is broken.
    """

    ordinal: int
    row_number: int
    values: Mapping[str, Any]

    def get(self, name: str) -> Any:
        return self.values.get(name)

    def present(self, name: str) -> bool:
        return self.values.get(name) is not None


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Everything a rule may look at besides the row itself.

    Note what is *not* here: no session, no database handle, no request. Rules are
    pure functions of (row, context), which is what makes them testable with plain
    dictionaries (plan.md §17).
    """

    today: date
    options: RuleOptions = field(default_factory=RuleOptions)
    scope: Mapping[ScopeKind, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuleViolation:
    """What a row rule yields. Rendered into an :class:`Issue` by the orchestrator."""

    code: IssueCode
    field_name: str | None = None
    severity: IssueSeverity | None = None
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FrameViolation:
    """What a frame rule yields: a violation plus the rows it applies to."""

    code: IssueCode
    ordinals: tuple[int, ...]
    field_name: str | None = None
    severity: IssueSeverity | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    #: Rows the rule wants dropped without an error (duplicate supersession).
    drop_ordinals: tuple[int, ...] = ()


RowCheck = Callable[[RowView, RuleContext], Sequence[RuleViolation]]
FrameCheck = Callable[[Sequence[RowView], RuleContext], Sequence[FrameViolation]]


@dataclass(frozen=True, slots=True)
class RowRule:
    """A cross-field rule evaluated on one row in isolation."""

    name: str
    code: IssueCode
    description: str
    fields: tuple[str, ...]
    check: RowCheck

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "primary_code": self.code.value,
            "description": self.description,
            "fields": list(self.fields),
        }


@dataclass(frozen=True, slots=True)
class FrameRule:
    """A cross-row rule evaluated once over the whole validated frame.

    Frame rules see every row that survived field-level validation. They are how
    "no overlapping effective ranges" and "one source id, one master" are
    enforced - questions no single row can answer.
    """

    name: str
    code: IssueCode
    description: str
    fields: tuple[str, ...]
    check: FrameCheck

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "primary_code": self.code.value,
            "description": self.description,
            "fields": list(self.fields),
        }


@dataclass(frozen=True, slots=True)
class ReferenceSpec:
    """A tenant-scoped foreign-key-ish check, declared but not executed here."""

    field_name: str
    target: ReferenceTarget
    description: str
    #: When the field may be blank, a blank does not trigger the check.
    required: bool = True

    @property
    def issue_code(self) -> IssueCode:
        return REFERENCE_ISSUE_CODES[self.target]

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field_name,
            "target": self.target.value,
            "issue_code": self.issue_code.value,
            "description": self.description,
            "required": self.required,
        }


# ===========================================================================
# Dataset contract
# ===========================================================================


@dataclass(frozen=True, slots=True)
class DatasetContract:
    """One versioned intake contract - the authority for a dataset type."""

    dataset_type: DatasetType
    version: str
    title: str
    description: str
    #: plan.md §10.1 "Expected owner" column, verbatim.
    owner: str
    cadence: Cadence
    fields: tuple[FieldSpec, ...]
    #: Business key used for duplicate detection and for upsert on commit.
    natural_key: tuple[str, ...]
    duplicate_policy: DuplicatePolicy
    requires_scope: tuple[ScopeKind, ...] = ()
    references: tuple[ReferenceSpec, ...] = ()
    row_rules: tuple[RowRule, ...] = ()
    frame_rules: tuple[FrameRule, ...] = ()
    forbidden_headers: tuple[ForbiddenHeaderPattern, ...] = ()
    sample_rows: tuple[Mapping[str, str], ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _SEMVER.match(self.version):
            raise ValueError(f"{self.dataset_type}: version must be semver, got {self.version!r}")
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.dataset_type}: duplicate field names")
        for key in self.natural_key:
            if key not in names:
                raise ValueError(f"{self.dataset_type}: natural key field {key!r} is not a field")
        if not self.natural_key:
            raise ValueError(f"{self.dataset_type}: a natural key is required")
        for reference in self.references:
            if reference.field_name not in names:
                raise ValueError(
                    f"{self.dataset_type}: reference on unknown field {reference.field_name!r}"
                )
        # A column may not resolve to two different fields, or the mapping wizard
        # would have to guess and plan.md §10.3 forbids guessing.
        seen: dict[str, str] = {}
        for spec in self.fields:
            for key in spec.match_keys:
                if key in seen and seen[key] != spec.name:
                    raise ValueError(
                        f"{self.dataset_type}: alias {key!r} is claimed by both "
                        f"{seen[key]!r} and {spec.name!r}"
                    )
                seen[key] = spec.name
        for row in self.sample_rows:
            unknown = set(row) - set(names)
            if unknown:
                raise ValueError(
                    f"{self.dataset_type}: sample row has unknown keys {sorted(unknown)}"
                )

    # -- lookups ---------------------------------------------------------
    @property
    def slug(self) -> str:
        return self.dataset_type.value

    @property
    def field_map(self) -> Mapping[str, FieldSpec]:
        return {f.name: f for f in self.fields}

    @property
    def required_fields(self) -> tuple[FieldSpec, ...]:
        return tuple(f for f in self.fields if f.required)

    @property
    def pii_fields(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.pii)

    @property
    def all_forbidden_headers(self) -> tuple[ForbiddenHeaderPattern, ...]:
        """Contract-specific refusals on top of the platform-wide §15 list."""
        return GLOBAL_FORBIDDEN_HEADERS + self.forbidden_headers

    def field_for(self, name: str) -> FieldSpec:
        return self.field_map[name]

    def header_row(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    def natural_key_of(self, values: Mapping[str, Any]) -> tuple[str, ...]:
        """Stringified business key. ``None`` renders as an empty segment so two
        rows that are both missing a key part collide rather than silently pass."""
        return tuple("" if values.get(k) is None else str(values.get(k)) for k in self.natural_key)

    # -- serialisation ---------------------------------------------------
    def json_schema(
        self, *, base_uri: str = "https://contracts.speaker-roi.local"
    ) -> dict[str, Any]:
        """JSON Schema for a single conformed row of this dataset."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"{base_uri}/{self.slug}/v{self.version}/schema.json",
            "title": self.title,
            "description": self.description,
            "type": "object",
            "properties": {f.name: f.json_schema() for f in self.fields},
            "required": [f.name for f in self.fields if f.required and not f.nullable],
            "additionalProperties": False,
            "x-contract": {
                "dataset_type": self.dataset_type.value,
                "version": self.version,
                "owner": self.owner,
                "cadence": self.cadence.value,
                "natural_key": list(self.natural_key),
                "duplicate_policy": self.duplicate_policy,
                "requires_scope": [s.value for s in self.requires_scope],
                "references": [r.as_dict() for r in self.references],
                "row_rules": [r.as_dict() for r in self.row_rules],
                "frame_rules": [r.as_dict() for r in self.frame_rules],
                "forbidden_headers": [
                    {"pattern": p.pattern, "code": p.code.value, "reason": p.reason}
                    for p in self.all_forbidden_headers
                ],
                "pii_fields": list(self.pii_fields),
                "notes": list(self.notes),
            },
        }


# ===========================================================================
# Registry
# ===========================================================================


@lru_cache(maxsize=1)
def _registry() -> dict[DatasetType, tuple[DatasetContract, ...]]:
    """Build the registry.

    The import is deliberately function-local: ``definitions/`` imports the model
    from this module, so a module-level import here would be circular. Keeping it
    lazy also means importing ``contracts`` for the model alone (as the API's
    typing layer does) does not pull in twelve dataset modules.
    """
    from speaker_roi_analytics.ingestion.definitions import ALL_CONTRACTS

    grouped: dict[DatasetType, list[DatasetContract]] = {}
    for contract in ALL_CONTRACTS:
        grouped.setdefault(contract.dataset_type, []).append(contract)
    out: dict[DatasetType, tuple[DatasetContract, ...]] = {}
    for dataset_type, contracts in grouped.items():
        ordered = sorted(contracts, key=lambda c: tuple(int(p) for p in c.version.split(".")))
        versions = [c.version for c in ordered]
        if len(versions) != len(set(versions)):
            raise RuntimeError(f"{dataset_type}: duplicate contract versions {versions}")
        out[dataset_type] = tuple(ordered)
    missing = set(DatasetType) - set(out)
    if missing:
        raise RuntimeError(
            f"DatasetType members without a contract: {sorted(m.value for m in missing)}"
        )
    return out


def contract_registry() -> Mapping[DatasetType, tuple[DatasetContract, ...]]:
    """Every published contract, grouped by dataset type and ordered by version."""
    return _registry()


def all_contracts() -> tuple[DatasetContract, ...]:
    """Latest-first flat list in ``DatasetType`` declaration order (deterministic)."""
    registry = _registry()
    return tuple(c for dataset_type in DatasetType for c in registry[dataset_type])


def get_contract(dataset_type: DatasetType, version: str | None = None) -> DatasetContract:
    """Return one contract; ``version=None`` selects the newest published version."""
    versions = _registry()[dataset_type]
    if version is None:
        return versions[-1]
    for contract in versions:
        if contract.version == version:
            return contract
    raise KeyError(f"{dataset_type.value} has no contract version {version!r}")
