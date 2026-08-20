"""Per-field parsing of untrusted cell values into typed Python objects.

Design position
---------------
Every function here is total: it returns a :class:`Coerced` carrying either a
value or an :class:`IssueCode`, and never raises on supplier input. A parser that
throws would either abort a 200,000-row file on row 3 or force a bare
``except Exception`` around the hot loop, and both lose the row number that
plan.md §10.3 requires us to keep.

Two decisions worth defending in review:

**Ambiguous dates are refused, not guessed.** ``03/04/2024`` is 3 April in Delhi
and 4 March in Boston. Silently choosing one shifts an event by a month, which
moves rows between the pre- and post-event windows and changes a causal estimate.
So a slash date whose day/month cannot be told apart from the value alone yields
``TYPE_AMBIGUOUS_DATE`` unless the caller has declared the source's date order.
Values that *are* self-disambiguating (``25/03/2024`` - there is no month 25)
parse without complaint, so this costs real files almost nothing.

**Months are a distinct grain.** plan.md §9.3 stores Rx per HCP-product-month.
Widening a month into a timestamp is how "missing period versus genuine zero
outcome" (§10.2) becomes undecidable, so ``YYYY-MM``, ``MM/YYYY``, ``Mon-YY`` and
a full date all normalise to the first day of the month and stay month-grained.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Final

from speaker_roi_analytics.ingestion.contracts import DType, FieldSpec
from speaker_roi_analytics.ingestion.issues import IssueCode

__all__ = [
    "ACCEPTED_DATE_FORMATS",
    "ACCEPTED_MONTH_FORMATS",
    "ISO_4217_CODES",
    "NULL_TOKENS",
    "Coerced",
    "CoercionOptions",
    "DateOrder",
    "coerce_value",
    "is_null_token",
    "parse_boolean",
    "parse_date",
    "parse_decimal",
    "parse_integer",
    "parse_month",
]


class DateOrder(StrEnum):
    """How to read a slash/dot date whose day and month are both <= 12."""

    #: Parse what is unambiguous; refuse the rest with ``TYPE_AMBIGUOUS_DATE``.
    AUTO = "AUTO"
    #: ISO-8601 only. Anything else is rejected outright.
    ISO = "ISO"
    DMY = "DMY"
    MDY = "MDY"


#: Tokens that mean "no value". Deliberately excludes ``UNKNOWN`` and ``?``,
#: which are assertions about the world rather than an absent cell and should
#: fail an enum or reference check loudly.
NULL_TOKENS: Final[frozenset[str]] = frozenset(
    {"", "na", "n/a", "n.a.", "null", "none", "nil", "-", "--", "#n/a", "#na", "nan", "\\n"}
)

ACCEPTED_DATE_FORMATS: Final[str] = "YYYY-MM-DD, YYYYMMDD, DD/MM/YYYY, DD-Mon-YYYY, DD Mon YYYY"
ACCEPTED_MONTH_FORMATS: Final[str] = "YYYY-MM, YYYY-MM-DD, MM/YYYY, YYYYMM, Mon-YY, Mon YYYY"

#: ISO 4217 active alphabetic codes. Held as data rather than validated by a
#: three-letter regex because plan.md §10.2 gates on "valid currency" and
#: ``XYZ`` matches a regex perfectly well.
ISO_4217_CODES: Final[frozenset[str]] = frozenset(
    [
        "AED",
        "AFN",
        "ALL",
        "AMD",
        "ANG",
        "AOA",
        "ARS",
        "AUD",
        "AWG",
        "AZN",
        "BAM",
        "BBD",
        "BDT",
        "BGN",
        "BHD",
        "BIF",
        "BMD",
        "BND",
        "BOB",
        "BOV",
        "BRL",
        "BSD",
        "BTN",
        "BWP",
        "BYN",
        "BZD",
        "CAD",
        "CDF",
        "CHE",
        "CHF",
        "CHW",
        "CLF",
        "CLP",
        "CNY",
        "COP",
        "COU",
        "CRC",
        "CUP",
        "CVE",
        "CZK",
        "DJF",
        "DKK",
        "DOP",
        "DZD",
        "EGP",
        "ERN",
        "ETB",
        "EUR",
        "FJD",
        "FKP",
        "GBP",
        "GEL",
        "GHS",
        "GIP",
        "GMD",
        "GNF",
        "GTQ",
        "GYD",
        "HKD",
        "HNL",
        "HTG",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "IQD",
        "IRR",
        "ISK",
        "JMD",
        "JOD",
        "JPY",
        "KES",
        "KGS",
        "KHR",
        "KMF",
        "KPW",
        "KRW",
        "KWD",
        "KYD",
        "KZT",
        "LAK",
        "LBP",
        "LKR",
        "LRD",
        "LSL",
        "LYD",
        "MAD",
        "MDL",
        "MGA",
        "MKD",
        "MMK",
        "MNT",
        "MOP",
        "MRU",
        "MUR",
        "MVR",
        "MWK",
        "MXN",
        "MXV",
        "MYR",
        "MZN",
        "NAD",
        "NGN",
        "NIO",
        "NOK",
        "NPR",
        "NZD",
        "OMR",
        "PAB",
        "PEN",
        "PGK",
        "PHP",
        "PKR",
        "PLN",
        "PYG",
        "QAR",
        "RON",
        "RSD",
        "RUB",
        "RWF",
        "SAR",
        "SBD",
        "SCR",
        "SDG",
        "SEK",
        "SGD",
        "SHP",
        "SLE",
        "SOS",
        "SRD",
        "SSP",
        "STN",
        "SVC",
        "SYP",
        "SZL",
        "THB",
        "TJS",
        "TMT",
        "TND",
        "TOP",
        "TRY",
        "TTD",
        "TWD",
        "TZS",
        "UAH",
        "UGX",
        "USD",
        "USN",
        "UYI",
        "UYU",
        "UYW",
        "UZS",
        "VED",
        "VES",
        "VND",
        "VUV",
        "WST",
        "XAF",
        "XCD",
        "XCG",
        "XDR",
        "XOF",
        "XPF",
        "YER",
        "ZAR",
        "ZMW",
        "ZWG",
    ]
)

_MONTH_NAMES: Final[Mapping[str, int]] = {
    name: index
    for index, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}

_TRUE_TOKENS: Final[frozenset[str]] = frozenset({"true", "t", "yes", "y", "1", "on", "checked"})
_FALSE_TOKENS: Final[frozenset[str]] = frozenset({"false", "f", "no", "n", "0", "off", "unchecked"})

_CURRENCY_SYMBOLS = re.compile(r"[$€£₹¥₨₽₩฿]")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_COMPACT_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_PARTS_DATE = re.compile(r"^(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{2,4})$")
_NAMED_DATE = re.compile(r"^(\d{1,2})[\s./\-]([A-Za-z]{3,9})[\s./\-](\d{2,4})$")
_NAMED_DATE_FIRST = re.compile(r"^([A-Za-z]{3,9})[\s./\-](\d{1,2})[,\s]+(\d{2,4})$")
_MONTH_ISO = re.compile(r"^(\d{4})[-/](\d{1,2})$")
_MONTH_COMPACT = re.compile(r"^(\d{4})(0[1-9]|1[0-2])$")
_MONTH_SLASH = re.compile(r"^(\d{1,2})[-/](\d{4})$")
_MONTH_NAMED = re.compile(r"^([A-Za-z]{3,9})[\s./\-]?(\d{2}|\d{4})$")
_MONTH_NAMED_LAST = re.compile(r"^(\d{4})[\s./\-]([A-Za-z]{3,9})$")

#: Excel's day-zero. Excel treats 1900 as a leap year, so its serials are offset
#: by two days from a naive 1900-01-01 epoch; 1899-12-30 absorbs that.
_EXCEL_EPOCH: Final[dt.date] = dt.date(1899, 12, 30)
_EXCEL_SERIAL_MAX: Final[int] = 2_958_465  # 9999-12-31


@dataclass(frozen=True, slots=True)
class CoercionOptions:
    """Per-source parsing preferences, saved alongside a column mapping."""

    date_order: DateOrder = DateOrder.AUTO
    #: Accept a bare number as an Excel date serial. Only applies to genuinely
    #: numeric cells (a CSV string of digits is never treated as a date).
    allow_excel_serial_dates: bool = True


DEFAULT_COERCION: Final[CoercionOptions] = CoercionOptions()


@dataclass(frozen=True, slots=True)
class Coerced:
    """Result of parsing one cell. Exactly one of ``value``/``code`` is meaningful."""

    value: Any = None
    code: IssueCode | None = None
    params: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.code is None


_OK_NULL: Final[Coerced] = Coerced(value=None)


def is_null_token(raw: object) -> bool:
    """True when the cell means "no value"."""
    if raw is None:
        return True
    if isinstance(raw, str):
        return raw.strip().lower() in NULL_TOKENS
    return False


# ===========================================================================
# Scalar parsers
# ===========================================================================


def _text(raw: object) -> str:
    return raw.strip() if isinstance(raw, str) else str(raw)


def parse_boolean(raw: object) -> Coerced:
    """Accept the true/false spellings real exports produce."""
    if isinstance(raw, bool):
        return Coerced(value=raw)
    if isinstance(raw, int | float | Decimal) and not isinstance(raw, bool):
        if raw in (0, 1):
            return Coerced(value=bool(raw))
        return Coerced(code=IssueCode.TYPE_INVALID_BOOLEAN, params={"value": raw})
    token = _text(raw).lower()
    if token in _TRUE_TOKENS:
        return Coerced(value=True)
    if token in _FALSE_TOKENS:
        return Coerced(value=False)
    return Coerced(code=IssueCode.TYPE_INVALID_BOOLEAN, params={"value": raw})


def _normalise_numeric_text(text: str) -> str | None:
    """Strip the decoration real financial exports carry.

    Handles ``(1,234.56)`` for negatives, currency symbols, non-breaking spaces
    and both separator conventions. When only commas are present the group sizes
    decide: ``1,234`` is one thousand two hundred and thirty-four, ``1,23`` is a
    European decimal.
    """
    # The three space characters below are deliberately different: U+00A0
    # (no-break), U+202F (narrow no-break) and U+0020.  Excel and European
    # locales each use one of them as a thousands separator, and a value that
    # keeps one is not a number.  ruff flags the look-alikes; they are the point.
    s = text.replace(" ", "").replace(" ", "").replace(" ", "").replace("'", "")  # noqa: RUF001
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    s = _CURRENCY_SYMBOLS.sub("", s)
    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("-"):
        negative, s = not negative, s[1:]
    if not s:
        return None
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        s = (
            s.replace(",", "")
            if s.rfind(".") > s.rfind(",")
            else s.replace(".", "").replace(",", ".")
        )
    elif has_comma:
        groups = s.split(",")
        tail_is_grouped = all(len(g) == 3 and g.isdigit() for g in groups[1:])
        s = s.replace(",", "") if tail_is_grouped else s.replace(",", ".")
    return f"-{s}" if negative else s


def parse_decimal(raw: object) -> Coerced:
    """Parse an exact decimal. Never returns a float - money is never binary."""
    if isinstance(raw, bool):
        return Coerced(code=IssueCode.TYPE_INVALID_DECIMAL, params={"value": raw})
    if isinstance(raw, Decimal):
        return Coerced(value=raw)
    if isinstance(raw, int):
        return Coerced(value=Decimal(raw))
    if isinstance(raw, float):
        # str() first: Decimal(0.1) would carry the binary artefact into storage.
        return Coerced(value=Decimal(str(raw)))
    cleaned = _normalise_numeric_text(_text(raw))
    if cleaned is None:
        return Coerced(code=IssueCode.TYPE_INVALID_DECIMAL, params={"value": raw})
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return Coerced(code=IssueCode.TYPE_INVALID_DECIMAL, params={"value": raw})
    if not value.is_finite():
        return Coerced(code=IssueCode.TYPE_INVALID_DECIMAL, params={"value": raw})
    return Coerced(value=value)


def parse_integer(raw: object) -> Coerced:
    """Parse a whole number. ``5.0`` is accepted, ``5.5`` is not."""
    if isinstance(raw, bool):
        return Coerced(code=IssueCode.TYPE_INVALID_INTEGER, params={"value": raw})
    if isinstance(raw, int):
        return Coerced(value=raw)
    decimal_result = parse_decimal(raw)
    if not decimal_result.ok:
        return Coerced(code=IssueCode.TYPE_INVALID_INTEGER, params={"value": raw})
    value: Decimal = decimal_result.value
    if value != value.to_integral_value():
        return Coerced(code=IssueCode.TYPE_INVALID_INTEGER, params={"value": raw})
    return Coerced(value=int(value))


def _two_digit_year(year: int) -> int:
    """POSIX pivot: 00-69 -> 2000s, 70-99 -> 1900s."""
    return 2000 + year if year <= 69 else 1900 + year


def _build_date(year: int, month: int, day: int, raw: object) -> Coerced:
    try:
        return Coerced(value=dt.date(year, month, day))
    except ValueError:
        return Coerced(
            code=IssueCode.TYPE_INVALID_DATE,
            params={"value": raw, "allowed": ACCEPTED_DATE_FORMATS},
        )


def parse_date(raw: object, options: CoercionOptions = DEFAULT_COERCION) -> Coerced:
    """Parse a calendar date, refusing genuinely ambiguous slash dates."""
    if isinstance(raw, dt.datetime):
        return Coerced(value=raw.date())
    if isinstance(raw, dt.date):
        return Coerced(value=raw)
    if isinstance(raw, bool):
        return Coerced(
            code=IssueCode.TYPE_INVALID_DATE,
            params={"value": raw, "allowed": ACCEPTED_DATE_FORMATS},
        )
    if isinstance(raw, int | float) and options.allow_excel_serial_dates:
        serial = int(raw)
        if 1 <= serial <= _EXCEL_SERIAL_MAX:
            return Coerced(value=_EXCEL_EPOCH + dt.timedelta(days=serial))
        return Coerced(
            code=IssueCode.TYPE_INVALID_DATE,
            params={"value": raw, "allowed": ACCEPTED_DATE_FORMATS},
        )

    text = _text(raw)
    invalid = Coerced(
        code=IssueCode.TYPE_INVALID_DATE, params={"value": raw, "allowed": ACCEPTED_DATE_FORMATS}
    )
    if not text:
        return invalid

    # A spreadsheet that stringified a datetime keeps the ISO prefix.
    head = (
        text.split("T")[0].split(" ")[0]
        if _ISO_DATE.match(text.split("T")[0].split(" ")[0])
        else text
    )

    if (m := _ISO_DATE.match(head)) is not None:
        return _build_date(int(m[1]), int(m[2]), int(m[3]), raw)
    if (m := _COMPACT_DATE.match(text)) is not None:
        return _build_date(int(m[1]), int(m[2]), int(m[3]), raw)
    if (m := _NAMED_DATE.match(text)) is not None:
        month = _MONTH_NAMES.get(m[2].lower())
        if month is None:
            return invalid
        year = int(m[3])
        return _build_date(year if len(m[3]) == 4 else _two_digit_year(year), month, int(m[1]), raw)
    if (m := _NAMED_DATE_FIRST.match(text)) is not None:
        month = _MONTH_NAMES.get(m[1].lower())
        if month is None:
            return invalid
        year = int(m[3])
        return _build_date(year if len(m[3]) == 4 else _two_digit_year(year), month, int(m[2]), raw)

    if (m := _PARTS_DATE.match(text)) is not None:
        first, second, third = int(m[1]), int(m[2]), int(m[3])
        if len(m[1]) == 4:  # unambiguous Y-M-D with a non-hyphen separator
            return _build_date(first, second, third, raw)
        year = third if len(m[3]) == 4 else _two_digit_year(third)
        if options.date_order is DateOrder.ISO:
            return invalid
        if options.date_order is DateOrder.DMY:
            return _build_date(year, second, first, raw)
        if options.date_order is DateOrder.MDY:
            return _build_date(year, first, second, raw)
        # AUTO: accept only when the value speaks for itself.
        if first > 12 and second <= 12:
            return _build_date(year, second, first, raw)
        if second > 12 and first <= 12:
            return _build_date(year, first, second, raw)
        if first <= 12 and second <= 12:
            return Coerced(code=IssueCode.TYPE_AMBIGUOUS_DATE, params={"value": raw})
        return invalid
    return invalid


def parse_month(raw: object, options: CoercionOptions = DEFAULT_COERCION) -> Coerced:
    """Parse a month-grain period, normalised to the first day of that month."""
    if isinstance(raw, dt.datetime):
        return Coerced(value=dt.date(raw.year, raw.month, 1))
    if isinstance(raw, dt.date):
        return Coerced(value=dt.date(raw.year, raw.month, 1))
    invalid = Coerced(
        code=IssueCode.TYPE_INVALID_MONTH, params={"value": raw, "allowed": ACCEPTED_MONTH_FORMATS}
    )
    if isinstance(raw, bool):
        return invalid
    text = str(int(raw)) if isinstance(raw, int | float) else _text(raw)
    if not text:
        return invalid

    if (m := _MONTH_ISO.match(text)) is not None:
        return _to_month(int(m[1]), int(m[2]), raw)
    if (m := _MONTH_COMPACT.match(text)) is not None:
        return _to_month(int(m[1]), int(m[2]), raw)
    if (m := _MONTH_SLASH.match(text)) is not None:
        return _to_month(int(m[2]), int(m[1]), raw)
    if (m := _MONTH_NAMED.match(text)) is not None:
        month = _MONTH_NAMES.get(m[1].lower())
        if month is not None:
            year = int(m[2])
            return _to_month(year if len(m[2]) == 4 else _two_digit_year(year), month, raw)
    if (m := _MONTH_NAMED_LAST.match(text)) is not None:
        month = _MONTH_NAMES.get(m[2].lower())
        if month is not None:
            return _to_month(int(m[1]), month, raw)

    # Fall back to full-date parsing: a spreadsheet routinely rewrites a month
    # cell as a whole date, and truncating is the only sane reading.
    as_date = parse_date(raw, options)
    if as_date.ok:
        value: dt.date = as_date.value
        return Coerced(value=dt.date(value.year, value.month, 1))
    if as_date.code is IssueCode.TYPE_AMBIGUOUS_DATE:
        return Coerced(code=IssueCode.TYPE_AMBIGUOUS_DATE, params={"value": raw})
    return invalid


def _to_month(year: int, month: int, raw: object) -> Coerced:
    if not 1 <= month <= 12 or not 1 <= year <= 9999:
        return Coerced(
            code=IssueCode.TYPE_INVALID_MONTH,
            params={"value": raw, "allowed": ACCEPTED_MONTH_FORMATS},
        )
    return Coerced(value=dt.date(year, month, 1))


def parse_currency_code(raw: object) -> Coerced:
    """Validate against the real ISO 4217 list, not a three-letter regex."""
    token = _text(raw).upper()
    if token in ISO_4217_CODES:
        return Coerced(value=token)
    return Coerced(code=IssueCode.TYPE_INVALID_CURRENCY_CODE, params={"value": raw})


def _parse_enum(raw: object, spec: FieldSpec) -> Coerced:
    """Match an enum value case-insensitively, tolerating spaces and hyphens."""
    assert spec.enum_ref is not None  # guaranteed by FieldSpec.__post_init__
    token = _text(raw)
    folded = re.sub(r"[^0-9a-z]+", "_", token.strip().lower()).strip("_")
    for candidate in spec.enum_ref:
        if folded == candidate.value.lower():
            return Coerced(value=candidate.value)
    return Coerced(
        code=IssueCode.VALUE_NOT_IN_ENUM,
        params={"value": raw, "allowed": ", ".join(spec.allowed_values)},
    )


def _check_decimal_shape(value: Decimal, spec: FieldSpec) -> Coerced | None:
    """Enforce declared precision/scale. Money is never silently rounded."""
    exponent = value.as_tuple().exponent
    scale = -int(exponent) if isinstance(exponent, int) and exponent < 0 else 0
    if spec.scale is not None and scale > spec.scale:
        return Coerced(code=IssueCode.TYPE_DECIMAL_SCALE_EXCEEDED, params={"expected": spec.scale})
    digits = len(value.as_tuple().digits)
    significant = max(digits, scale)
    if spec.precision is not None and significant > spec.precision:
        return Coerced(
            code=IssueCode.TYPE_DECIMAL_PRECISION_EXCEEDED, params={"expected": spec.precision}
        )
    return None


def coerce_value(
    spec: FieldSpec, raw: object, options: CoercionOptions = DEFAULT_COERCION
) -> Coerced:
    """Parse one cell against one :class:`FieldSpec`.

    Nullability and range are *not* checked here - that is ``validators.py``'s
    job - so that a blank required cell is reported as ``VALUE_REQUIRED_MISSING``
    rather than as a type error, which is what the person fixing the file needs
    to read.
    """
    if is_null_token(raw):
        return _OK_NULL
    match spec.dtype:
        case DType.STRING:
            text = _text(raw)
            return Coerced(value=text) if text else _OK_NULL
        case DType.INTEGER:
            return parse_integer(raw)
        case DType.DECIMAL:
            result = parse_decimal(raw)
            if not result.ok:
                return result
            shape_problem = _check_decimal_shape(result.value, spec)
            return shape_problem if shape_problem is not None else result
        case DType.BOOLEAN:
            return parse_boolean(raw)
        case DType.DATE:
            return parse_date(raw, options)
        case DType.MONTH:
            return parse_month(raw, options)
        case DType.ENUM:
            return _parse_enum(raw, spec)
        case DType.CURRENCY_CODE:
            return parse_currency_code(raw)
    raise AssertionError(f"unhandled dtype {spec.dtype}")  # pragma: no cover
