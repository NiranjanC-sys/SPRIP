"""M1 - attendance propensity, and the common-support decision that follows it.

What this model is for, stated precisely because it changes every design choice
below: the propensity score exists to **build comparable cohorts**, not to predict
who will attend. Nobody is shown a ranked list of prescribers by predicted
attendance, and plan.md §15 forbids exactly that use. The score is an intermediate
quantity consumed by matching and then discarded.

Three consequences follow.

**It is cross-fitted, always.** A gradient-boosted model scored on its own
training rows produces propensities that are too confident: treated units get
pushed toward 1 and controls toward 0, the two distributions pull apart, and
measured overlap looks worse than it is while matched pairs are chosen on
memorised noise. Out-of-fold scoring costs one model fit per fold and removes the
problem. The folds are grouped by prescriber, because the same prescriber appears
at several events and splitting them across folds would leak.

**Discrimination is a diagnostic, not the objective.** A high AUC means selection
is strong - which we already know, it is designed in - and a *very* high AUC is a
warning that something in the feature set is proxying treatment rather than
confounding it. What actually matters is calibration, since the score is used as a
distance metric, and the balance it achieves after matching, which is measured in
``matching.py`` and gated there.

**Matching happens on the linear predictor, not the probability.** Probabilities
compress at both ends: the gap from 0.90 to 0.95 is the same distance as 0.50 to
0.55 on the probability scale but a much larger difference in odds, so a caliper
in probability units is tight in the middle of the distribution and meaningless at
the extremes. The logit is roughly homoscedastic, which is the scale Austin's
0.2-SD caliper was calibrated on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import structlog
from lightgbm import LGBMClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold

from speaker_roi_core.enums import ExclusionReason

from .features import PROPENSITY_COLUMNS
from .panel import Cohort
from .spec import EstimatorSpec

__all__ = [
    "PROPENSITY_PARAMS",
    "PropensityResult",
    "fit_propensity",
]

_LOG = structlog.get_logger(__name__)

#: Deliberately conservative. The cohorts here are hundreds to low thousands of
#: rows with a handful of genuinely predictive features, so the risk is a model
#: that memorises prescribers rather than one that underfits. Shallow trees, a
#: high leaf minimum and heavy subsampling are all pointed at that risk.
PROPENSITY_PARAMS: dict[str, object] = {
    "objective": "binary",
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 15,
    "max_depth": 4,
    "min_child_samples": 40,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    #: L2 rather than L1: the features are correlated by construction (volume,
    #: TRx and decile all measure prescriber size), and L1 would arbitrarily pick
    #: one of a correlated set, making the score unstable across refits for no
    #: gain in the estimate.
    "reg_lambda": 1.0,
    "verbose": -1,
    "deterministic": True,
    "force_row_wise": True,
}

#: Fewer folds than the usual 5 because the treated arm is the scarce one: with
#: ~1,500 attendees, 4 folds still leaves ~375 treated units per held-out fold,
#: enough for a stable AUC, while keeping 75% of the data in each fit.
N_FOLDS = 4


@dataclass(frozen=True, slots=True)
class PropensityResult:
    """Out-of-fold scores, held-out metrics, and the support decision.

    ``scores`` is one row per cohort unit with ``propensity`` (probability) and
    ``linear_propensity`` (logit). ``in_support`` is the boolean the matcher
    respects; units outside it are excluded with
    :attr:`~speaker_roi_core.enums.ExclusionReason.OUTSIDE_COMMON_SUPPORT`.
    """

    scores: pd.DataFrame
    auc: float
    #: Per-fold AUC. A wide spread means the score depends on which prescribers
    #: happened to land in the training half, and the matched sets built from it
    #: are correspondingly arbitrary.
    fold_aucs: tuple[float, ...]
    #: Mean absolute deviation between predicted and observed attendance rate
    #: across score deciles. This is the metric that matters for a score used as a
    #: distance, and it is not the one a classifier is usually judged on.
    calibration_error: float
    #: Share of treated units inside the control score range.
    overlap: float
    exclusions: pd.DataFrame
    importances: pd.DataFrame
    n_folds: int = N_FOLDS
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _logit(p: np.ndarray) -> np.ndarray:
    """Log-odds, with the ends clipped.

    Cross-fitted probabilities can legitimately reach 0 or 1 for a unit no fold
    ever saw a near neighbour of. Clipping at 1e-6 caps the logit near +/-13.8,
    which is far outside any caliper and so behaves as "unmatched" rather than
    poisoning the standard deviation the caliper is scaled by.
    """
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1.0 - p))


def _calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Mean absolute gap between predicted and realised rate, by score decile.

    Deciles of the score rather than fixed probability bins: the score
    distribution is concentrated, and equal-width bins would leave most of them
    empty and average a handful of noisy cells with the well-populated ones.
    """
    order = np.argsort(p)
    gaps = []
    for chunk in np.array_split(order, bins):
        if chunk.size < 10:
            continue
        gaps.append(abs(float(p[chunk].mean() - y[chunk].mean())))
    return float(np.mean(gaps)) if gaps else float("nan")


