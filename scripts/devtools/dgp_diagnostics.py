"""Measure the properties the synthetic DGP is *asserted* to have.

plan.md §11 makes falsifiable claims about the generated data, and until now only
one of them (overlapping exposure) was checked anywhere in code. A synthetic
dataset whose confounding is not actually there, or whose confounding is so
severe that no estimator could ever recover the truth, is worse than no synthetic
dataset at all: everything downstream still runs, and the numbers it produces are
meaningless in a way nothing surfaces.

1. **Overlapping exposure** - the share of verified attendances with another
   same-brand verified attendance inside the 90-day outcome window. Those rows
   are dropped from the treated cohort, so a high rate leaves nothing to
   estimate on. Target ~6%.
2. **Selection is real** - the standardised mean difference between attendees
   and invited non-attendees on pre-period prescribing must exceed 0.25, or the
   propensity model has nothing to correct and matching is theatre.
3. **The naive estimator is wrong** - a plain pre/post difference on the treated
   must overstate the stored ground truth by more than 25%, or the whole causal
   apparatus is solving a problem the data does not have, and the demo narrative
   in plan.md §24.5 has nothing to show.
4. **The truth is still recoverable** - attendees and invited non-attendees must
   already be moving alike before the event, on the scale the estimator works
   on. 2 and 3 are about making the problem hard; this one is about keeping it
   solvable, and it is the gate that catches the failure mode where selection is
   accidentally tied to transient outcome dynamics. Two such defects were found
   and fixed this way; both were invisible to every other check.

2 and 3 pull against 1 and 4: the levers that reduce contamination also reduce
selection, and the levers that strengthen selection tend to attack
identification. Anything that changes a volume, selection or outcome parameter
has to be re-measured here, not reasoned about.

Seeds are fixed and several are run, because a gate that passes on one draw and
fails on the next is not a gate.

    python scripts/devtools/dgp_diagnostics.py            # both profiles
    python scripts/devtools/dgp_diagnostics.py smoke      # one profile
    python scripts/devtools/dgp_diagnostics.py smoke 3    # over 3 seeds
"""

from __future__ import annotations

import logging
import statistics
import sys
import time

import numpy as np
import pandas as pd
import structlog

from speaker_roi_analytics.synthetic import config as cfg
from speaker_roi_analytics.synthetic.generator import _build
from speaker_roi_analytics.synthetic.rng import RngBook

#: Seeds are fixed rather than random: a gate that passes on one draw and fails
#: on the next is not a gate, and the only way to see that is to run several.
SEEDS = (20260819, 4242, 777, 13, 90210)

PRE_MONTHS = 6
POST_MONTHS = 3


def _quiet() -> None:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))


def _month_index(months: pd.Series, start: pd.Timestamp) -> pd.Series:
    m = pd.to_datetime(months)
    return (m.dt.year - start.year) * 12 + (m.dt.month - start.month)


