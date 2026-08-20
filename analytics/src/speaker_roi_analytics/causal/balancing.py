"""Post-matching weight refinement by entropy balancing.

Why matching alone is not enough
--------------------------------
Nearest-neighbour matching on a propensity score is a *scalar* summary of a
multivariate problem. Rosenbaum and Rubin's balancing-score result says that
conditioning on the true score balances every covariate **in expectation**; it says
nothing about any finite sample, and in a finite sample the score has no way to know
which of its inputs a particular matched set happens to have left unequal. On this
data, matching cuts the strongly selected covariates by 80-90% - the caliper is
doing most of the work - and then stalls with three or four of them sitting just
above the threshold, at 0.10-0.14 standardised units against a 0.10 bound.

That gap cannot honestly be closed by loosening the bound. The noise floor here is
``2 x SE(SMD) = 0.076``, so 0.10 is *above* what sampling error alone explains and
the residual is real imbalance rather than a measurement artefact. Nor is it closed
by a tighter caliper: a sweep showed that buys almost nothing and costs retention.

What this module does instead
-----------------------------
Entropy balancing (Hainmueller 2012) keeps the matched sets exactly as matching left
them and reweights *within* them, choosing the control weights that satisfy the
balance constraints while staying as close as possible - in Kullback-Leibler
divergence - to the weights matching produced. The moment conditions are then met by
construction rather than hoped for, and because the starting point is the matched,
calipered sample, the weights are still supported by controls matching already
certified as comparable. That is the crucial difference from weighting the full
sample: no unit outside the caliper can be resurrected by a large weight.

Two constraints make this safe rather than merely convenient.

**Event totals are held fixed.** The event indicators are part of the constraint
set, so each event's control weight still sums to its treated count. Without that
the solver could satisfy a global moment by shifting weight between events, and the
cohort-time aggregation downstream - which relies on each event's two arms being
comparable *within* the event - would be reading arms that no longer correspond. The
covariate coefficients are shared across events rather than fitted per event, which
is what keeps a typical event's fifteen treated units from being asked to support six
exact moments of their own.

**A failed refinement is refused, not accepted.** Exact moments can always be bought
by concentrating weight on a handful of controls, and weights like that report
balance the data cannot support. So the effective sample size is checked against a
floor, and if the refinement costs more than that - or if the solver does not
converge - the base weights are returned unchanged with the reason recorded, and the
balance gate is left to fail honestly. Reporting an unreachable estimate as balanced
is a worse failure than reporting an unbalanced one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import structlog

__all__ = ["BalanceRefinement", "entropy_balance"]

_LOG = structlog.get_logger(__name__)

#: Newton iterations before the solver gives up. Entropy balancing's dual is convex
#: and smooth, so a well-posed problem converges in well under ten; anything needing
#: many more is telling us the constraints are close to infeasible.
MAX_ITER = 40

#: Convergence test, in standardised units: the largest absolute residual moment. Set
#: two orders of magnitude below the 0.10 balance bound so convergence is never the
#: thing that decides whether the gate passes.
TOLERANCE = 1e-3

#: Smallest share of the base effective sample size the refinement may leave behind.
#: Below this the exact moments are being carried by too few controls to believe, and
#: the refinement is refused. Kish effective size, so 0.5 means the refined weights
#: are worth at least half as many independent controls as the matched weights were.
MIN_ESS_SHARE = 0.5


@dataclass(frozen=True)
class BalanceRefinement:
    """Outcome of the refinement, whether or not it was applied."""

    #: Weights to use. The base weights unchanged when ``applied`` is False.
    weights: pd.DataFrame
    applied: bool
    #: Why it was refused. Empty when ``applied`` is True.
    reason: str
    #: Largest absolute standardised residual moment the solver reached.
    max_residual: float
    #: Kish effective sample size of the control arm, before and after.
    ess_before: float
    ess_after: float
    #: Newton iterations used.
    iterations: int

    @property
    def ess_share(self) -> float:
        return self.ess_after / self.ess_before if self.ess_before > 0 else float("nan")


def _kish(w: np.ndarray) -> float:
    """Effective sample size of a weighted sample: ``(sum w)^2 / sum w^2``."""
    total = float(w.sum())
    squares = float(np.square(w).sum())
    return (total * total / squares) if squares > 0 else 0.0


def _design(
    frame: pd.DataFrame, covariates: tuple[str, ...], scale: dict[str, float]
) -> np.ndarray:
    """Standardised covariate block, mean-imputed.

    Imputation is confined to the *solver's* view. The balance table still reads raw
    values with missingness skipped, so a covariate that is largely missing cannot be
    made to look balanced by imputing it to the target: the constraint the solver
    satisfies and the number the gate reads would then disagree, and the gate wins.
    """
    columns = []
    for name in covariates:
        values = frame[name].to_numpy(dtype=float)
        mean = float(np.nanmean(values)) if np.isfinite(np.nanmean(values)) else 0.0
        filled = np.where(np.isnan(values), mean, values)
        columns.append(filled / (scale.get(name) or 1.0))
    return np.column_stack(columns) if columns else np.empty((len(frame), 0))


def entropy_balance(
    weights: pd.DataFrame,
    features: pd.DataFrame,
    covariates: tuple[str, ...],
    scale: dict[str, float],
) -> BalanceRefinement:
    """Reweight matched controls to meet the treated covariate means exactly.

    ``weights`` is :attr:`~.matching.MatchResult.weights` - one row per unit with an
    ``is_treated`` flag and the matching weight. ``covariates`` should be the
    ``MATCHED``-role columns: the ones matching was responsible for, and the ones the
    gate reads. ``scale`` maps each to the pre-matching pooled standard deviation, so
    the solver's tolerance and the gate's bound are in the same units.

    Treated weights are never touched. The estimand is the ATT for the matched treated
    population, and reweighting the treated arm would silently redefine whose effect
    is being reported.
    """
    if weights.empty or not covariates:
        return BalanceRefinement(weights, False, "nothing to balance", float("nan"), 0.0, 0.0, 0)

    joined = weights.merge(
        features[["event_id", "hcp_id", *covariates]], on=["event_id", "hcp_id"], how="left"
    )
    treated = joined[joined["is_treated"]]
    control = joined[~joined["is_treated"]].reset_index(drop=True)
    if treated.empty or control.empty:
        return BalanceRefinement(weights, False, "one arm is empty", float("nan"), 0.0, 0.0, 0)

    used = tuple(name for name in covariates if name in joined and joined[name].notna().any())
    if not used:
        return BalanceRefinement(
            weights, False, "no covariate has any observed value", float("nan"), 0.0, 0.0, 0
        )

    t_w = treated["weight"].to_numpy(dtype=float)
    t_x = _design(treated, used, scale)
    target = (t_x * t_w[:, None]).sum(axis=0) / t_w.sum()

    c_x = _design(control, used, scale)
    base = control["weight"].to_numpy(dtype=float)
    ess_before = _kish(base)

    # Event indicators pin each event's control total to its treated total. One is
    # dropped: the normalisation ``sum(w) = 1`` already fixes the level, and keeping
    # every indicator would leave the constraint matrix singular.
    categories = sorted(joined["event_id"].unique())
    c_events = pd.Categorical(control["event_id"], categories=categories)
    t_events = pd.Categorical(treated["event_id"], categories=categories)
    dummies = np.eye(len(categories), dtype=float)[c_events.codes]
    shares = np.bincount(t_events.codes, weights=t_w, minlength=len(categories)) / t_w.sum()
    dummies, shares = dummies[:, 1:], shares[1:]

    z = np.column_stack([c_x - target, dummies - shares])
    lam = np.zeros(z.shape[1], dtype=float)
    log_base = np.log(np.maximum(base, 1e-300))

    def evaluate(candidate: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
        """Dual loss, residual moments and normalised weights at ``candidate``."""
        eta = log_base - z @ candidate
        peak = float(eta.max())
        raw = np.exp(eta - peak)
        total = float(raw.sum())
        w = raw / total
        loss = float(np.log(total) + peak - np.log(base.sum()))
        return loss, z.T @ w, w

    loss, moments, w = evaluate(lam)
    iterations = 0
    for iterations in range(1, MAX_ITER + 1):
        if float(np.abs(moments).max()) <= TOLERANCE:
            break
        centred = z - moments
        hessian = centred.T @ (centred * w[:, None])
        # Ridge on the diagonal: near-collinear constraints - a small event whose
        # controls barely vary - otherwise produce a step of arbitrary size in a
        # direction the data cannot resolve.
        hessian += 1e-8 * max(float(np.trace(hessian)), 1.0) * np.eye(hessian.shape[0])
        try:
            step = np.linalg.solve(hessian, moments)
        except np.linalg.LinAlgError:
            return BalanceRefinement(
                weights,
                False,
                "balance constraints are singular",
                float(np.abs(moments).max()),
                ess_before,
                ess_before,
                iterations,
            )
        # Backtracking: the dual is convex, so a step that fails to reduce the loss is
        # too long rather than pointing the wrong way.
        length, accepted = 1.0, False
        for _ in range(30):
            trial = lam + length * step
            new_loss, new_moments, new_w = evaluate(trial)
            if new_loss <= loss:
                lam, loss, moments, w, accepted = trial, new_loss, new_moments, new_w, True
                break
            length *= 0.5
        if not accepted:
            break

    residual = float(np.abs(moments).max())
    refined = w * float(base.sum())
    ess_after = _kish(refined)

    if residual > TOLERANCE:
        return BalanceRefinement(
            weights, False, "solver did not converge", residual, ess_before, ess_after, iterations
        )
    if ess_before > 0 and ess_after / ess_before < MIN_ESS_SHARE:
        return BalanceRefinement(
            weights,
            False,
            (
                f"refinement costs too much precision: effective control sample "
                f"{ess_after:.0f} of {ess_before:.0f} ({ess_after / ess_before:.0%}, "
                f"floor {MIN_ESS_SHARE:.0%})"
            ),
            residual,
            ess_before,
            ess_after,
            iterations,
        )

    out = weights.copy()
    lookup = pd.Series(refined, index=pd.MultiIndex.from_frame(control[["event_id", "hcp_id"]]))
    mapped = pd.MultiIndex.from_frame(out[["event_id", "hcp_id"]]).map(lookup)
    out["weight"] = np.where(
        out["is_treated"], out["weight"].to_numpy(dtype=float), mapped.to_numpy(dtype=float)
    )
    _LOG.info(
        "causal.matching.entropy_balance",
        covariates=list(used),
        constraints=int(z.shape[1]),
        iterations=iterations,
        residual=residual,
        ess_before=ess_before,
        ess_after=ess_after,
    )
    return BalanceRefinement(out, True, "", residual, ess_before, ess_after, iterations)
