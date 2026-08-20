"""Versioned data-intake contracts for the HCP Speaker Program ROI platform.

This package is the schema authority for every CSV/XLSX upload the platform
accepts (plan.md §10).  It owns four things and nothing else:

1. **The contracts** — a declarative, versioned description of each of the
   twelve datasets in plan.md §10.1: fields, types, enums, natural keys,
   duplicate policy, cross-row rules and the columns that must never appear.
2. **The parsers** — chunked CSV and XLSX readers that preserve the original
   1-based spreadsheet row number of every record so an error report can point
   the uploader at the exact line to fix.
3. **The validator** — a pure function from (file, contract) to a
   :class:`~speaker_roi_analytics.ingestion.validate.ValidationOutcome`, with
   per-row dispositions and a closed set of documented error codes.
4. **The artifacts** — downloadable templates, JSON Schemas and the data
   dictionary, all generated from the contracts so they cannot drift.

Deliberate non-dependencies (plan.md §17): nothing here imports FastAPI,
SQLAlchemy, or any database driver.  Reference lookups ("does this brand code
exist for this tenant?") and taxonomy lookups are supplied by the caller as
injected resolver callables, which keeps the whole package unit-testable with
plain dictionaries and lets the same code run inside an API request, a batch
job or a notebook.

Typical use::

    from speaker_roi_analytics.ingestion import get_contract, validate_file
    from speaker_roi_core.enums import DatasetType

    contract = get_contract(DatasetType.RX_MONTHLY)
    outcome = validate_file(path, contract)
    if outcome.is_loadable:
        load(outcome.accepted_frame)
"""

from __future__ import annotations

from .contracts import (
    Cadence,
    DatasetContract,
    DType,
    DuplicatePolicy,
    FieldSpec,
    ForbiddenHeaderPattern,
    ReferenceSpec,
    ReferenceTarget,
    RuleContext,
    RuleOptions,
    ScopeKind,
    all_contracts,
    contract_registry,
    get_contract,
    normalise_header,
)
from .issues import (
    ISSUE_CATALOGUE,
    Gate,
    Issue,
    IssueCategory,
    IssueCode,
    IssueDefinition,
    make_issue,
)
from .mapping import (
    ColumnMapping,
    MappingCandidate,
    MappingSuggestion,
    MappingThresholds,
    check_forbidden_headers,
    resolve_mapping,
    suggest_mapping,
)
from .profiling import ColumnProfile, FileProfile, ProfileOptions, profile_file
from .readers import (
    ReaderError,
    ReaderLimits,
    ReadPlan,
    RowSource,
    SourceRow,
    open_row_source,
)
from .validate import (
    ReferenceResolver,
    RowDisposition,
    RowResult,
    TaxonomyResolver,
    ValidationLimits,
    ValidationOutcome,
    ValidationSummary,
    validate_file,
    validate_rows,
)

__all__ = [
    "ISSUE_CATALOGUE",
    "Cadence",
    "ColumnMapping",
    "ColumnProfile",
    "DType",
    "DatasetContract",
    "DuplicatePolicy",
    "FieldSpec",
    "FileProfile",
    "ForbiddenHeaderPattern",
    "Gate",
    "Issue",
    "IssueCategory",
    "IssueCode",
    "IssueDefinition",
    "MappingCandidate",
    "MappingSuggestion",
    "MappingThresholds",
    "ProfileOptions",
    "ReadPlan",
    "ReaderError",
    "ReaderLimits",
    "ReferenceResolver",
    "ReferenceSpec",
    "ReferenceTarget",
    "RowDisposition",
    "RowResult",
    "RowSource",
    "RuleContext",
    "RuleOptions",
    "ScopeKind",
    "SourceRow",
    "TaxonomyResolver",
    "ValidationLimits",
    "ValidationOutcome",
    "ValidationSummary",
    "all_contracts",
    "check_forbidden_headers",
    "contract_registry",
    "get_contract",
    "make_issue",
    "normalise_header",
    "open_row_source",
    "profile_file",
    "resolve_mapping",
    "suggest_mapping",
    "validate_file",
    "validate_rows",
]
