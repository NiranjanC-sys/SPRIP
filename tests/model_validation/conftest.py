"""Synthetic generators whose ground truth is known, for the forecasting models.

These are deliberately *not* the full synthetic panel from
:mod:`speaker_roi_analytics.synthetic`. That generator produces prescribing histories so
that the causal layer can be tested end to end, and running it costs minutes. The
forecasting models consume something much narrower - one row per measured event, carrying
an effect estimate and an interval - so the fixtures here manufacture exactly that, from a
hierarchy whose variance components are chosen rather than discovered.

Choosing them is the point. A shrinkage estimator can only be validated against a known
between-group variance, and a conformal interval can only be validated against a known
noise distribution. The full panel gives neither: its true effects exist, but the
hierarchy they were drawn from is an emergent property of a dozen interacting knobs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd
import pytest

from speaker_roi_core.enums import EvidenceGrade

#: Standard-normal quantile at 0.90, the one-sided tail of an 80% interval. The fixtures
#: build intervals with it so that ``prepare_training_frame`` recovers exactly the standard
#: error that was used to generate the observation - which is what makes the precision
#: weighting testable rather than merely plausible.
Z80 = 1.2816

DEFAULT_FORMATS = ("IN_PERSON", "VIRTUAL", "ROUNDTABLE")


def _grade_for(se: float) -> EvidenceGrade:
    """Grade by measured precision, the way the causal layer effectively does.

    Not an exact reproduction of :func:`~speaker_roi_analytics.causal.grade_evidence` - it
    reads eight gates, not one number - but it produces the correlation that matters here:
    imprecise events carry weaker grades. A fixture that assigned grades at random would
    let a precision-weighting bug pass, because the weights and the grades would be
    independent and any admissible-grade filter would look harmless.
    """
    if se > 0.80:
        return EvidenceGrade.DIRECTIONAL
    if se > 0.45:
        return EvidenceGrade.MODERATE
    return EvidenceGrade.STRONG


def build_hierarchical_events(
    seed: int,
    *,
    n: int = 120,
    tau: float = 0.35,
    brands: int = 6,
    formats: Sequence[str] = DEFAULT_FORMATS,
    noise_scale: float = 0.90,
    global_mean: float = 2.0,
) -> pd.DataFrame:
    """Measured-event rows drawn from a two-level hierarchy with known variances.

    Brand effects are drawn with standard deviation ``tau`` around ``global_mean``, and
    each ``(brand, format)`` cell with ``tau / 2`` around its brand. The true per-attendee
    effect is carried through in a ``_true`` column, which the production code ignores and
    the tests read.

    ``noise_scale`` controls the measurement error: each event's standard error is
    ``|N(0, noise_scale)| + 0.25``, so precision varies across events by roughly an order
    of magnitude, as it does in reality when one program had 40 attendees with a clean
    control pool and the next had 9.
    """
    rng = np.random.default_rng(seed)
    brand_ids = [f"b{i}" for i in range(brands)]
    brand_effect = {b: global_mean + rng.normal(0.0, tau) for b in brand_ids}
    cell_effect = {
        (b, f): brand_effect[b] + rng.normal(0.0, tau / 2.0) for b in brand_ids for f in formats
    }

    rows: list[dict[str, object]] = []
    for i in range(n):
        brand = brand_ids[i % brands]
        fmt = formats[(i // brands) % len(formats)]
        attendees = int(rng.integers(8, 40))
        true = cell_effect[(brand, fmt)]
        se = abs(rng.normal(0.0, noise_scale)) + 0.25
        observed = true + rng.normal(0.0, se)
        rows.append(
            {
                "event_id": f"e{i}",
                "brand_id": brand,
                "event_format": fmt,
                # Month index doubles as the temporal order the rolling-origin split uses.
                "event_month_index": i,
                "verified_attendees": attendees,
                "incremental_total": observed * attendees,
                "ci_low": (observed - Z80 * se) * attendees,
                "ci_high": (observed + Z80 * se) * attendees,
                "grade": _grade_for(se),
                "_true": true,
                "_se": se,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def hierarchical_events() -> Callable[..., pd.DataFrame]:
    """Factory fixture, so a test can choose its own seed and variance components."""
    return build_hierarchical_events


def build_invitations(
    seed: int,
    *,
    n_events: int = 80,
    size_range: tuple[int, int] = (18, 120),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Invitation-grain and event-grain frames for the attendance model.

    Attendance is generated from a logistic model on a subset of the features the model
    fits, plus a per-event shared shock. The shock is the reason
    :meth:`~speaker_roi_analytics.forecast.AttendanceForecaster.forecast_reach` builds its
    interval from realised event totals rather than from per-row binomial variance, so a
    fixture without one would make that design look like unnecessary conservatism.

    Two properties of this generator are load-bearing and were both absent from its first
    version, which made three tests unanswerable rather than failing:

    **Room sizes vary.** ``size_range`` spans roughly seven-fold. With a constant invitation
    count per event there is nothing for a design-level model to learn - the historical mean
    attendance is very nearly the optimal forecast - so "does the model beat the historical
    average" has no correct answer, and a proportional dispersion estimate is unmeasurable
    because every event is the same size.

    **The per-invitation signal is strong enough to detect.** Prior attendance behaviour is
    the dominant predictor of attendance in practice, and the coefficient here reflects
    that. With a weak coefficient the achievable AUC sits near the shock-limited floor, and
    an AUC assertion tests the fixture's signal-to-noise rather than the model.
    """
    rng = np.random.default_rng(seed)
    inv_rows: list[dict[str, object]] = []
    event_rows: list[dict[str, object]] = []

    for e in range(n_events):
        days_notice = int(rng.integers(5, 60))
        is_virtual = int(rng.random() < 0.35)
        per_event = int(rng.integers(size_range[0], size_range[1] + 1))
        # One shock per event: weather, a competing congress, a rep who forgot to call.
        shock = float(rng.normal(0.0, 0.55))
        invited = 0
        attended = 0
        for h in range(per_event):
            prior_rate = float(np.clip(rng.beta(2, 5), 0.0, 1.0))
            distance = 0.0 if is_virtual else float(abs(rng.normal(40, 30)))
            decile = int(rng.integers(1, 11))
            logit = (
                -1.60
                + 4.20 * prior_rate
                + 0.020 * days_notice
                - 0.010 * distance
                + 0.35 * is_virtual
                + 0.11 * decile
                + shock
            )
            probability = 1.0 / (1.0 + np.exp(-logit))
            outcome = int(rng.random() < probability)
            invited += 1
            attended += outcome
            inv_rows.append(
                {
                    "event_id": f"e{e}",
                    "hcp_id": f"h{e}-{h}",
                    # Carried on the invitation grain as well as the event grain: the
                    # model's documented contract is that either frame can be ordered in
                    # time without a join, so that a validation split cannot accidentally
                    # order invitations by row position.
                    "event_month_index": e,
                    "attended": outcome,
                    "days_notice": days_notice,
                    "channel_rank": int(rng.integers(0, 3)),
                    "prior_invitations": int(rng.integers(0, 8)),
                    "prior_attendance_rate": prior_rate,
                    "distance_km": distance,
                    "is_virtual": is_virtual,
                    "specialty_rank": int(rng.integers(0, 6)),
                    "decile": decile,
                    "prior_rep_calls": int(rng.integers(0, 12)),
                    "month_of_year": (e % 12) + 1,
                    "is_weekend": int(rng.random() < 0.2),
                }
            )
        event_rows.append(
            {
                "event_id": f"e{e}",
                "event_month_index": e,
                "verified_attendees": attended,
                "invitations_planned": invited,
                "days_notice": days_notice,
                "is_virtual": is_virtual,
                "format_rank": int(rng.integers(0, 4)),
                "speaker_prior_events": int(rng.integers(0, 15)),
                "month_of_year": (e % 12) + 1,
                "is_weekend": int(rng.random() < 0.2),
                "venue_capacity": int(per_event * 0.9),
                "_shock": shock,
            }
        )
    return pd.DataFrame(inv_rows), pd.DataFrame(event_rows)