def diagnose(profile: cfg.SyntheticProfile, seed: int) -> dict[str, float]:
    started = time.monotonic()
    _tax, frames, truth, diag = _build(profile, RngBook(seed))
    elapsed = time.monotonic() - started

    events = frames["events"]
    completed = events[events["status"] == "COMPLETED"]
    attendance = frames["attendance"]
    verified = attendance[attendance["is_verified"]]
    rx = frames["rx_monthly"]
    latent = truth["hcp_latent"]

    start = pd.Timestamp(profile.panel_start_month)
    rx = rx.assign(mi=_month_index(rx["month"], start))
    # One brand-level series per HCP-month: the estimator works on the brand the
    # event promoted, not on a single SKU.
    brand_rx = (
        rx[rx["is_observed"]].groupby(["hcp_id", "brand_id", "mi"], as_index=False)["nrx"].sum()
    )

    ev = completed[["event_id", "brand_id", "event_month_index"]]
    treated = verified[["event_id", "hcp_id"]].merge(ev, on="event_id", how="inner")
    invited = frames["invitations"][["event_id", "hcp_id"]].merge(ev, on="event_id", how="inner")
    attended_keys = set(zip(treated["event_id"], treated["hcp_id"], strict=True))
    control = invited[
        ~pd.Series(
            list(zip(invited["event_id"], invited["hcp_id"], strict=True)),
            index=invited.index,
        ).isin(attended_keys)
    ]

    def window_mean(pairs: pd.DataFrame, lo: int, hi: int, *, log: bool = False) -> pd.Series:
        """Mean brand NRx per month over months [event+lo, event+hi] per row.

        ``log`` averages ``log1p(nrx)`` instead, for the parallel-trends check
        below - see the comment there for why the scale is load-bearing.
        """
        joined = pairs.merge(brand_rx, on=["hcp_id", "brand_id"], how="left")
        offset = joined["mi"] - joined["event_month_index"]
        inside = joined[(offset >= lo) & (offset <= hi)]
        if log:
            inside = inside.assign(nrx=np.log1p(inside["nrx"]))
        grouped = inside.groupby(["event_id", "hcp_id"])["nrx"].mean()
        keys = pd.MultiIndex.from_frame(pairs[["event_id", "hcp_id"]])
        return grouped.reindex(keys).to_numpy()

    t_pre = window_mean(treated, -PRE_MONTHS, -1)
    c_pre = window_mean(control, -PRE_MONTHS, -1)
    t_post = window_mean(treated, 1, POST_MONTHS)
    c_post = window_mean(control, 1, POST_MONTHS)

    def smd(a: np.ndarray, b: np.ndarray) -> float:
        a, b = a[~np.isnan(a)], b[~np.isnan(b)]
        pooled = np.sqrt((np.var(a, ddof=1) + np.var(b, ddof=1)) / 2)
        return float(abs(a.mean() - b.mean()) / pooled) if pooled > 0 else 0.0

    # Selection on the observable the propensity model actually sees...
    smd_pre_rx = smd(t_pre, c_pre)
    # ...and on the latent trait it does not, which is the residual confounding
    # the sensitivity analysis has to bound.
    lat = latent.set_index("hcp_id")["latent_opportunity"]
    smd_latent = smd(
        lat.reindex(treated["hcp_id"]).to_numpy(),
        lat.reindex(control["hcp_id"]).to_numpy(),
    )

    # The naive analyst's number: treated post minus treated pre, times attendees,
    # summed over events. The truth is stored per event.
    ok = ~(np.isnan(t_pre) | np.isnan(t_post))
    c_ok = ~(np.isnan(c_pre) | np.isnan(c_post))
    treated_delta = float((t_post[ok] - t_pre[ok]).mean())
    naive_total = treated_delta * POST_MONTHS * int(ok.sum())

    # Parallel trends is the assumption everything downstream rests on, and it is
    # a property of the *data*, testable without building an estimator: if
    # treatment assignment does not depend on transient outcome dynamics, then
    # attendees and invited non-attendees must already be moving alike before the
    # event. Measured as the difference in each group's own early-pre to late-pre
    # step, scaled by the true effect so the number is readable as "how much of the
    # effect could a pre-trend masquerade as".
    #
    # No matching, no propensity model, no weighting - which is the point. A
    # matched estimator on a noisy baseline is biased in whichever direction the
    # matching variable's noise runs, so a diagnostic built that way reports its own
    # artefacts. Whether an estimator recovers the stored truth is a question about
    # the estimator and belongs in tests/model_validation.
    #
    # Two pieces of structure this does need, both of them substantive.
    #
    # First, the event fixed effect. Access, competitor pressure and seasonality are
    # AR(1) walks shared by every HCP in a brand-region, and an event contributes
    # ~13 attendees against ~40 invited non-attendees, so the two *pooled* group
    # means weight those shocks differently. Differencing inside each event and only
    # then averaging removes them, because both groups then face the same draw.
    #
    # Second, and less obvious: this is measured on ``log1p(nrx)``, not on raw NRx,
    # because **parallel trends in raw levels is violated by construction here and
    # that is correct rather than a defect.** The outcome is multiplicative - volume
    # is ``exp(linear)`` - and attendees are selected to a higher level (the SMD
    # above is ~0.75 by design). So any movement common to both groups, the
    # promotional halo included, scales with each unit's own level and therefore
    # produces a larger *absolute* change for attendees. Measured in levels the
    # statistic came out at -0.26 to +2.72 times the effect depending on the seed;
    # the same data in logs gives -0.001 to +0.019, i.e. pre-period trends that
    # agree to within two percent.
    #
    # A multiplicative outcome, selection on level, and additive parallel trends are
    # three properties that cannot hold at once, and the first two are the realistic
    # ones. The consequence is a real constraint on M2, not on the generator: it
    # cannot difference raw NRx across groups at different baselines. Working in
    # logs, or differencing within strata of baseline volume - where treated and
    # control share a level, so a common multiplicative shock is the same absolute
    # amount - both discharge it. Matching on pre-period volume, which plan.md §12.2
    # already requires, is what produces those strata. That the stored truth is
    # additive in NRx while the confounding is multiplicative is the hard case on
    # purpose: it is why the estimator has to condition on baseline rather than
    # merely adjust for it.
    def log_step(pairs: pd.DataFrame) -> np.ndarray:
        late = window_mean(pairs, -(PRE_MONTHS // 2), -1, log=True)
        early = window_mean(pairs, -PRE_MONTHS, -(PRE_MONTHS // 2) - 1, log=True)
        return late - early

    def by_event(pairs: pd.DataFrame, values: np.ndarray) -> pd.Series:
        col = pd.Series(values, index=pairs.index)
        return col.groupby(pairs["event_id"]).mean()

    gap = (by_event(treated, log_step(treated)) - by_event(control, log_step(control))).dropna()
    # Weighted by attendees, matching how the ATT aggregates event-level effects.
    w = treated.groupby("event_id").size().reindex(gap.index)
    pretrend = float((gap * w).sum() / w.sum()) if w.sum() else float("nan")

    realised = truth["event_effects"]
    live = realised[realised["is_realised"]]
    true_total = float(live["true_total_incremental_nrx_90d"].sum())

    naive_ratio = naive_total / true_total if true_total else float("nan")
    control_delta = float((c_post[c_ok] - c_pre[c_ok]).mean())

    return {
        "seed": seed,
        "overlap": float(diag["overlapping_exposure_rate"]),
        "attendance_rate": float(diag["verified_attendance_rate"]),
        "smd_pre_rx": smd_pre_rx,
        "smd_latent": smd_latent,
        "naive_ratio": naive_ratio,
        "pretrend": pretrend,
        "abs_pretrend": abs(pretrend),
        "treated_delta": treated_delta,
        "control_delta": control_delta,
        "treated": len(treated),
        "usable_per_event": len(verified)
        * (1 - float(diag["overlapping_exposure_rate"]))
        / max(len(completed), 1),
        "rx_rows": len(rx),
        "seconds": elapsed,
    }


GATES = (
    ("overlap", "<=", 0.12, "overlapping exposure"),
    ("smd_pre_rx", ">=", 0.25, "pre-period SMD (observable)"),
    ("naive_ratio", ">=", 1.25, "naive / true"),
    ("abs_pretrend", "<=", 0.05, "pre-trend, log NRx"),
)


def report(name: str, rows: list[dict[str, float]]) -> bool:
    print(f"\n=== {name} ===")
    header = (
        f"{'seed':>10} {'overlap':>8} {'att.rate':>9} {'SMD(rx)':>8} {'SMD(lat)':>9} "
        f"{'naive/true':>11} {'pretrend':>9} {'usable/evt':>11} {'rx rows':>10} {'secs':>6}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{int(r['seed']):>10} {r['overlap']:>7.1%} {r['attendance_rate']:>8.1%} "
            f"{r['smd_pre_rx']:>8.3f} {r['smd_latent']:>9.3f} {r['naive_ratio']:>11.2f} "
            f"{r['pretrend']:>+9.4f} "
            f"{r['usable_per_event']:>11.1f} {int(r['rx_rows']):>10,} {r['seconds']:>6.1f}"
        )
    ok = True
    print()
    for key, op, bound, label in GATES:
        values = [r[key] for r in rows]
        worst = max(values) if op == "<=" else min(values)
        passed = worst <= bound if op == "<=" else worst >= bound
        ok &= passed
        mean = statistics.fmean(values)
        print(
            f"  {'PASS' if passed else 'FAIL'}  {label:<28} worst {worst:>7.3f} "
            f"{op} {bound}   (mean {mean:.3f})"
        )
    return ok


def main(argv: list[str]) -> int:
    _quiet()
    names = [argv[0]] if argv and argv[0] in cfg.PROFILES else list(cfg.PROFILES)
    n_seeds = int(argv[1]) if len(argv) > 1 else 1
    ok = True
    for name in names:
        profile = cfg.PROFILES[name]
        rows = [diagnose(profile, s) for s in SEEDS[:n_seeds]]
        ok &= report(name, rows)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
