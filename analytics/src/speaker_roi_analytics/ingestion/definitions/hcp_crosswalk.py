"""``HCP_CROSSWALK`` — source identifier to master identifier mapping (plan.md §10.1, §9.4).

This is the join that makes the whole platform possible.  An Rx row, an
attendance row and a marketing touch describe the *same* prescriber only because
this file says the CRM's ``CRM-0009182`` and the Rx panel's ``RX-77213`` are one
person.  If that mapping is wrong, an attendee's own prescriptions land in the
control arm and the measured lift is arithmetic on noise.

Two properties are therefore enforced hard:

* **Unambiguity.** One ``(source_system, source_hcp_id)`` may resolve to only
  one ``master_hcp_id`` within any overlapping effective window.  Two candidates
  are quarantined for steward review, never auto-picked
  (:func:`~speaker_roi_analytics.ingestion.validators.unambiguous_crosswalk`).
* **Declared confidence.** A probabilistic match below the review threshold is
  quarantined even when it is the only candidate.  Plan.md §9.4 requires a
  review queue rather than a silent accept, because a wrong match is invisible
  downstream — it just looks like a prescriber who behaved oddly.

Ranges are half-open ``[effective_from, effective_to)``, so a mapping can be
superseded on a given day without a one-day gap or a one-day overlap.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from speaker_roi_analytics.ingestion.contracts import (
    Cadence,
    DatasetContract,
    DType,
    FieldSpec,
    ReferenceSpec,
    ReferenceTarget,
    RowRule,
    RowView,
    RuleContext,
    RuleViolation,
)
from speaker_roi_analytics.ingestion.definitions._common import (
    note_field,
    source_hcp_id_field,
    source_system_field,
)
from speaker_roi_analytics.ingestion.issues import IssueCode
from speaker_roi_analytics.ingestion.validators import (
    effective_range_half_open,
    unambiguous_crosswalk,
)
from speaker_roi_core.enums import (
    DatasetType,
    IdentityMatchStatus,
    IssueSeverity,
    MatchMethod,
)

__all__ = ["CONTRACT"]


def _probabilistic_match_needs_review() -> RowRule:
    """A low-confidence probabilistic match goes to the review queue, not the warehouse.

    ``EXACT_SOURCE_ID`` and ``STEWARD_DECISION`` matches are trusted at face
    value: the first is deterministic and the second already had a human in the
    loop.  ``PROBABILISTIC`` matches below
    :attr:`RuleOptions.probabilistic_review_threshold` are quarantined — plan.md
    §9.4 requires ambiguous identity to reach a queue rather than the fact
    tables, and a fuzzy name match at 0.6 confidence is exactly the case that
    silently merges two different prescribers.
    """

    def _check(row: RowView, ctx: RuleContext) -> Sequence[RuleViolation]:
        method = row.get("match_method")
        if method is None:
            return ()
        if str(method).strip().upper() != MatchMethod.PROBABILISTIC.value:
            return ()
        confidence = row.get("confidence")
        threshold = ctx.options.probabilistic_review_threshold
        if isinstance(confidence, Decimal) and confidence >= threshold:
            return ()
        return (
            RuleViolation(
                code=IssueCode.RULE_CONFIDENCE_BELOW_REVIEW_THRESHOLD,
                field_name="confidence",
                severity=IssueSeverity.QUARANTINE,
                params={"threshold": str(threshold), "method": MatchMethod.PROBABILISTIC.value},
            ),
        )

    return RowRule(
        name="probabilistic_match_needs_review",
        code=IssueCode.RULE_CONFIDENCE_BELOW_REVIEW_THRESHOLD,
        description=(
            "A PROBABILISTIC match must carry a confidence at or above the review threshold; "
            "anything lower is quarantined for a steward to decide."
        ),
        fields=("match_method", "confidence"),
        check=_check,
    )


CONTRACT = DatasetContract(
    dataset_type=DatasetType.HCP_CROSSWALK,
    version="1.0.0",
    title="HCP Identity Crosswalk",
    description=(
        "Maps each source system's HCP identifier onto the platform's master identifier, "
        "with the method, confidence and effective window of the mapping."
    ),
    owner="Data Management / Master Data",
    cadence=Cadence.AD_HOC,
    natural_key=("source_system", "source_hcp_id", "master_hcp_id", "effective_from"),
    duplicate_policy="REJECT",
    fields=(
        source_system_field(),
        source_hcp_id_field(
            description="Identifier as it appears in the source system named above."
        ),
        FieldSpec(
            name="master_hcp_id",
            title="Master HCP ID",
            dtype=DType.STRING,
            description=(
                "The platform-wide identifier this source identifier resolves to. Every dataset "
                "is joined on this value after resolution."
            ),
            max_length=80,
            example="MST-0001923",
            pii=True,
            aliases=(
                "mdm_id",
                "golden_id",
                "master_id",
                "resolved_hcp_id",
                "universal_hcp_id",
                "enterprise_hcp_id",
            ),
        ),
        FieldSpec(
            name="match_method",
            title="Match Method",
            dtype=DType.ENUM,
            description=(
                "How the mapping was established. The method determines how much scrutiny the "
                "row receives: probabilistic matches are held to a confidence threshold."
            ),
            enum_ref=MatchMethod,
            example="EXACT_SOURCE_ID",
            aliases=(
                "method",
                "match_type",
                "matching_method",
                "resolution_method",
                "MATCH_METHOD",
            ),
        ),
        FieldSpec(
            name="confidence",
            title="Confidence",
            dtype=DType.DECIMAL,
            description=(
                "Match confidence between 0 and 1. Required for probabilistic matches; "
                "deterministic matches may leave it blank or set it to 1."
            ),
            required=False,
            nullable=True,
            precision=5,
            scale=4,
            minimum=Decimal("0"),
            maximum=Decimal("1"),
            example="1.0000",
            aliases=("match_confidence", "score", "match_score", "probability", "confidence_score"),
        ),
        FieldSpec(
            name="status",
            title="Match Status",
            dtype=DType.ENUM,
            description=(
                "Current disposition of the mapping. AMBIGUOUS and REJECTED rows are accepted so "
                "the review queue has a record; they are never used to join facts."
            ),
            enum_ref=IdentityMatchStatus,
            example="MATCHED",
            aliases=("match_status", "identity_status", "resolution_status", "state"),
        ),
        FieldSpec(
            name="effective_from",
            title="Effective From",
            dtype=DType.DATE,
            description="First day this mapping applies. Half-open range: [effective_from, effective_to).",
            example="2025-01-01",
            aliases=("valid_from", "start_date", "from_date", "effective_start", "EFFECTIVE_FROM"),
        ),
        FieldSpec(
            name="effective_to",
            title="Effective To",
            dtype=DType.DATE,
            description=(
                "First day this mapping no longer applies (exclusive). Leave blank for the "
                "mapping currently in force."
            ),
            required=False,
            nullable=True,
            example="",
            aliases=("valid_to", "end_date", "to_date", "effective_end", "EFFECTIVE_TO"),
        ),
        FieldSpec(
            name="resolved_by",
            title="Resolved By",
            dtype=DType.STRING,
            description=(
                "Who or what established the mapping — a steward's username or the name of the "
                "matching job. Required for STEWARD_DECISION rows so the decision is auditable."
            ),
            required=False,
            nullable=True,
            max_length=120,
            example="mdm.batch.v3",
            aliases=("resolver", "matched_by", "reviewed_by", "steward", "owner"),
        ),
        note_field(
            description="Optional steward note explaining a non-obvious mapping. Never used in matching."
        ),
    ),
    references=(
        ReferenceSpec(
            field_name="source_system",
            target=ReferenceTarget.SOURCE_SYSTEM,
            description="Must be a source system registered for this tenant.",
        ),
    ),
    row_rules=(
        effective_range_half_open(),
        _probabilistic_match_needs_review(),
    ),
    frame_rules=(unambiguous_crosswalk(),),
    sample_rows=(
        {
            "source_system": "CRM",
            "source_hcp_id": "CRM-0009182",
            "master_hcp_id": "MST-0001923",
            "match_method": "EXACT_SOURCE_ID",
            "confidence": "1.0000",
            "status": "MATCHED",
            "effective_from": "2025-01-01",
            "effective_to": "",
            "resolved_by": "mdm.batch.v3",
            "note": "",
        },
        {
            "source_system": "RXPANEL",
            "source_hcp_id": "RX-77213",
            "master_hcp_id": "MST-0001923",
            "match_method": "DETERMINISTIC_RULE",
            "confidence": "0.9900",
            "status": "MATCHED",
            "effective_from": "2025-01-01",
            "effective_to": "",
            "resolved_by": "mdm.batch.v3",
            "note": "Matched on registration number and city.",
        },
        {
            "source_system": "EVENTTOOL",
            "source_hcp_id": "ET-55210",
            "master_hcp_id": "MST-0004410",
            "match_method": "STEWARD_DECISION",
            "confidence": "1.0000",
            "status": "MANUALLY_MATCHED",
            "effective_from": "2025-06-01",
            "effective_to": "",
            "resolved_by": "a.sharma",
            "note": "Duplicate registration merged after review.",
        },
        {
            "source_system": "RXPANEL",
            "source_hcp_id": "RX-90881",
            "master_hcp_id": "MST-0007712",
            "match_method": "PROBABILISTIC",
            "confidence": "0.9100",
            "status": "MATCHED",
            "effective_from": "2025-03-01",
            "effective_to": "2026-01-01",
            "resolved_by": "mdm.batch.v3",
            "note": "Superseded by a steward decision from 2026-01-01.",
        },
    ),
    notes=(
        "A source identifier that maps to two different master identifiers over overlapping "
        "windows is quarantined, not resolved by rule. Ambiguous identity is a review task.",
        "Ranges are half-open: set the old row's effective_to to the same date as the new "
        "row's effective_from to supersede a mapping cleanly.",
    ),
)