@pytest.fixture
def invitation_panel() -> Callable[..., tuple[pd.DataFrame, pd.DataFrame]]:
    return build_invitations


def realised_variance_components(frame: pd.DataFrame) -> tuple[float, float]:
    """The ``(between_parent, within_parent)`` variance actually present in a fixture.

    Not the nominal ``tau`` the factory was asked for. With six brands, the realised
    between-brand spread can differ from its population value by a factor of ten - seed 404
    draws six brands whose true effects lie within 0.03 variance of each other, against a
    nominal 0.1225 - so asserting an estimator against the nominal parameter tests the
    fixture's luck rather than the estimator.
    """
    cells = frame.drop_duplicates(["brand_id", "event_format"])
    within = float(cells.groupby("brand_id")["_true"].var(ddof=1).mean())
    between = float(cells.groupby("brand_id")["_true"].mean().var(ddof=1))
    return between, within


#: A panel wide enough for the method-of-moments estimator to be measured two-sided:
#: ten brands across four formats. The narrower default fixture is kept for every other
#: test because it is the realistic size, but a heterogeneity estimator on six parents of
#: three cells has a sampling distribution wide enough to swallow any assertion tight
#: enough to be useful.
WIDE_PANEL = {
    "n": 600,
    "brands": 10,
    "formats": ("IN_PERSON", "VIRTUAL", "ROUNDTABLE", "HYBRID"),
    "noise_scale": 0.5,
}
