"""The closed catalogue of intake issue codes.

Why this module exists
----------------------
plan.md §10.2 requires the upload pipeline to "produce machine-readable JSON
plus human-readable CSV error reports" and, in the same section, "Never log file
contents, access tokens or sensitive free text". Those two requirements pull in
opposite directions unless the vocabulary of failures is *closed and pre-written*:
a message assembled ad hoc at the point of failure inevitably ends up
interpolating the offending cell, and the offending cell is untrusted supplier
data (plan.md §15: "Treat all uploaded data as untrusted").

So every failure this package can emit is declared here once, with:

* a stable ``IssueCode`` that the API, the UI and the row-level error workbook
  all key off (it is part of the product's public contract - renaming one is a
  breaking change);
* an ``IssueSeverity`` from the core vocabulary - ``ERROR`` rejects the row,
  ``QUARANTINE`` parks it for a steward, ``WARNING`` accepts and flags it;
* a **safe** message template that names the field and the rule. Templates that
  interpolate ``{value}`` are marked ``echoes_value=True`` and the renderer
  replaces the value with ``[redacted]`` whenever the field carries
  ``FieldSpec.pii`` - so a personal datum can never reach a log line, an error
  CSV, or a screen;
* a remediation hint aimed at the person who has to fix the file, not at us;
* the plan.md §10.2 validation ``Gate`` the code implements, so "every gate is
  reachable" is a test assertion rather than a claim.

``ISSUE_CATALOGUE`` is data, not code: the API serves it verbatim so the portal
can render "what does this error mean" without a second copy of the text, and
``docs/data_dictionary.md`` is generated from it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import StrEnum
from typing import Any, Final

from speaker_roi_core.enums import IssueSeverity

__all__ = [
    "ISSUE_CATALOGUE",
    "Gate",
    "Issue",
    "IssueCategory",
    "IssueCode",
    "IssueDefinition",
    "catalogue_rows",
    "definition_for",
    "make_issue",
    "sanitize_scalar",
]

#: Hard cap on any supplier-derived fragment that reaches a message. Long enough
#: to identify a bad cell, short enough that a crafted 1 MB cell cannot be used
#: to flood the issue store or a log sink.
MAX_ECHO_CHARS: Final[int] = 80

#: What a redacted value renders as. Deliberately not the empty string, so a
#: reader can tell "we withheld this" from "the cell was blank".
REDACTED: Final[str] = "[redacted]"


class Gate(StrEnum):
    """The validation gates enumerated in plan.md §10.2, plus the §15 privacy gate.

    Every :class:`IssueDefinition` names the gate it enforces. ``tests/unit``
    asserts that each gate has at least one reachable code, which turns "all the
    gates exist" from a review opinion into a passing test.
    """

    #: "Allowed extension and MIME signature; configurable size and row limits."
    EXTENSION_AND_LIMITS = "EXTENSION_AND_LIMITS"
    #: "Header/schema version, required fields and data types."
    HEADER_AND_TYPES = "HEADER_AND_TYPES"
    #: "Unique keys and duplicate handling."
    UNIQUE_KEYS = "UNIQUE_KEYS"
    #: "Valid campaign/event/vendor assignment."
    SCOPE_ASSIGNMENT = "SCOPE_ASSIGNMENT"
    #: "Dates, event windows and event status."
    DATES_AND_EVENT_WINDOWS = "DATES_AND_EVENT_WINDOWS"
    #: "Non-negative Rx/cost counts and valid currency."
    NON_NEGATIVE_AND_CURRENCY = "NON_NEGATIVE_AND_CURRENCY"
    #: "Product and HCP identity match state."
    IDENTITY_MATCH = "IDENTITY_MATCH"
    #: "Missing period versus genuine zero outcome."
    MISSING_VERSUS_ZERO = "MISSING_VERSUS_ZERO"
    #: "Cost reconciliation and outcome-coverage thresholds."
    RECONCILIATION_AND_COVERAGE = "RECONCILIATION_AND_COVERAGE"
    #: "Cross-tenant identifiers always fail closed."
    CROSS_TENANT_FAIL_CLOSED = "CROSS_TENANT_FAIL_CLOSED"
    #: plan.md §15 / §7.4 - forbidden personal data and named-HCP targeting.
    PRIVACY_AND_TARGETING = "PRIVACY_AND_TARGETING"


class IssueCategory(StrEnum):
    """Coarse grouping used to sort the error workbook and the docs table."""

    FILE = "FILE"
    SCHEMA = "SCHEMA"
    TYPE = "TYPE"
    VALUE = "VALUE"
    TAXONOMY = "TAXONOMY"
    REFERENCE = "REFERENCE"
    DUPLICATE = "DUPLICATE"
    IDENTITY = "IDENTITY"
    RULE = "RULE"
    POLICY = "POLICY"
    INTERNAL = "INTERNAL"


class IssueCode(StrEnum):
    """Stable, documented failure codes. Closed set; additions are additive only."""

    # --- file / container -------------------------------------------------
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_EMPTY = "FILE_EMPTY"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_TOO_MANY_ROWS = "FILE_TOO_MANY_ROWS"
    FILE_TOO_MANY_COLUMNS = "FILE_TOO_MANY_COLUMNS"
    FILE_UNSUPPORTED_EXTENSION = "FILE_UNSUPPORTED_EXTENSION"
    FILE_MACRO_ENABLED_WORKBOOK = "FILE_MACRO_ENABLED_WORKBOOK"
    FILE_LEGACY_BINARY_WORKBOOK = "FILE_LEGACY_BINARY_WORKBOOK"
    FILE_ENCRYPTED_WORKBOOK = "FILE_ENCRYPTED_WORKBOOK"
    FILE_CORRUPT = "FILE_CORRUPT"
    FILE_COMPRESSION_RATIO_SUSPICIOUS = "FILE_COMPRESSION_RATIO_SUSPICIOUS"
    FILE_SHEET_NOT_FOUND = "FILE_SHEET_NOT_FOUND"
    FILE_NO_VISIBLE_SHEET = "FILE_NO_VISIBLE_SHEET"
    FILE_SHEET_DIMENSIONS_EXCEEDED = "FILE_SHEET_DIMENSIONS_EXCEEDED"
    FILE_ENCODING_UNDETECTED = "FILE_ENCODING_UNDETECTED"
    FILE_ENCODING_LOW_CONFIDENCE = "FILE_ENCODING_LOW_CONFIDENCE"
    FILE_DECODE_ERROR = "FILE_DECODE_ERROR"
    FILE_DELIMITER_AMBIGUOUS = "FILE_DELIMITER_AMBIGUOUS"
    FILE_DELIMITER_UNCONFIRMED = "FILE_DELIMITER_UNCONFIRMED"
    FILE_FIELD_TOO_LARGE = "FILE_FIELD_TOO_LARGE"

    # --- header / schema --------------------------------------------------
    SCHEMA_NO_HEADER_ROW = "SCHEMA_NO_HEADER_ROW"
    SCHEMA_MISSING_REQUIRED_COLUMN = "SCHEMA_MISSING_REQUIRED_COLUMN"
    SCHEMA_UNKNOWN_COLUMN = "SCHEMA_UNKNOWN_COLUMN"
    SCHEMA_DUPLICATE_COLUMN = "SCHEMA_DUPLICATE_COLUMN"
    SCHEMA_AMBIGUOUS_COLUMN_MATCH = "SCHEMA_AMBIGUOUS_COLUMN_MATCH"
    SCHEMA_EMPTY_HEADER_CELL = "SCHEMA_EMPTY_HEADER_CELL"
    SCHEMA_ROW_LENGTH_MISMATCH = "SCHEMA_ROW_LENGTH_MISMATCH"
    SCHEMA_UNKNOWN_CONTRACT_VERSION = "SCHEMA_UNKNOWN_CONTRACT_VERSION"
    SCHEMA_MAPPING_UNKNOWN_FIELD = "SCHEMA_MAPPING_UNKNOWN_FIELD"

    # --- type coercion ----------------------------------------------------
    TYPE_INVALID_INTEGER = "TYPE_INVALID_INTEGER"
    TYPE_INVALID_DECIMAL = "TYPE_INVALID_DECIMAL"
    TYPE_INVALID_BOOLEAN = "TYPE_INVALID_BOOLEAN"
    TYPE_INVALID_DATE = "TYPE_INVALID_DATE"
    TYPE_AMBIGUOUS_DATE = "TYPE_AMBIGUOUS_DATE"
    TYPE_INVALID_MONTH = "TYPE_INVALID_MONTH"
    TYPE_INVALID_CURRENCY_CODE = "TYPE_INVALID_CURRENCY_CODE"
    TYPE_DECIMAL_PRECISION_EXCEEDED = "TYPE_DECIMAL_PRECISION_EXCEEDED"
    TYPE_DECIMAL_SCALE_EXCEEDED = "TYPE_DECIMAL_SCALE_EXCEEDED"

    # --- value constraints ------------------------------------------------
    VALUE_REQUIRED_MISSING = "VALUE_REQUIRED_MISSING"
    VALUE_NULL_NOT_ALLOWED = "VALUE_NULL_NOT_ALLOWED"
    VALUE_NEGATIVE_NOT_ALLOWED = "VALUE_NEGATIVE_NOT_ALLOWED"
    VALUE_OUT_OF_RANGE = "VALUE_OUT_OF_RANGE"
    VALUE_TOO_LONG = "VALUE_TOO_LONG"
    VALUE_PATTERN_MISMATCH = "VALUE_PATTERN_MISMATCH"
    VALUE_NOT_IN_ENUM = "VALUE_NOT_IN_ENUM"
    VALUE_REQUIRED_UNLESS_SUPPRESSED = "VALUE_REQUIRED_UNLESS_SUPPRESSED"

    # --- tenant-scoped controlled lists -----------------------------------
    TAXONOMY_UNKNOWN_VALUE = "TAXONOMY_UNKNOWN_VALUE"

    # --- tenant-scoped references -----------------------------------------
    REF_UNKNOWN_BRAND_CODE = "REF_UNKNOWN_BRAND_CODE"
    REF_UNKNOWN_PRODUCT_CODE = "REF_UNKNOWN_PRODUCT_CODE"
    REF_UNKNOWN_CAMPAIGN_CODE = "REF_UNKNOWN_CAMPAIGN_CODE"
    REF_UNKNOWN_EVENT_CODE = "REF_UNKNOWN_EVENT_CODE"
    REF_UNKNOWN_VENDOR_CODE = "REF_UNKNOWN_VENDOR_CODE"
    REF_UNKNOWN_HCP_IDENTIFIER = "REF_UNKNOWN_HCP_IDENTIFIER"
    REF_UNKNOWN_SOURCE_SYSTEM = "REF_UNKNOWN_SOURCE_SYSTEM"
    REF_OUTSIDE_DECLARED_SCOPE = "REF_OUTSIDE_DECLARED_SCOPE"
    REF_CROSS_TENANT_IDENTIFIER = "REF_CROSS_TENANT_IDENTIFIER"

    # --- duplicate handling -----------------------------------------------
    DUPLICATE_NATURAL_KEY = "DUPLICATE_NATURAL_KEY"
    DUPLICATE_SUPERSEDED = "DUPLICATE_SUPERSEDED"
    DUPLICATE_RECONCILED = "DUPLICATE_RECONCILED"

    # --- identity ---------------------------------------------------------
    IDENTITY_AMBIGUOUS_CROSSWALK = "IDENTITY_AMBIGUOUS_CROSSWALK"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"

    # --- cross-field and cross-row business rules -------------------------
    RULE_INVALID_EFFECTIVE_RANGE = "RULE_INVALID_EFFECTIVE_RANGE"
    RULE_OVERLAPPING_EFFECTIVE_RANGE = "RULE_OVERLAPPING_EFFECTIVE_RANGE"
    RULE_MISSING_VERSUS_ZERO = "RULE_MISSING_VERSUS_ZERO"
    RULE_UNSUPPORTED_PROVENANCE = "RULE_UNSUPPORTED_PROVENANCE"
    RULE_SUPPRESSED_VALUE_PRESENT = "RULE_SUPPRESSED_VALUE_PRESENT"
    RULE_VERIFIED_WITHOUT_SOURCE = "RULE_VERIFIED_WITHOUT_SOURCE"
    RULE_ATTENDANCE_STATUS_CONFLICT = "RULE_ATTENDANCE_STATUS_CONFLICT"
    RULE_ATTENDANCE_CONFLICTING_EVIDENCE = "RULE_ATTENDANCE_CONFLICTING_EVIDENCE"
    RULE_ATTENDANCE_CONFLICTING_STRONG_SOURCE = "RULE_ATTENDANCE_CONFLICTING_STRONG_SOURCE"
    RULE_EVENT_STATUS_DATE_CONFLICT = "RULE_EVENT_STATUS_DATE_CONFLICT"
    RULE_EVENT_OUTSIDE_CAMPAIGN_WINDOW = "RULE_EVENT_OUTSIDE_CAMPAIGN_WINDOW"
    RULE_FUTURE_PERIOD = "RULE_FUTURE_PERIOD"
    RULE_TRX_LESS_THAN_NRX = "RULE_TRX_LESS_THAN_NRX"
    RULE_AT_LEAST_ONE_REQUIRED = "RULE_AT_LEAST_ONE_REQUIRED"
    RULE_DEPENDENT_FIELD_REQUIRED = "RULE_DEPENDENT_FIELD_REQUIRED"
    RULE_MIXED_CURRENCY_EVENT = "RULE_MIXED_CURRENCY_EVENT"
    RULE_ELIGIBILITY_REASON_REQUIRED = "RULE_ELIGIBILITY_REASON_REQUIRED"
    RULE_ZERO_QUANTITY = "RULE_ZERO_QUANTITY"
    RULE_APPROVAL_WITHOUT_APPROVER = "RULE_APPROVAL_WITHOUT_APPROVER"
    RULE_CONFIDENCE_BELOW_REVIEW_THRESHOLD = "RULE_CONFIDENCE_BELOW_REVIEW_THRESHOLD"
    RULE_STALE_CANDIDATE_DATE = "RULE_STALE_CANDIDATE_DATE"
    RULE_COVERAGE_BELOW_THRESHOLD = "RULE_COVERAGE_BELOW_THRESHOLD"

    # --- compliance policy ------------------------------------------------
    POLICY_FORBIDDEN_PII_COLUMN = "POLICY_FORBIDDEN_PII_COLUMN"
    POLICY_NAMED_HCP_TARGETING = "POLICY_NAMED_HCP_TARGETING"
    POLICY_FORMULA_NEUTRALISED = "POLICY_FORMULA_NEUTRALISED"

    # --- internal ---------------------------------------------------------
    INTERNAL_COERCION_FAILURE = "INTERNAL_COERCION_FAILURE"

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


@dataclass(frozen=True, slots=True)
class IssueDefinition:
    """One row of the published error catalogue."""

    code: IssueCode
    severity: IssueSeverity
    category: IssueCategory
    gate: Gate
    title: str
    #: ``str.format_map``-style template. Placeholders that are not supplied at
    #: render time degrade to ``(unspecified)`` rather than raising - an error
    #: report must never fail to render because of a missing detail.
    message_template: str
    remediation: str
    #: True when the template interpolates supplier data. Those templates are the
    #: only ones the redaction path has to consider.
    echoes_value: bool = False

    @property
    def docs_anchor(self) -> str:
        """Anchor into the generated ``docs/data_dictionary.md`` issue table."""
        return f"data_dictionary.md#issue-{self.code.value.lower().replace('_', '-')}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "category": self.category.value,
            "gate": self.gate.value,
            "title": self.title,
            "message_template": self.message_template,
            "remediation": self.remediation,
            "echoes_value": self.echoes_value,
            "docs_anchor": self.docs_anchor,
        }


def _d(
    code: IssueCode,
    severity: IssueSeverity,
    category: IssueCategory,
    gate: Gate,
    title: str,
    message_template: str,
    remediation: str,
    *,
    echoes_value: bool = False,
) -> IssueDefinition:
    return IssueDefinition(
        code=code,
        severity=severity,
        category=category,
        gate=gate,
        title=title,
        message_template=message_template,
        remediation=remediation,
        echoes_value=echoes_value,
    )


_E = IssueSeverity.ERROR
_W = IssueSeverity.WARNING
_Q = IssueSeverity.QUARANTINE
_I = IssueSeverity.INFO

_DEFINITIONS: tuple[IssueDefinition, ...] = (
    # ---------------------------------------------------------------- file
    _d(
        IssueCode.FILE_NOT_FOUND,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "File not readable",
        "The uploaded object could not be opened for reading.",
        "Re-upload the file. If this repeats, the stored object is damaged and the batch must be recreated.",
    ),
    _d(
        IssueCode.FILE_EMPTY,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "File is empty",
        "The file contains no data rows.",
        "Export the sheet again; a file with only a header row carries no records to validate.",
    ),
    _d(
        IssueCode.FILE_TOO_LARGE,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "File exceeds the configured size limit",
        "File size {actual} bytes exceeds the configured limit of {limit} bytes.",
        "Split the export into several files and upload them as separate batches; each batch is versioned independently.",
    ),
    _d(
        IssueCode.FILE_TOO_MANY_ROWS,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "File exceeds the configured row limit",
        "The file contains more than the configured limit of {limit} data rows.",
        "Split the export by period or by brand and upload each part as its own batch.",
    ),
    _d(
        IssueCode.FILE_TOO_MANY_COLUMNS,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "File exceeds the configured column limit",
        "The header row declares more than the configured limit of {limit} columns.",
        "Remove pivot or scratch columns to the right of the data and export again.",
    ),
    _d(
        IssueCode.FILE_UNSUPPORTED_EXTENSION,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Unsupported file type",
        "File extension {extension} is not accepted; supported types are .csv and .xlsx.",
        "Save the workbook as .xlsx or export the sheet as .csv and upload again.",
    ),
    _d(
        IssueCode.FILE_MACRO_ENABLED_WORKBOOK,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Macro-enabled workbook rejected",
        "The workbook contains or declares a macro project and is refused without being opened.",
        "Save a copy as .xlsx (Excel: File > Save As > Excel Workbook) and upload that copy.",
    ),
    _d(
        IssueCode.FILE_LEGACY_BINARY_WORKBOOK,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Legacy .xls workbook rejected",
        "Legacy binary workbooks (.xls) are not supported.",
        "Open the file in Excel and save it as .xlsx, then upload again.",
    ),
    _d(
        IssueCode.FILE_ENCRYPTED_WORKBOOK,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Encrypted workbook rejected",
        "The workbook is password protected; the platform does not accept credentials to open supplier files.",
        "Remove the password (File > Info > Protect Workbook > Encrypt with Password, clear the box) and upload again.",
    ),
    _d(
        IssueCode.FILE_CORRUPT,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "File could not be parsed",
        "The file is not a readable {format} container.",
        "Re-export from the source system; a partially transferred file will fail here.",
    ),
    _d(
        IssueCode.FILE_COMPRESSION_RATIO_SUSPICIOUS,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Workbook expands to an implausible size",
        "The archive expands to {actual} bytes at a compression ratio of {ratio}:1, above the configured safety limit.",
        "Export a workbook that contains only the intake sheet; embedded images and full-sheet formatting inflate the archive.",
    ),
    _d(
        IssueCode.FILE_SHEET_NOT_FOUND,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Requested worksheet not present",
        "Worksheet {sheet} was requested but the workbook contains {sheets}.",
        "Select one of the worksheets listed, or rename the intake sheet to match the template.",
    ),
    _d(
        IssueCode.FILE_NO_VISIBLE_SHEET,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Workbook has no visible worksheet",
        "Every worksheet in the workbook is hidden and hidden sheets are not read by default.",
        "Unhide the sheet that holds the data, or ask an administrator to permit hidden sheets for this source.",
    ),
    _d(
        IssueCode.FILE_SHEET_DIMENSIONS_EXCEEDED,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Worksheet dimensions exceed the configured limit",
        "Worksheet {sheet} declares {actual} cells, above the configured limit of {limit}.",
        "Delete unused rows and columns (Ctrl+Shift+End should land on the last real cell) and save again.",
    ),
    _d(
        IssueCode.FILE_ENCODING_UNDETECTED,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Text encoding could not be determined",
        "No character encoding could be detected for this file.",
        "Re-export the CSV as UTF-8. Most systems offer 'CSV UTF-8' as an explicit export option.",
    ),
    _d(
        IssueCode.FILE_ENCODING_LOW_CONFIDENCE,
        _W,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Text encoding detected with low confidence",
        "Encoding {encoding} was detected with confidence {confidence}; {fallback} was used instead.",
        "Re-export as UTF-8 if accented or non-Latin characters look wrong in the preview.",
    ),
    _d(
        IssueCode.FILE_DECODE_ERROR,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "File could not be decoded",
        "The file could not be decoded as {encoding}.",
        "Re-export the CSV as UTF-8 and upload again.",
    ),
    _d(
        IssueCode.FILE_DELIMITER_AMBIGUOUS,
        _W,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Delimiter could not be determined unambiguously",
        "More than one delimiter fits this file ({allowed}); {delimiter} was proposed and needs confirmation.",
        "Confirm the delimiter in the upload wizard, or re-export using a comma.",
    ),
    _d(
        IssueCode.FILE_DELIMITER_UNCONFIRMED,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "Delimiter needs explicit confirmation",
        "The proposed delimiter {delimiter} was not confirmed, so the file was not parsed.",
        "Confirm or correct the delimiter in the upload wizard before processing.",
    ),
    _d(
        IssueCode.FILE_FIELD_TOO_LARGE,
        _E,
        IssueCategory.FILE,
        Gate.EXTENSION_AND_LIMITS,
        "A single field exceeds the configured size limit",
        "A field on this row exceeds the configured limit of {limit} bytes.",
        "Check for an unterminated quote: an unclosed quotation mark makes the parser read the rest of the file as one field.",
    ),
    # -------------------------------------------------------------- schema
    _d(
        IssueCode.SCHEMA_NO_HEADER_ROW,
        _E,
        IssueCategory.SCHEMA,
        Gate.HEADER_AND_TYPES,
        "No header row found",
        "No row in the first {limit} rows looks like a header for {dataset}.",
        "Download the current template and copy your data underneath its header row.",
    ),
    _d(
        IssueCode.SCHEMA_MISSING_REQUIRED_COLUMN,
        _E,
        IssueCategory.SCHEMA,
        Gate.HEADER_AND_TYPES,
        "Required column missing",
        "Required column {field} is not present and no accepted alternate spelling was found.",
        "Add the column using the template header, or map an existing column to it in the column-mapping step.",
    ),
    _d(
        IssueCode.SCHEMA_UNKNOWN_COLUMN,
        _W,
        IssueCategory.SCHEMA,
        Gate.HEADER_AND_TYPES,
        "Column not part of the contract",
        "Column {column} is not part of contract {dataset} and was ignored.",
        "Remove the column, or map it to a contract field if it holds data the contract expects.",
    ),
    _d(
        IssueCode.SCHEMA_DUPLICATE_COLUMN,
        _E,
        IssueCategory.SCHEMA,
        Gate.HEADER_AND_TYPES,
        "Duplicate column header",
        "Header {column} appears more than once, so the intended source column is undefined.",
        "Rename or delete the duplicate column and upload again.",
    ),
    _d(
        IssueCode.SCHEMA_AMBIGUOUS_COLUMN_MATCH,
        _E,
        IssueCategory.SCHEMA,
        Gate.HEADER_AND_TYPES,
        "Several columns match one contract field",
        "Columns {allowed} all match contract field {field}; the platform will not guess between them.",
        "Keep exactly one of these columns, or choose the correct one in the column-mapping step.",
    ),
    _d(
        IssueCode.SCHEMA_EMPTY_HEADER_CELL,
        _W,
        IssueCategory.SCHEMA,
        Gate.HEADER_AND_TYPES,
        "Blank header cell",
        "Column {column} in the header row is blank and was ignored.",
        "Delete the empty column, or give it the header from the template.",
    ),
    _d(
        IssueCode.SCHEMA_ROW_LENGTH_MISMATCH,
        _E,
        IssueCategory.SCHEMA,
        Gate.HEADER_AND_TYPES,
        "Row has a different number of fields than the header",
        "This row has {actual} fields but the header declares {expected}.",
        "Look for an unescaped quote or an unquoted delimiter inside a text field on this row.",
    ),
    _d(
        IssueCode.SCHEMA_UNKNOWN_CONTRACT_VERSION,
        _E,
        IssueCategory.SCHEMA,
        Gate.HEADER_AND_TYPES,
        "Unknown contract version",
        "Contract version {expected} is not published for dataset {dataset}.",
        "Download the current template; published versions are listed in the data dictionary.",
    ),
    _d(
        IssueCode.SCHEMA_MAPPING_UNKNOWN_FIELD,
        _E,
        IssueCategory.SCHEMA,
        Gate.HEADER_AND_TYPES,
        "Saved mapping names a field the contract does not have",
        "Saved column mapping refers to field {field}, which contract {dataset} does not define.",
        "Re-run the column-mapping wizard against the current contract version and save a new mapping.",
    ),
    # ---------------------------------------------------------------- type
    _d(
        IssueCode.TYPE_INVALID_INTEGER,
        _E,
        IssueCategory.TYPE,
        Gate.HEADER_AND_TYPES,
        "Not a whole number",
        "Field {field} expects a whole number but received {value}.",
        "Remove thousands separators and decimal parts; counts must be whole numbers.",
        echoes_value=True,
    ),
    _d(
        IssueCode.TYPE_INVALID_DECIMAL,
        _E,
        IssueCategory.TYPE,
        Gate.HEADER_AND_TYPES,
        "Not a decimal number",
        "Field {field} expects a decimal number but received {value}.",
        "Use a plain number such as 1234.56. Currency symbols and thousands separators are accepted; text is not.",
        echoes_value=True,
    ),
    _d(
        IssueCode.TYPE_INVALID_BOOLEAN,
        _E,
        IssueCategory.TYPE,
        Gate.HEADER_AND_TYPES,
        "Not a true/false value",
        "Field {field} expects true or false but received {value}.",
        "Use TRUE/FALSE, YES/NO or 1/0.",
        echoes_value=True,
    ),
    _d(
        IssueCode.TYPE_INVALID_DATE,
        _E,
        IssueCategory.TYPE,
        Gate.DATES_AND_EVENT_WINDOWS,
        "Not a recognised date",
        "Field {field} expects a date but received {value}; accepted formats are {allowed}.",
        "Prefer the unambiguous ISO form YYYY-MM-DD.",
        echoes_value=True,
    ),
    _d(
        IssueCode.TYPE_AMBIGUOUS_DATE,
        _E,
        IssueCategory.TYPE,
        Gate.DATES_AND_EVENT_WINDOWS,
        "Date could mean two different days",
        "Field {field} received {value}, which is a valid date under both day-first and month-first reading.",
        "Re-export using ISO dates (YYYY-MM-DD), or set the source's date order in the upload wizard.",
        echoes_value=True,
    ),
    _d(
        IssueCode.TYPE_INVALID_MONTH,
        _E,
        IssueCategory.TYPE,
        Gate.DATES_AND_EVENT_WINDOWS,
        "Not a recognised month",
        "Field {field} expects a month but received {value}; accepted formats are {allowed}.",
        "Use YYYY-MM. Note that a spreadsheet may silently reformat a month cell as a full date.",
        echoes_value=True,
    ),
    _d(
        IssueCode.TYPE_INVALID_CURRENCY_CODE,
        _E,
        IssueCategory.TYPE,
        Gate.NON_NEGATIVE_AND_CURRENCY,
        "Not a valid ISO 4217 currency code",
        "Field {field} expects a three-letter ISO 4217 currency code but received {value}.",
        "Use the alphabetic code, for example USD, EUR or INR. Currency symbols are not accepted.",
        echoes_value=True,
    ),
    _d(
        IssueCode.TYPE_DECIMAL_PRECISION_EXCEEDED,
        _E,
        IssueCategory.TYPE,
        Gate.NON_NEGATIVE_AND_CURRENCY,
        "Number has too many significant digits",
        "Field {field} allows at most {expected} significant digits.",
        "Round the value to the declared precision before exporting.",
    ),
    _d(
        IssueCode.TYPE_DECIMAL_SCALE_EXCEEDED,
        _E,
        IssueCategory.TYPE,
        Gate.NON_NEGATIVE_AND_CURRENCY,
        "Number has too many decimal places",
        "Field {field} allows at most {expected} decimal places.",
        "Round the value; money is stored as an exact decimal and is never silently truncated.",
    ),
    # --------------------------------------------------------------- value
    _d(
        IssueCode.VALUE_REQUIRED_MISSING,
        _E,
        IssueCategory.VALUE,
        Gate.HEADER_AND_TYPES,
        "Required value missing",
        "Field {field} is required and this row leaves it blank.",
        "Fill the value in, or remove the row if the record is not real.",
    ),
    _d(
        IssueCode.VALUE_NULL_NOT_ALLOWED,
        _E,
        IssueCategory.VALUE,
        Gate.HEADER_AND_TYPES,
        "Blank not allowed for this field",
        "Field {field} does not accept a blank value.",
        "Supply a value. If the real answer is 'not measured', check whether the contract has an explicit flag for that.",
    ),
    _d(
        IssueCode.VALUE_NEGATIVE_NOT_ALLOWED,
        _E,
        IssueCategory.VALUE,
        Gate.NON_NEGATIVE_AND_CURRENCY,
        "Negative value not allowed",
        "Field {field} must not be negative.",
        "Correct the sign. Credit notes are recorded as their own rows with an approval status, never as a negative count.",
    ),
    _d(
        IssueCode.VALUE_OUT_OF_RANGE,
        _E,
        IssueCategory.VALUE,
        Gate.NON_NEGATIVE_AND_CURRENCY,
        "Value outside the permitted range",
        "Field {field} must be within {allowed}.",
        "Check the unit of the source column; a percentage supplied as 0-100 where a 0-1 fraction is expected lands here.",
    ),
    _d(
        IssueCode.VALUE_TOO_LONG,
        _E,
        IssueCategory.VALUE,
        Gate.HEADER_AND_TYPES,
        "Value longer than allowed",
        "Field {field} allows at most {expected} characters but received {actual}.",
        "Shorten the value. Long free text belongs in a notes field, not in a code field.",
    ),
    _d(
        IssueCode.VALUE_PATTERN_MISMATCH,
        _E,
        IssueCategory.VALUE,
        Gate.HEADER_AND_TYPES,
        "Value does not match the required format",
        "Field {field} must match the format {pattern}.",
        "Compare the value with the example in the data dictionary for this field.",
    ),
    _d(
        IssueCode.VALUE_NOT_IN_ENUM,
        _E,
        IssueCategory.VALUE,
        Gate.HEADER_AND_TYPES,
        "Value is not one of the permitted values",
        "Field {field} received {value}; permitted values are {allowed}.",
        "Map the source system's wording to one of the permitted values before export.",
        echoes_value=True,
    ),
    _d(
        IssueCode.VALUE_REQUIRED_UNLESS_SUPPRESSED,
        _E,
        IssueCategory.VALUE,
        Gate.MISSING_VERSUS_ZERO,
        "Blank outcome without a suppression flag",
        "Field {field} is blank but {other} is not set, so the platform cannot tell a suppressed value from a lost one.",
        "Set the suppression flag on rows the supplier withheld, and supply the number everywhere else.",
    ),
    # ------------------------------------------------------------ taxonomy
    _d(
        IssueCode.TAXONOMY_UNKNOWN_VALUE,
        _E,
        IssueCategory.TAXONOMY,
        Gate.HEADER_AND_TYPES,
        "Value is not in the company's controlled list",
        "Field {field} received {value}, which is not an active {taxonomy} value for this company.",
        "Add the value to the controlled list in Data Management, or correct the spelling to an existing entry.",
        echoes_value=True,
    ),
    # ----------------------------------------------------------- reference
    _d(
        IssueCode.REF_UNKNOWN_BRAND_CODE,
        _E,
        IssueCategory.REFERENCE,
        Gate.SCOPE_ASSIGNMENT,
        "Unknown brand code",
        "Field {field} references a brand that does not exist for this company.",
        "Load the brand in the Brand/Product master first; intake never creates master records as a side effect.",
    ),
    _d(
        IssueCode.REF_UNKNOWN_PRODUCT_CODE,
        _E,
        IssueCategory.REFERENCE,
        Gate.IDENTITY_MATCH,
        "Unknown product code",
        "Field {field} references a product that does not exist for this company.",
        "Load the product in the Brand/Product master, or add a product crosswalk row for this source system.",
    ),
    _d(
        IssueCode.REF_UNKNOWN_CAMPAIGN_CODE,
        _E,
        IssueCategory.REFERENCE,
        Gate.SCOPE_ASSIGNMENT,
        "Unknown campaign code",
        "Field {field} references a campaign that does not exist for this company.",
        "Load the campaign in the Campaign/Event master before uploading dependent data.",
    ),
    _d(
        IssueCode.REF_UNKNOWN_EVENT_CODE,
        _E,
        IssueCategory.REFERENCE,
        Gate.SCOPE_ASSIGNMENT,
        "Unknown event code",
        "Field {field} references an event that does not exist for this company.",
        "Load the event in the Campaign/Event master first, then re-upload this file.",
    ),
    _d(
        IssueCode.REF_UNKNOWN_VENDOR_CODE,
        _E,
        IssueCategory.REFERENCE,
        Gate.SCOPE_ASSIGNMENT,
        "Unknown vendor code",
        "Field {field} references a vendor that is not registered for this company.",
        "Register the vendor and its dataset assignment in Data Management before submitting its data.",
    ),
    _d(
        IssueCode.REF_UNKNOWN_HCP_IDENTIFIER,
        _Q,
        IssueCategory.REFERENCE,
        Gate.IDENTITY_MATCH,
        "Source HCP identifier not yet resolved",
        "The source identifier in {field} has no active crosswalk entry, so the row is quarantined rather than discarded.",
        "Upload an HCP crosswalk row for this source system and identifier; the quarantined rows are then re-driven.",
    ),
    _d(
        IssueCode.REF_UNKNOWN_SOURCE_SYSTEM,
        _E,
        IssueCategory.REFERENCE,
        Gate.SCOPE_ASSIGNMENT,
        "Unknown source system",
        "Field {field} names a source system that is not registered for this company.",
        "Register the source system in Company and source configuration first.",
    ),
    _d(
        IssueCode.REF_OUTSIDE_DECLARED_SCOPE,
        _E,
        IssueCategory.REFERENCE,
        Gate.SCOPE_ASSIGNMENT,
        "Row refers to something outside the declared upload scope",
        "This row references {target}, which is outside the {scope} scope declared for this upload session.",
        "Start a new upload session with the correct scope, or remove the out-of-scope rows.",
    ),
    _d(
        IssueCode.REF_CROSS_TENANT_IDENTIFIER,
        _E,
        IssueCategory.REFERENCE,
        Gate.CROSS_TENANT_FAIL_CLOSED,
        "Identifier belongs to another company",
        "Field {field} references an identifier that does not belong to this company; the row fails closed.",
        "Remove the row. Identifiers are never shared across companies, and a match here would be a data-separation defect.",
    ),
    # ----------------------------------------------------------- duplicate
    _d(
        IssueCode.DUPLICATE_NATURAL_KEY,
        _E,
        IssueCategory.DUPLICATE,
        Gate.UNIQUE_KEYS,
        "Duplicate business key",
        "More than one row carries the business key {key}, and this dataset rejects duplicates.",
        "Keep one row per business key. If two rows are genuinely different records, one of the key fields is wrong.",
    ),
    _d(
        IssueCode.DUPLICATE_SUPERSEDED,
        _I,
        IssueCategory.DUPLICATE,
        Gate.UNIQUE_KEYS,
        "Row superseded by another row with the same business key",
        "Business key {key} appears more than once; the {policy} row was kept and this one was not loaded.",
        "No action needed. Remove the redundant rows at source if you want the counts to line up exactly.",
    ),
    _d(
        IssueCode.DUPLICATE_RECONCILED,
        _I,
        IssueCategory.DUPLICATE,
        Gate.UNIQUE_KEYS,
        "Duplicate rows reconciled by evidence strength",
        "Business key {key} appeared {count} times; the row with the strongest verification evidence was kept.",
        "No action needed. The retained evidence source is shown on the attendance record.",
    ),
    # ------------------------------------------------------------ identity
    _d(
        IssueCode.IDENTITY_AMBIGUOUS_CROSSWALK,
        _Q,
        IssueCategory.IDENTITY,
        Gate.IDENTITY_MATCH,
        "One source identifier maps to several master records",
        "Source identifier {key} maps to {count} different master records over overlapping effective periods.",
        "A data steward must resolve the crosswalk. The platform never picks a master record on its own.",
    ),
    _d(
        IssueCode.IDENTITY_UNRESOLVED,
        _Q,
        IssueCategory.IDENTITY,
        Gate.IDENTITY_MATCH,
        "Identity could not be resolved",
        "The identity in {field} could not be resolved to a master record and the row is held in quarantine.",
        "Resolve the identity in the HCP crosswalk screen; quarantined rows are released once a match exists.",
    ),
    # ---------------------------------------------------------------- rule
    _d(
        IssueCode.RULE_INVALID_EFFECTIVE_RANGE,
        _E,
        IssueCategory.RULE,
        Gate.DATES_AND_EVENT_WINDOWS,
        "Effective range ends before it starts",
        "{field} must be strictly after {other}; effective ranges are half-open [from, to).",
        "Correct the dates. Leave the end blank for a row that is still current.",
    ),
    _d(
        IssueCode.RULE_OVERLAPPING_EFFECTIVE_RANGE,
        _E,
        IssueCategory.RULE,
        Gate.DATES_AND_EVENT_WINDOWS,
        "Overlapping effective ranges for the same key",
        "Key {key} has effective ranges that overlap, so the value in force on a given day is undefined.",
        "Close the earlier row before the later one starts. ROI restatements depend on exactly one assumption being in force per day.",
    ),
    _d(
        IssueCode.RULE_MISSING_VERSUS_ZERO,
        _E,
        IssueCategory.RULE,
        Gate.MISSING_VERSUS_ZERO,
        "Zero outcome declared as not observed",
        "This row reports zero for {field} while marking the period as not observed, which are two different facts.",
        "A genuine zero is an observation: set the observed flag. A period the supplier did not cover should be omitted or left blank with the flag clear.",
    ),
    _d(
        IssueCode.RULE_UNSUPPORTED_PROVENANCE,
        _E,
        IssueCategory.RULE,
        Gate.MISSING_VERSUS_ZERO,
        "Outcome supplied with neither observation nor projection provenance",
        "{field} carries a value while the row is marked neither observed nor projected.",
        "Set the observed flag for measured periods, or the projected flag for supplier-modelled periods.",
    ),
    _d(
        IssueCode.RULE_SUPPRESSED_VALUE_PRESENT,
        _W,
        IssueCategory.RULE,
        Gate.MISSING_VERSUS_ZERO,
        "Suppressed row still carries a value",
        "The suppression flag is set but {field} still holds a number.",
        "Confirm with the supplier which is correct; the analysis treats suppressed periods as unobserved.",
    ),
    _d(
        IssueCode.RULE_VERIFIED_WITHOUT_SOURCE,
        _E,
        IssueCategory.RULE,
        Gate.RECONCILIATION_AND_COVERAGE,
        "Verified attendance without a verification source",
        "Attendance is marked verified while the verification source is UNVERIFIED.",
        "Record how attendance was proven (badge scan, sign-in sheet, platform log or vendor attestation), or clear the verified flag.",
    ),
    _d(
        IssueCode.RULE_ATTENDANCE_STATUS_CONFLICT,
        _E,
        IssueCategory.RULE,
        Gate.RECONCILIATION_AND_COVERAGE,
        "Registration status contradicts verified attendance",
        "Registration status {value} cannot be combined with verified attendance.",
        "Set the registration status to ATTENDED for people who attended, or clear the verified flag.",
        echoes_value=True,
    ),
    _d(
        IssueCode.RULE_ATTENDANCE_CONFLICTING_EVIDENCE,
        _Q,
        IssueCategory.RULE,
        Gate.RECONCILIATION_AND_COVERAGE,
        "Duplicate attendance rows disagree",
        "Business key {key} appears {count} times with contradictory attendance outcomes at the same evidence strength.",
        "A steward must decide which record is correct; the platform will not pick between equally strong sources.",
    ),
    _d(
        IssueCode.RULE_ATTENDANCE_CONFLICTING_STRONG_SOURCE,
        _Q,
        IssueCategory.RULE,
        Gate.RECONCILIATION_AND_COVERAGE,
        "Two strong attendance sources disagree",
        "Business key {key} is reported differently by two strong evidence sources ({allowed}).",
        "Reconcile the badge/platform export with the source system. Treatment status is never guessed from conflicting evidence.",
    ),
    _d(
        IssueCode.RULE_EVENT_STATUS_DATE_CONFLICT,
        _E,
        IssueCategory.RULE,
        Gate.DATES_AND_EVENT_WINDOWS,
        "Event status contradicts the event date",
        "An event dated {value} cannot already be COMPLETED.",
        "Set the status to SCHEDULED until the event has happened; only completed events create exposure.",
        echoes_value=True,
    ),
    _d(
        IssueCode.RULE_EVENT_OUTSIDE_CAMPAIGN_WINDOW,
        _W,
        IssueCategory.RULE,
        Gate.DATES_AND_EVENT_WINDOWS,
        "Event falls outside its campaign window",
        "The event date lies outside the campaign period declared on the same row.",
        "Extend the campaign window or correct the event date; the row is loaded either way.",
    ),
    _d(
        IssueCode.RULE_FUTURE_PERIOD,
        _E,
        IssueCategory.RULE,
        Gate.DATES_AND_EVENT_WINDOWS,
        "Period lies in the future",
        "Field {field} refers to a period after {expected}, so it cannot contain observed data.",
        "Check the period column; a two-digit year read as a future century is the usual cause.",
    ),
    _d(
        IssueCode.RULE_TRX_LESS_THAN_NRX,
        _W,
        IssueCategory.RULE,
        Gate.MISSING_VERSUS_ZERO,
        "Total prescriptions below new prescriptions",
        "TRx is lower than NRx for this row, which is unusual because TRx normally includes refills.",
        "Confirm the supplier's definitions. The platform preserves the supplier definition and does not reconcile the two.",
    ),
    _d(
        IssueCode.RULE_AT_LEAST_ONE_REQUIRED,
        _E,
        IssueCategory.RULE,
        Gate.HEADER_AND_TYPES,
        "At least one of a group of fields is required",
        "At least one of {allowed} must be supplied on every row.",
        "Fill in whichever of the listed fields the source system can provide.",
    ),
    _d(
        IssueCode.RULE_DEPENDENT_FIELD_REQUIRED,
        _E,
        IssueCategory.RULE,
        Gate.HEADER_AND_TYPES,
        "A dependent field is required by another value on this row",
        "Field {field} is required because {other} is set to {value}.",
        "Supply the dependent value, or change the value that triggered the requirement.",
        echoes_value=True,
    ),
    _d(
        IssueCode.RULE_MIXED_CURRENCY_EVENT,
        _W,
        IssueCategory.RULE,
        Gate.RECONCILIATION_AND_COVERAGE,
        "One event carries costs in several currencies",
        "Event {key} has costs in {allowed}; there is no implicit conversion anywhere in the platform.",
        "This is accepted, but the fully loaded cost is reported per currency until an FX rate is configured for the reporting currency.",
    ),
    _d(
        IssueCode.RULE_ELIGIBILITY_REASON_REQUIRED,
        _E,
        IssueCategory.RULE,
        Gate.RECONCILIATION_AND_COVERAGE,
        "Ineligible row without a reason",
        "The row is marked ineligible but gives no eligibility reason.",
        "Record why the HCP was ineligible; every drop-off in the evidence funnel has to be explainable.",
    ),
    _d(
        IssueCode.RULE_ZERO_QUANTITY,
        _W,
        IssueCategory.RULE,
        Gate.RECONCILIATION_AND_COVERAGE,
        "Activity row with zero quantity",
        "This activity row carries a quantity of zero and therefore contributes no exposure.",
        "Remove zero-quantity rows at source if they are placeholders rather than real activity.",
    ),
    _d(
        IssueCode.RULE_APPROVAL_WITHOUT_APPROVER,
        _E,
        IssueCategory.RULE,
        Gate.RECONCILIATION_AND_COVERAGE,
        "Approved without a named approver",
        "The row is marked APPROVED but {field} is blank.",
        "Record who approved it. Approval without an accountable name is not auditable.",
    ),
    _d(
        IssueCode.RULE_CONFIDENCE_BELOW_REVIEW_THRESHOLD,
        _W,
        IssueCategory.RULE,
        Gate.IDENTITY_MATCH,
        "Probabilistic match accepted below the review threshold",
        "A probabilistic match is marked MATCHED with confidence below {expected}.",
        "Have a steward confirm the match, or set the status to AMBIGUOUS so it is queued for review.",
    ),
    _d(
        IssueCode.RULE_STALE_CANDIDATE_DATE,
        _W,
        IssueCategory.RULE,
        Gate.DATES_AND_EVENT_WINDOWS,
        "Candidate programme is dated in the past",
        "The planned date is before {expected}; candidate programmes are forward-looking design inputs.",
        "Update the planned date, or measure the event through the historical pipeline instead.",
    ),
    _d(
        IssueCode.RULE_COVERAGE_BELOW_THRESHOLD,
        _W,
        IssueCategory.RULE,
        Gate.RECONCILIATION_AND_COVERAGE,
        "Outcome coverage below the usable threshold",
        "Field {field} is below {expected}, so this period contributes little usable outcome signal.",
        "Confirm the supplier's coverage factor. Low-coverage periods are retained but weighted down in the analysis.",
    ),
    # -------------------------------------------------------------- policy
    _d(
        IssueCode.POLICY_FORBIDDEN_PII_COLUMN,
        _E,
        IssueCategory.POLICY,
        Gate.PRIVACY_AND_TARGETING,
        "File contains a column this platform must not ingest",
        "Column {column} matches the forbidden pattern {pattern}; the whole file is refused before any row is read.",
        "Remove the column at source. Patient identifiers, contact details and national health identifiers are out of scope for programme measurement.",
    ),
    _d(
        IssueCode.POLICY_NAMED_HCP_TARGETING,
        _E,
        IssueCategory.POLICY,
        Gate.PRIVACY_AND_TARGETING,
        "File tries to supply named prescribers as a prediction input",
        "Column {column} names individual prescribers, which is not accepted as an input to a programme forecast.",
        "Describe the programme design instead (topic, format, region, specialty mix, expected attendance). Forecasts are produced for designs, never for named prescribers.",
    ),
    _d(
        IssueCode.POLICY_FORMULA_NEUTRALISED,
        _I,
        IssueCategory.POLICY,
        Gate.PRIVACY_AND_TARGETING,
        "Exported cell neutralised against formula injection",
        "{count} exported cells began with a spreadsheet formula character and were prefixed with an apostrophe.",
        "No action needed. The original text is preserved; only its interpretation as a formula is prevented.",
    ),
    # ------------------------------------------------------------ internal
    _d(
        IssueCode.INTERNAL_COERCION_FAILURE,
        _E,
        IssueCategory.INTERNAL,
        Gate.HEADER_AND_TYPES,
        "Internal error while reading a value",
        "An unexpected error occurred while reading field {field}.",
        "Report the upload identifier to support. The row is not loaded.",
    ),
)

#: The published catalogue. Ordered by declaration so the docs table is stable.
ISSUE_CATALOGUE: Final[Mapping[IssueCode, IssueDefinition]] = {d.code: d for d in _DEFINITIONS}

_MISSING_CODES = set(IssueCode) - set(ISSUE_CATALOGUE)
if _MISSING_CODES:  # pragma: no cover - guards a developer mistake at import time
    raise RuntimeError(f"IssueCode members without a catalogue entry: {sorted(_MISSING_CODES)}")


def definition_for(code: IssueCode) -> IssueDefinition:
    """Return the published definition for ``code``."""
    return ISSUE_CATALOGUE[code]


def catalogue_rows() -> list[dict[str, Any]]:
    """JSON-safe catalogue for the API and the generated documentation."""
    return [d.as_dict() for d in _DEFINITIONS]


class _SafeParams(dict[str, str]):
    """``format_map`` source that degrades unknown placeholders instead of raising.

    An error report that cannot render because a detail was not supplied is worse
    than one that says ``(unspecified)``.
    """

    def __missing__(self, key: str) -> str:
        return "(unspecified)"


def sanitize_scalar(value: object, *, limit: int = MAX_ECHO_CHARS) -> str:
    """Render an untrusted scalar safely for inclusion in a message.

    Control characters (including the newlines a crafted cell would use to forge
    extra log lines) collapse to spaces, and the result is truncated. This is the
    only path by which supplier bytes reach a message string.
    """
    text = "" if value is None else str(value)
    cleaned = "".join(" " if ch < " " or ch == "\x7f" else ch for ch in text).strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 3] + "..."
    return cleaned


@dataclass(frozen=True, slots=True)
class Issue:
    """One rendered, safe, row-addressable finding.

    ``row_number`` is the **original** 1-based row number in the uploaded file -
    the physical CSV line where the record starts, or the spreadsheet row number
    (plan.md §10.3: "Preserve original row number in all validation errors").
    ``None`` means the finding is about the file or the header rather than a row.
    """

    code: IssueCode
    severity: IssueSeverity
    message: str
    field: str | None = None
    row_number: int | None = None
    column: str | None = None
    sheet: str | None = None
    context: Mapping[str, str | int | float | bool | None] = dc_field(default_factory=dict)

    @property
    def definition(self) -> IssueDefinition:
        return ISSUE_CATALOGUE[self.code]

    @property
    def category(self) -> IssueCategory:
        return self.definition.category

    @property
    def gate(self) -> Gate:
        return self.definition.gate

    def as_dict(self) -> dict[str, Any]:
        """The shape written to the machine-readable JSON report (plan.md §10.2)."""
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "category": self.category.value,
            "gate": self.gate.value,
            "row_number": self.row_number,
            "field": self.field,
            "column": self.column,
            "sheet": self.sheet,
            "message": self.message,
            "remediation": self.definition.remediation,
            "docs_anchor": self.definition.docs_anchor,
            "context": dict(self.context),
        }

    def sort_key(self) -> tuple[int, str, str, str]:
        """Deterministic ordering: file-level findings first, then by row."""
        return (
            self.row_number if self.row_number is not None else -1,
            self.field or "",
            self.code.value,
            self.message,
        )


def make_issue(
    code: IssueCode,
    *,
    field_name: str | None = None,
    row_number: int | None = None,
    column: str | None = None,
    sheet: str | None = None,
    severity: IssueSeverity | None = None,
    redact: bool = False,
    **params: object,
) -> Issue:
    """Render a catalogue entry into a concrete, safe :class:`Issue`.

    ``redact=True`` is passed by the validator whenever the field it is
    complaining about carries :attr:`FieldSpec.pii`. It replaces every
    supplier-derived parameter with ``[redacted]``, so a personal datum never
    reaches the issue store, the downloadable error workbook or a log line
    (plan.md §10.2: "Never log file contents ... or sensitive free text").

    ``severity`` overrides the catalogue default only where a contract has a
    documented reason to soften or harden a shared code.
    """
    definition = ISSUE_CATALOGUE[code]
    rendered: dict[str, str] = {}
    context: dict[str, str | int | float | bool | None] = {}
    for key, raw in params.items():
        if redact and key in _SUPPLIER_PARAMS:
            rendered[key] = REDACTED
            context[key] = REDACTED
            continue
        rendered[key] = sanitize_scalar(raw)
        context[key] = raw if isinstance(raw, str | int | float | bool | None) else str(raw)
    if field_name is not None:
        rendered.setdefault("field", field_name)
    # The structural locators double as message parameters so a caller never has
    # to pass ``column=`` twice to get "Column X is not part of ...".  They are
    # our own labels and the uploader's own header text, never a cell value, so
    # they are outside the redaction set on purpose.
    if column is not None:
        rendered.setdefault("column", sanitize_scalar(column))
    if sheet is not None:
        rendered.setdefault("sheet", sanitize_scalar(sheet))
    message = definition.message_template.format_map(_SafeParams(rendered))
    return Issue(
        code=code,
        severity=severity if severity is not None else definition.severity,
        message=message,
        field=field_name,
        row_number=row_number,
        column=column,
        sheet=sheet,
        context=context,
    )


#: Parameters whose contents come from the uploaded file rather than from us.
#: Only these are redacted; ``field``, ``allowed`` and friends are our own text.
_SUPPLIER_PARAMS: Final[frozenset[str]] = frozenset({"value", "values", "key", "sample", "target"})
