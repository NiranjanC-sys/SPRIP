"""Shared column types.

Two rules are enforced here rather than left to each model author:

1. **Enums are native PostgreSQL types, created once by the migration.** Every
   ``pg_enum()`` column is declared ``create_type=False`` so SQLAlchemy never
   tries to ``CREATE TYPE`` on the fly. The single authority for which types
   exist is ``speaker_roi_core.enums.PG_ENUMS``, which the initial migration
   iterates. A model referencing an enum missing from that tuple fails loudly at
   migration time instead of silently at first insert.

2. **Money is never a float.** plan.md §9 requires ``NUMERIC`` amounts paired
   with an ISO-4217 code. ``Money`` fixes the precision/scale so a rounding
   difference cannot appear between the API, the optimizer and the warehouse.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Numeric, String
from sqlalchemy.dialects.postgresql import JSONB

from speaker_roi_core.enums import StrEnumBase

#: Schema that owns every enum type. Keeping them in one schema means the
#: migration's search_path handling is trivial and `pg_dump` ordering is stable.
ENUM_SCHEMA = "core"


def pg_enum(enum_cls: type[StrEnumBase], **kwargs: Any) -> SAEnum:
    """Column type for a controlled vocabulary.

    ``values_callable`` makes SQLAlchemy persist the enum *value* rather than the
    Python member name. They are identical for our ``StrEnum`` vocabularies, but
    being explicit means renaming a member without changing its value is a pure
    code change with no migration.
    """
    return SAEnum(
        enum_cls,
        name=_type_name(enum_cls),
        schema=ENUM_SCHEMA,
        native_enum=True,
        create_type=False,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
        **kwargs,
    )


def _type_name(enum_cls: type[StrEnumBase]) -> str:
    """``EvidenceGrade`` -> ``evidence_grade``."""
    name = enum_cls.__name__
    out: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index > 0 and not name[index - 1].isupper():
            out.append("_")
        out.append(char.lower())
    return "".join(out)


#: Currency amounts. 18 digits with 2 decimals covers every realistic program
#: budget while staying inside a 64-bit integer once scaled.
Money = Numeric(18, 2)

#: Model coefficients, standard errors and indices. 6 decimals is enough for
#: reproducible statistics and avoids the "0.30000000000000004" artefacts that
#: make an analyst distrust the whole report.
Measure = Numeric(18, 6)

#: Probabilities, shares and coverage factors, constrained to [0, 1] by a check
#: constraint at each use site.
Fraction = Numeric(9, 6)

#: Counts of prescriptions. NUMERIC rather than INTEGER because an *estimated*
#: incremental count is fractional by nature.
Quantity = Numeric(18, 4)

#: ISO-4217 alphabetic code.
Currency = String(3)

#: Hex digest of SHA-256.
Sha256 = String(64)

__all__ = [
    "JSONB",
    "Currency",
    "Fraction",
    "Measure",
    "Money",
    "Quantity",
    "Sha256",
    "pg_enum",
]
