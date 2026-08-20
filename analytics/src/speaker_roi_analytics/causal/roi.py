"""Money: turning an incremental-script interval into contribution and ROI.

This module is deliberately the least clever one in the package. Every input is
supplied and approved by Finance, nothing is inferred, and no number here is fitted to
anything. The reason is that the failure mode is asymmetric: a wrong causal estimate is
a bad analysis, but a wrong contribution-per-script is a bad *promise*, and it will be
quoted in a budget meeting long after anyone remembers where it came from.

Four rules the implementation enforces rather than documents
------------------------------------------------------------
**Margin is never inferred.** Not from the brand name, not from a list price, not from
an LLM, not from a comparable product. Either Finance supplied a net contribution per
incremental script for this tenant, brand and period, or there is no ROI. plan.md §12.5
says this and :func:`compute_roi` refuses rather than guesses.

**The assumption is chosen by the event's date, not today's.** An effective-dated
assumption exists so that a program run last March is valued at last March's margin. If
selection used the current date, republishing an old analysis would silently restate its
ROI, and two reports of the same event would disagree with no visible cause.

**The interval that propagates is the bias-bounded one.** Not the bootstrap interval.
The bootstrap describes sampling error alone, and on observational program data that is
the smaller uncertainty - see :mod:`.sensitivity`. Propagating the narrow interval would
produce a confident-looking ROI range whose true coverage nobody knows, which is the
single most dangerous artefact this system could emit.

**Magnitude is not published below MODERATE.** A ``DIRECTIONAL`` grade says the sign is
the only trustworthy part of the estimate. Multiplying a magnitude nobody should quote by
a margin does not make it quotable, so :func:`compute_roi` returns a result marked
unpublishable with the reason attached. plan.md's acceptance criterion is that
unsupported events publish no ROI; this is where that is true in code rather than in a
convention someone can forget.

What "fully loaded" has to mean
------------------------------
The cost side is as easy to get wrong as the benefit side, and in the same direction. A
speaker program's honoraria are the visible cost and often less than half the real one:
venue, catering, travel, agency fees, materials, and internal time all belong in the
denominator. :class:`EventCost` therefore takes components and sums them rather than
taking a single number, so an omission is visible as a zero in a named field instead of
being invisible in a total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import structlog

from speaker_roi_core.enums import EvidenceGrade

from .evidence import EvidenceReport

__all__ = [
    "PUBLISHABLE_GRADES",
    "ContributionComponents",
    "EventCost",
    "FinanceAssumption",
    "RoiResult",
    "RoiScenario",
    "compute_roi",
]

_LOG = structlog.get_logger(__name__)

#: Grades whose magnitude may be turned into money. ``DIRECTIONAL`` is deliberately
#: absent: see the module docstring on why a sign is not a magnitude.
PUBLISHABLE_GRADES: frozenset[EvidenceGrade] = frozenset(
    {EvidenceGrade.STRONG, EvidenceGrade.MODERATE}
)


@dataclass(frozen=True, slots=True)
class ContributionComponents:
    """Finance's component model for contribution per incremental script.

    Offered as an alternative to a single approved figure because some finance teams
    hold price and margin separately and would otherwise maintain a derived number by
    hand. Both routes are approved the same way and stored under the same version.
    """

    #: Net revenue per script after rebates and channel discounts, in
    #: :attr:`FinanceAssumption.currency`. Net, not list: list price times margin
    #: double-counts the discount.
    net_revenue_per_script: float
    #: Gross contribution margin as a fraction, not a percentage. 0.62, never 62.
    gross_margin_fraction: float
    #: Additional scripts Finance expects each incremental new prescription to generate
    #: through refills. 1.0 means "count the new prescription only". Supplied by
    #: Finance, never modelled here: a refill multiplier estimated from the same
    #: prescribing panel the causal estimate came from would double-count the effect.
    persistency_multiplier: float = 1.0

    def per_script(self) -> float:
        return (
            self.net_revenue_per_script * self.gross_margin_fraction * self.persistency_multiplier
        )

    def valid(self) -> str:
        """Empty string when usable, otherwise why not."""
        if not np.isfinite(self.net_revenue_per_script) or self.net_revenue_per_script <= 0:
            return "net revenue per script must be a positive number"
        if not 0.0 < self.gross_margin_fraction <= 1.0:
            return (
                f"gross margin must be a fraction between 0 and 1, got "
                f"{self.gross_margin_fraction} - a percentage was probably entered"
            )
        if not np.isfinite(self.persistency_multiplier) or self.persistency_multiplier < 1.0:
            return "persistency multiplier must be at least 1.0"
        return ""


@dataclass(frozen=True, slots=True)
class FinanceAssumption:
    """One effective-dated, approved monetary assumption.

    Either :attr:`contribution_per_script` or :attr:`components` is supplied. If both
    are, the direct figure wins and a warning is raised: a stored pair that disagrees is
    a data-entry error, and silently preferring one without saying so is how a
    reconciliation meeting becomes a mystery.
    """

    version_id: str
    tenant_id: str
    brand_id: str
    currency: str
    effective_from: date
    #: Exclusive. ``None`` means still in force.
    effective_to: date | None = None
    approved: bool = False
    approved_by: str = ""
    contribution_per_script: float | None = None
    components: ContributionComponents | None = None

    def covers(self, when: date) -> bool:
        return self.effective_from <= when and (
            self.effective_to is None or when < self.effective_to
        )

    def per_script(self) -> float:
        if self.contribution_per_script is not None:
            return float(self.contribution_per_script)
        return self.components.per_script() if self.components else float("nan")

    def problem(self) -> str:
        """Empty string when this assumption may be used, otherwise why not."""
        if not self.approved:
            return f"finance assumption {self.version_id} has not been approved"
        if self.contribution_per_script is None and self.components is None:
            return f"finance assumption {self.version_id} carries no contribution figure"
        if self.contribution_per_script is not None:
            if not np.isfinite(self.contribution_per_script) or self.contribution_per_script <= 0.0:
                return "approved contribution per script must be a positive number"
        elif self.components is not None and (reason := self.components.valid()):
            return reason
        if not self.currency:
            return f"finance assumption {self.version_id} has no currency"
        return ""


@dataclass(frozen=True, slots=True)
class EventCost:
    """Fully loaded cost of one event, by component.

    Components rather than a total so that a missing category is visible. ``total`` is
    the sum; there is deliberately no way to supply a total that disagrees with its
    parts, because that is a reconciliation problem waiting to happen.
    """

    event_id: str
    currency: str
    honoraria: float = 0.0
    venue_and_catering: float = 0.0
    travel_and_accommodation: float = 0.0
    agency_and_production: float = 0.0
    materials: float = 0.0
    internal_time: float = 0.0
    other: float = 0.0
    approved: bool = False

    @property
    def total(self) -> float:
        return float(
            self.honoraria
            + self.venue_and_catering
            + self.travel_and_accommodation
            + self.agency_and_production
            + self.materials
            + self.internal_time
            + self.other
        )

    def problem(self) -> str:
        if not self.approved:
            return f"cost for event {self.event_id} has not been approved"
        parts = (
            self.honoraria,
            self.venue_and_catering,
            self.travel_and_accommodation,
            self.agency_and_production,
            self.materials,
            self.internal_time,
            self.other,
        )
        if any(not np.isfinite(value) or value < 0 for value in parts):
            return "cost components must be non-negative numbers"
        if self.total <= 0:
            return f"cost for event {self.event_id} totals zero, so no ratio can be formed"
        if not self.currency:
            return f"cost for event {self.event_id} has no currency"
        return ""


@dataclass(frozen=True, slots=True)
class RoiScenario:
    """One point on the propagated interval."""

    #: ``conservative`` | ``base`` | ``optimistic``.
    name: str
    incremental_scripts: float
    contribution: float
    net_benefit: float
    #: Contribution divided by cost. Above 1.0 the program paid for itself.
    benefit_cost_ratio: float
    #: Net benefit divided by cost, as a fraction. ``0.4`` is a 40% return.
    net_roi: float


@dataclass(frozen=True, slots=True)
class RoiResult:
    """The three scenarios, or an explained refusal."""

    publishable: bool
    #: Why not, when ``publishable`` is False. The API returns this verbatim; it is
    #: written to be shown to a commercial user, not parsed.
    refusal_reason: str
    currency: str
    #: Which approved assumption produced these numbers, for the audit trail. A stored
    #: ROI row without this is unreproducible.
    finance_version_id: str
    contribution_per_script: float
    cost_total: float
    grade: EvidenceGrade
    scenarios: tuple[RoiScenario, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def scenario(self, name: str) -> RoiScenario | None:
        return next((s for s in self.scenarios if s.name == name), None)


def _refuse(reason: str, grade: EvidenceGrade, currency: str = "") -> RoiResult:
    _LOG.info("causal.roi.refused", reason=reason, grade=grade.value)
    return RoiResult(
        publishable=False,
        refusal_reason=reason,
        currency=currency,
        finance_version_id="",
        contribution_per_script=float("nan"),
        cost_total=float("nan"),
        grade=grade,
    )


def select_assumption(
    assumptions: tuple[FinanceAssumption, ...],
    tenant_id: str,
    brand_id: str,
    event_date: date,
) -> tuple[FinanceAssumption | None, str]:
    """The approved assumption in force for this tenant, brand and event date.

    Returns ``(assumption, problem)``. When two approved versions overlap the event
    date the later ``effective_from`` wins and a problem string is *not* raised - a
    restatement legitimately supersedes an earlier version for the same period, and
    refusing would block every tenant who has ever corrected a margin. The chosen
    version id is recorded on the result, so which one was used is never in doubt.
    """
    candidates = [
        assumption
        for assumption in assumptions
        if assumption.tenant_id == tenant_id
        and assumption.brand_id == brand_id
        and assumption.covers(event_date)
    ]
    if not candidates:
        return None, (
            f"no finance assumption is in force for brand {brand_id} on "
            f"{event_date.isoformat()}, so contribution cannot be computed"
        )
    approved = [a for a in candidates if a.approved]
    if not approved:
        return None, (
            f"the finance assumption covering {event_date.isoformat()} is not approved, "
            "so it cannot be used to publish ROI"
        )
    chosen = max(approved, key=lambda a: (a.effective_from, a.version_id))
    return chosen, chosen.problem()


def compute_roi(
    evidence: EvidenceReport,
    incremental_scripts: float,
    assumptions: tuple[FinanceAssumption, ...],
    cost: EventCost,
    *,
    tenant_id: str,
    brand_id: str,
    event_date: date,
) -> RoiResult:
    """Contribution, benefit-cost ratio and net ROI across the propagated interval.

    ``incremental_scripts`` is the point estimate; the interval comes from
    :attr:`~.evidence.EvidenceReport.interval_low` and ``interval_high``, which is the
    bias-bounded range rather than the bootstrap one. Refuses - rather than returning
    zeros - when the grade is too low, the finance version is missing or unapproved, the
    cost is missing or unapproved, or the currencies disagree.
    """
    grade = evidence.grade
    if grade not in PUBLISHABLE_GRADES:
        detail = evidence.caps[0] if evidence.caps else "the evidence does not support a magnitude"
        return _refuse(
            f"evidence is graded {grade.value}, so no financial figure is published: {detail}",
            grade,
        )

    assumption, problem = select_assumption(assumptions, tenant_id, brand_id, event_date)
    if assumption is None or problem:
        return _refuse(problem or "no usable finance assumption", grade)
    if reason := cost.problem():
        return _refuse(reason, grade, assumption.currency)
    if cost.currency != assumption.currency:
        return _refuse(
            f"event cost is in {cost.currency} but the finance assumption is in "
            f"{assumption.currency}; ROI across currencies is not computed here",
            grade,
            assumption.currency,
        )

    per_script = assumption.per_script()
    if not np.isfinite(per_script) or per_script <= 0:
        return _refuse(
            f"finance assumption {assumption.version_id} does not resolve to a positive "
            "contribution per script",
            grade,
            assumption.currency,
        )

    warnings: list[str] = []
    if assumption.contribution_per_script is not None and assumption.components is not None:
        warnings.append(
            f"finance assumption {assumption.version_id} carries both a direct "
            "contribution and a component model; the direct figure was used"
        )

    total = cost.total
    points = (
        ("conservative", evidence.interval_low),
        ("base", incremental_scripts),
        ("optimistic", evidence.interval_high),
    )
    scenarios: list[RoiScenario] = []
    for name, scripts in points:
        if not np.isfinite(scripts):
            warnings.append(f"the {name} scenario has no interval bound and was omitted")
            continue
        contribution = float(scripts) * per_script
        net = contribution - total
        scenarios.append(
            RoiScenario(
                name=name,
                incremental_scripts=float(scripts),
                contribution=contribution,
                net_benefit=net,
                benefit_cost_ratio=contribution / total,
                net_roi=net / total,
            )
        )

    if not any(s.name == "base" for s in scenarios):
        return _refuse(
            "the incremental script estimate is not a finite number, so no contribution "
            "can be computed",
            grade,
            assumption.currency,
        )
    # A conservative bound below zero is normal and must survive to the surface: the
    # bias-bounded range is one-sided-negative on plenty of real cohorts, and hiding
    # that would turn "this might have lost money" into "this made money".
    if (low := next((s for s in scenarios if s.name == "conservative"), None)) and low.net_roi < 0:
        warnings.append(
            "the conservative end of the range is a net loss; the program's return is "
            "not established at the bottom of the interval"
        )

    result = RoiResult(
        publishable=True,
        refusal_reason="",
        currency=assumption.currency,
        finance_version_id=assumption.version_id,
        contribution_per_script=per_script,
        cost_total=total,
        grade=grade,
        scenarios=tuple(scenarios),
        warnings=tuple(warnings) + evidence.warnings,
    )
    _LOG.info(
        "causal.roi.computed",
        event_id=cost.event_id,
        grade=grade.value,
        finance_version_id=assumption.version_id,
        contribution_per_script=per_script,
        cost_total=total,
        base_net_roi=result.scenario("base").net_roi if result.scenario("base") else None,
    )
    return result
