"""Measure how overlapping exposure responds to the HCP universe size.

The generator asserts a ceiling on overlapping exposure - the share of verified
attendances that have another same-brand attendance inside the 90-day outcome
window - because those attendances are excluded from the treated cohort and a
high rate leaves nothing to estimate on. Contamination is a *density*: a
same-brand invitation lands in an HCP's window at a rate set by events x
invitees x attendance rate over the size of the universe they are drawn from, and
only the denominator is free once the row minimums fix the numerator.

The relationship is steeper than 1/n, because a larger pool leaves more
un-cooled candidates and the invitation scheduler's per-HCP-brand cooldown gets
to do its job instead of running out of eligible prescribers. That is why this
has to be measured rather than extrapolated - see deviation 4 in
``synthetic/config.py`` for what happened the last time it was reasoned about.

    python scripts/devtools/sweep_overlap.py                    # smoke defaults
    python scripts/devtools/sweep_overlap.py full 9000 14000    # explicit sizes
"""

from __future__ import annotations

import dataclasses
import logging
import sys
import time

import structlog

from speaker_roi_analytics.synthetic import config as cfg
from speaker_roi_analytics.synthetic.generator import _build
from speaker_roi_analytics.synthetic.rng import RngBook


def measure(base: cfg.SyntheticProfile, n_hcps: int) -> dict[str, float]:
    profile = dataclasses.replace(base, n_hcps_per_tenant=n_hcps)
    start = time.monotonic()
    _tax, frames, _truth, diag = _build(profile, RngBook(20260819))
    elapsed = time.monotonic() - start

    attendance = frames["attendance"]
    verified = int(attendance["is_verified"].sum())
    events = frames["events"]
    completed = int((events["status"] == "COMPLETED").sum())
    overlap = float(diag["overlapping_exposure_rate"])
    return {
        "hcps_per_tenant": n_hcps,
        "overlap_pct": overlap * 100,
        "verified": verified,
        "per_event": verified / completed,
        "usable_per_event": verified * (1 - overlap) / completed,
        "rx_rows": int(frames["rx_monthly"].shape[0]),
        "seconds": elapsed,
    }


#: Bracketing values per profile, wide enough to show the curve's shape rather
#: than just whether one guess landed.
DEFAULT_SIZES: dict[str, tuple[int, ...]] = {
    "smoke": (400, 800, 1200, 2000, 3200),
    "full": (5_200, 9_000, 14_000, 20_000),
}


def main(argv: list[str]) -> int:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))
    name = argv[0] if argv and argv[0] in cfg.PROFILES else "smoke"
    rest = argv[1:] if argv and argv[0] in cfg.PROFILES else argv
    sizes = tuple(int(a) for a in rest) if rest else DEFAULT_SIZES[name]
    base = cfg.PROFILES[name]

    header = f"{'hcps/tenant':>12} {'overlap%':>9} {'verified':>9} {'att/event':>10} {'usable/event':>13} {'rx rows':>9} {'secs':>6}"
    print(f"=== {name} ===")
    print(header)
    print("-" * len(header))
    for n in sizes:
        r = measure(base, n)
        print(
            f"{r['hcps_per_tenant']:>12,} {r['overlap_pct']:>8.1f}% {r['verified']:>9,} "
            f"{r['per_event']:>10.1f} {r['usable_per_event']:>13.1f} {r['rx_rows']:>9,} "
            f"{r['seconds']:>6.1f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