def _common_support(linear: np.ndarray, treated: np.ndarray) -> np.ndarray:
    """Units inside the overlapping region of the two score distributions.

    The rule is the 1st-to-99th percentile intersection rather than the strict
    min-max overlap. Strict min-max hands the boundary to a single extreme unit in
    either arm, so one unusual prescriber can widen the retained region enough to
    admit treated units with no real counterpart - or, in the other direction,
    truncate a perfectly good cohort.

    Treated units above the control range are the substantive exclusions: there is
    no one to compare them with, and a model that extrapolates there is inventing
    the comparison rather than making it. Controls outside the treated range are
    also dropped, for the narrower reason that they will never be anybody's
    nearest neighbour and only inflate the pool.
    """
    if treated.all() or not treated.any():
        return np.ones_like(treated, dtype=bool)
    t_lo, t_hi = np.percentile(linear[treated], [1, 99])
    c_lo, c_hi = np.percentile(linear[~treated], [1, 99])
    lo, hi = max(t_lo, c_lo), min(t_hi, c_hi)
    return (linear >= lo) & (linear <= hi)


def fit_propensity(
    cohort: Cohort,
    features: pd.DataFrame,
    spec: EstimatorSpec,
    *,
    columns: tuple[str, ...] | None = None,
) -> PropensityResult:
    """Cross-fitted attendance propensity plus the common-support decision.

    Raises nothing on a degenerate cohort: too few treated units, or an arm that
    is entirely absent, produces a result whose ``warnings`` say so and whose
    scores are constant. The gate layer decides what that means for the evidence
    grade - refusing here would deny the caller the diagnostics they need to
    explain the refusal.

    ``columns`` overrides :data:`~.features.PROPENSITY_COLUMNS` and exists for one
    caller: :func:`~.sensitivity.run_sensitivity` withholds a covariate at a time to
    benchmark how far a confounder of a strength this data contains can move the
    answer. It is deliberately a keyword argument rather than a spec field, because a
    spec is the thing a stored result is reproducible against and these runs are
    diagnostics, not specifications anything is reported under.
    """
    model_columns = tuple(columns) if columns else PROPENSITY_COLUMNS
    frame = features.merge(
        cohort.units[["event_id", "hcp_id", "is_treated"]], on=["event_id", "hcp_id"], how="inner"
    )
    y = frame["is_treated"].to_numpy(dtype=int)
    # PROPENSITY_COLUMNS, not every feature column: the baseline-window own-volume
    # levels are deliberately withheld from the model. Matching on a function of the
    # same realised window the difference-in-differences subtracts borrows that
    # window's noise and the estimator reads the reversion as impact - see
    # :data:`~.features.BASELINE_WINDOW_LEVELS` for the mechanism and the measurement.
    x = frame[list(model_columns)]
    groups = frame["hcp_id"].to_numpy()

    warnings: list[str] = []
    n_treated, n_control = int(y.sum()), int((1 - y).sum())
    degenerate = min(n_treated, n_control) < N_FOLDS * 5
    if degenerate:
        # Constant score: every unit is equally comparable, which is the honest
        # statement when there is not enough data to say otherwise. Matching then
        # degenerates to within-event random pairing, and the gates fail on sample
        # size, which is the correct outcome.
        warnings.append(
            f"cohort too small to cross-fit a propensity model "
            f"({n_treated} treated, {n_control} control); using a constant score"
        )
        oof = np.full(len(frame), y.mean() if len(y) else 0.5, dtype=float)
        fold_aucs: tuple[float, ...] = ()
        importances = pd.DataFrame({"feature": list(model_columns), "gain": 0.0})
    else:
        oof = np.full(len(frame), np.nan)
        fold_scores: list[float] = []
        gains = np.zeros(len(model_columns), dtype=float)
        # Stratified *and* grouped: stratified so every fold holds a representative
        # share of the scarce treated arm, grouped so a prescriber's several units
        # never straddle the split.
        splitter = StratifiedGroupKFold(
            n_splits=N_FOLDS, shuffle=True, random_state=spec.bootstrap_seed
        )
        for fold, (train_idx, test_idx) in enumerate(splitter.split(x, y, groups)):
            model = LGBMClassifier(**PROPENSITY_PARAMS, random_state=spec.bootstrap_seed + fold)
            model.fit(x.iloc[train_idx], y[train_idx])
            oof[test_idx] = model.predict_proba(x.iloc[test_idx])[:, 1]
            gains += np.asarray(model.booster_.feature_importance("gain"), dtype=float)
            held = y[test_idx]
            if 0 < held.sum() < held.size:
                fold_scores.append(float(roc_auc_score(held, oof[test_idx])))
        fold_aucs = tuple(fold_scores)
        importances = pd.DataFrame(
            {"feature": list(model_columns), "gain": gains / max(N_FOLDS, 1)}
        ).sort_values("gain", ascending=False, ignore_index=True)

    linear = _logit(oof)
    treated_mask = y.astype(bool)
    auc = float(roc_auc_score(y, oof)) if 0 < y.sum() < y.size and np.ptp(oof) > 0 else float("nan")
    if auc == auc and auc > 0.95:
        # Not a compliment. Selection this separable means some feature is standing
        # in for the treatment itself, and the matched comparison would then be
        # between units that differ on that feature by construction.
        warnings.append(
            f"propensity AUC {auc:.3f} is high enough to suspect a feature is "
            "proxying treatment rather than confounding it"
        )

    in_support = _common_support(linear, treated_mask)
    overlap = float(in_support[treated_mask].mean()) if treated_mask.any() else float("nan")
    if overlap == overlap and overlap < spec.gates.min_propensity_overlap:
        warnings.append(
            f"only {overlap:.1%} of treated units lie inside the control score range "
            f"(gate requires {spec.gates.min_propensity_overlap:.0%})"
        )

    scores = frame[["tenant_id", "event_id", "hcp_id", "brand_id", "is_treated"]].copy()
    scores["propensity"] = oof
    scores["linear_propensity"] = linear
    scores["in_support"] = in_support

    dropped = scores.loc[~in_support, ["tenant_id", "event_id", "hcp_id"]].copy()
    dropped["reason"] = ExclusionReason.OUTSIDE_COMMON_SUPPORT.value

    _LOG.info(
        "causal.propensity.fitted",
        spec=spec.fingerprint,
        treated=n_treated,
        control=n_control,
        auc=auc,
        overlap=overlap,
        out_of_support=int((~in_support).sum()),
        warnings=len(warnings),
    )
    return PropensityResult(
        scores=scores.reset_index(drop=True),
        auc=auc,
        fold_aucs=fold_aucs,
        calibration_error=_calibration_error(y.astype(float), oof),
        overlap=overlap,
        exclusions=dropped.reset_index(drop=True),
        importances=importances,
        warnings=tuple(warnings),
    )
