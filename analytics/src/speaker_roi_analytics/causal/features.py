"""Pre-event covariates for the propensity model.

One invariant governs this whole module: **every column here is knowable strictly
before the event date.** ``pre6m`` means month offsets ``[-6, -1]``; the event
month is excluded, because attendance happens partway through it and any quantity
measured over it is part outcome. A single post-event column in this table would
leak the outcome into treatment assignment, and the failure is silent in the worst
possible way - the recovered ATT gets *better*, balance looks immaculate, and every
gate goes green while the estimate means nothing. So the invariant is asserted
(:func:`assert_no_leakage`) rather than merely intended.

What to include, and why not everything
---------------------------------------
The propensity model's job is not to predict attendance as accurately as possible.
It is to make attendees and non-attendees comparable on the things that also drive
prescribing. Those are different objectives, and conflating them causes real harm:
a variable that predicts attendance but is unrelated to the outcome adds variance
to the matched estimate without removing bias, and an *instrument* - something
affecting attendance only - actively amplifies whatever bias remains. So the
feature set here mirrors the confounders, not the best available predictors.

The columns are the observable half of the true selection model in
``synthetic/exposure.py``: baseline prescribing level and trend, topic fit, prior
engagement, recent field activity, travel friction and competing-event pressure.
The latent half of that model (opportunity and affinity, combined weight 0.80 +
0.65 against the observable level's 0.55) is by construction absent from every
frame the platform can read. That is not a gap to be closed - it is the residual
confounding that survives matching, and bounding it is the sensitivity suite's
job (``UNMEASURED_CONFOUNDER_BOUND``). Any analysis here that appeared to recover
the truth exactly would be evidence of a leak, not of success.

Missing values are left as NaN rather than imputed. LightGBM learns a split
direction for missingness, which is the honest treatment: "this prescriber has no
field-activity record" is information, and imputing a mean would assert an
average call volume the data never observed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import structlog

from .panel import Cohort, PanelFrames

__all__ = [
    "BASELINE_WINDOW_LEVELS",
    "FEATURE_COLUMNS",
    "MATCHING_COVARIATES",
    "PROPENSITY_COLUMNS",
    "assert_no_leakage",
    "build_features",
]

_LOG = structlog.get_logger(__name__)

#: Every covariate offered to the propensity model, in a fixed order so a stored
#: model's feature vector cannot be reassembled differently at scoring time.
FEATURE_COLUMNS: tuple[str, ...] = (
    # Baseline prescribing - the observable confounder matching exists to handle.
    "pre_nrx_mean",
    #: Level over the *earlier*, disjoint window. This is what matching balances
    #: on; ``pre_nrx_mean`` is what the baseline is computed from. See
    #: :attr:`~.spec.EstimatorSpec.anchor_window_months` for the measured reason
    #: those must not be the same window.
    "anchor_nrx_mean",
    "anchor_months_observed",
    "pre_nrx_trend",
    "pre_nrx_volatility",
    "pre_trx_mean",
    #: Total-prescription level over the anchor window, standing in for
    #: ``pre_trx_mean`` in the propensity model for the same reason
    #: ``anchor_nrx_mean`` stands in for ``pre_nrx_mean``.
    "anchor_trx_mean",
    "pre_competitor_share",
    "pre_months_observed",
    # Engagement history, which drives both invitation and prescribing.
    "prior_engagement_count",
    "pre_rep_calls",
    "pre_emails",
    "pre_samples",
    # Prescriber attributes.
    "decile",
    "years_in_practice",
    "is_target_specialty",
    "specialty_matches_topic",
    # Event-side friction. Affects attendance strongly; included because it also
    # correlates with region, and region drives access and competitor pressure.
    "is_local_venue",
    "competing_events_same_month",
    "event_size_planned",
    # Prior exposure, observable from the attendance record.
    "prior_same_brand_attendances",
    "months_since_last_attendance",
)

#: Own-volume levels measured over the **baseline window** - the same months the
#: DiD subtracts as each unit's pre-period level.
#:
#: These are excluded from :data:`PROPENSITY_COLUMNS`, and the exclusion is
#: load-bearing rather than tidy-minded. A realised window mean is a noisy proxy
#: for the prescriber's underlying level, and the two errors are the same draw: if
#: matching equalises the realised baseline, the controls it selects for a
#: genuinely higher-prescribing attendee are drawn from the top of their own
#: month-to-month noise. They revert over the post window while the attendee does
#: not, and the difference-in-differences reads the reversion as impact. Balancing
#: the *earlier*, disjoint window instead carries no information about the baseline
#: window's noise, so there is nothing to borrow.
#:
#: Restricting the volume caliper is not sufficient on its own: the propensity
#: score is itself a function of its inputs, so leaving a baseline-window level in
#: the model re-imports the same noise through the score. Measured on five seeds,
#: with the caliper already moved to the anchor window but these columns still in
#: the model, the baseline-window SMD was still pulled to 0.102-0.138 while the
#: anchor window sat at 0.033-0.049 - matching was still partly chasing the
#: baseline - and the per-seed estimate swung between 0.4x and 2.5x the known truth.
#:
#: They remain in :data:`FEATURE_COLUMNS` because the estimator needs
#: ``pre_nrx_mean`` as its offset and the balance table reports both with their
#: reasons. Excluded from the *model*, not from the record.
BASELINE_WINDOW_LEVELS: tuple[str, ...] = (
    "pre_nrx_mean",
    "pre_trx_mean",
)

#: What the propensity model actually sees: :data:`FEATURE_COLUMNS` less the
#: baseline-window levels. Derived by filtering rather than written out, so the two
#: lists cannot drift, and order is inherited so a stored model's feature vector
#: cannot be reassembled differently at scoring time.
PROPENSITY_COLUMNS: tuple[str, ...] = tuple(
    column for column in FEATURE_COLUMNS if column not in BASELINE_WINDOW_LEVELS
)

#: The subset whose post-matching balance is reported and gated. Deliberately
#: narrower than :data:`FEATURE_COLUMNS`: balance is required on the confounders,
#: and demanding it on a pure attendance predictor would fail matched sets that are
#: in fact perfectly adequate for the estimate. It *includes* the baseline-window
#: levels the model no longer sees - they are reported with the role that says who
#: is responsible for them instead of being quietly omitted.
MATCHING_COVARIATES: tuple[str, ...] = (
    "anchor_nrx_mean",
    "anchor_trx_mean",
    "pre_nrx_mean",
    "pre_nrx_trend",
    "pre_trx_mean",
    "pre_competitor_share",
    "prior_engagement_count",
    "pre_rep_calls",
    "decile",
    "years_in_practice",
    "prior_same_brand_attendances",
)


def assert_no_leakage(features: pd.DataFrame, cohort: Cohort) -> None:
    """Fail loudly if a feature could only be known after the event.

    Two checks, both cheap enough to run on every build.

    The first is structural: the frame must not carry an outcome column. Nothing
    stops a future edit from merging ``post_mean`` in as a convenience and
    forgetting it is the answer.

    The second is statistical, and catches the subtler version. A feature that
    secretly encodes the outcome will correlate with the *post-period* outcome far
    more strongly than any legitimate baseline does. Baseline prescribing is
    genuinely persistent, so a high correlation is expected and not suspicious by
    itself; near-perfect correlation is not persistence, it is the outcome wearing
    a different name.
    """
    forbidden = {"post_mean", "post_months", "outcome", "is_treated", "arm"}
    present = forbidden.intersection(features.columns)
    if present:
        raise ValueError(f"post-event columns leaked into the feature frame: {sorted(present)}")

    post = cohort.units.set_index(["event_id", "hcp_id"])["post_mean"]
    aligned = post.reindex(pd.MultiIndex.from_frame(features[["event_id", "hcp_id"]]))
    suspicious: list[tuple[str, float]] = []
    for column in FEATURE_COLUMNS:
        if column not in features:
            continue
        values = features[column].to_numpy(dtype=float)
        target = aligned.to_numpy(dtype=float)
        ok = ~(np.isnan(values) | np.isnan(target))
        if ok.sum() < 30 or np.std(values[ok]) == 0:
            continue
        r = abs(float(np.corrcoef(values[ok], target[ok])[0, 1]))
        if r > 0.995:
            suspicious.append((column, r))
    if suspicious:
        raise ValueError(
            "feature(s) correlate with the post-period outcome almost perfectly, "
            f"which is leakage rather than persistence: {suspicious}"
        )


def _window_stats(cohort: Cohort) -> pd.DataFrame:
    """Baseline level, trend and volatility from the pre-window monthly panel.

    The trend is an ordinary least-squares slope in *log* space, per month. Logs
    for the same reason the pre-trend diagnostic uses them: the outcome is
    multiplicative, so a level-space slope for a 100-script prescriber and a
    10-script prescriber describe different things even when both are growing at
    the same rate, and the propensity model would then be matching on volume
    twice instead of on volume and growth.
    """
    pre = cohort.monthly[cohort.monthly["offset"] < 0]
    if pre.empty:
        return pd.DataFrame(columns=["event_id", "hcp_id", "pre_nrx_trend", "pre_nrx_volatility"])

    logged = pre.assign(log_outcome=np.log1p(pre["outcome"]))

    def slope(group: pd.DataFrame) -> float:
        x = group["offset"].to_numpy(dtype=float)
        if x.size < 2 or np.ptp(x) == 0:
            return np.nan
        y = group["log_outcome"].to_numpy(dtype=float)
        return float(np.polyfit(x, y, 1)[0])

    grouped = logged.groupby(["event_id", "hcp_id"])
    out = grouped.apply(slope, include_groups=False).rename("pre_nrx_trend").reset_index()
    vol = grouped["log_outcome"].std().rename("pre_nrx_volatility").reset_index()
    return out.merge(vol, on=["event_id", "hcp_id"], how="outer")


def _pre_window_sum(
    units: pd.DataFrame, source: pd.DataFrame, columns: dict[str, str], months: int
) -> pd.DataFrame:
    """Sum ``source`` columns over the ``months`` before each unit's event month.

    ``source`` is keyed on (hcp_id, mi). The join is on the prescriber, then
    filtered by offset, which is why it must never be given a frame containing the
    event month or later.
    """
    joined = units[["event_id", "hcp_id", "event_month_index"]].merge(
        source, on="hcp_id", how="left"
    )
    offset = joined["mi"] - joined["event_month_index"]
    inside = joined[(offset >= -months) & (offset <= -1)]
    agg = inside.groupby(["event_id", "hcp_id"], as_index=False)[list(columns)].sum()
    return agg.rename(columns=columns)


def build_features(cohort: Cohort, frames: PanelFrames) -> pd.DataFrame:
    """One row per cohort unit, with :data:`FEATURE_COLUMNS` and the join keys.

    Returned in the cohort's own row order, so the feature matrix and the
    treatment vector cannot drift apart.
    """
    units = cohort.units
    out = units[["tenant_id", "event_id", "hcp_id", "brand_id", "event_month_index"]].copy()

    # --- outcome-panel baselines -----------------------------------------
    out["pre_nrx_mean"] = units["pre_mean"].to_numpy()
    out["pre_months_observed"] = units["pre_months"].to_numpy()
    stats = _window_stats(cohort)
    out = out.merge(stats, on=["event_id", "hcp_id"], how="left")

    # The anchor level: the same quantity as ``pre_nrx_mean``, measured over a window
    # that does not overlap it. Matching balances this one. A unit with no anchor
    # history gets NaN rather than a fallback to the baseline window - falling back
    # would silently reinstate exactly the noise-borrowing the anchor window exists
    # to prevent, for the subset of units least able to afford it.
    anchor = cohort.anchor
    if anchor.empty:
        out["anchor_nrx_mean"] = np.nan
        out["anchor_months_observed"] = 0
    else:
        anchor_agg = anchor.groupby(["event_id", "hcp_id"], as_index=False).agg(
            anchor_nrx_mean=("outcome", "mean"), anchor_months_observed=("outcome", "size")
        )
        out = out.merge(anchor_agg, on=["event_id", "hcp_id"], how="left")
        out["anchor_months_observed"] = out["anchor_months_observed"].fillna(0).astype(int)
        # Too thin a series is not a level, it is a month or two of noise wearing a
        # level's name, and it would be a worse caliper target than the baseline.
        thin = out["anchor_months_observed"] < cohort.spec.min_anchor_months
        out.loc[thin, "anchor_nrx_mean"] = np.nan

    rx = frames.rx_monthly
    observed = rx[rx["is_observed"] & ~rx["suppression_flag"].astype(bool)]
    wide = observed.groupby(["hcp_id", "brand_id", "month"], as_index=False)[
        ["trx", "competitor_trx"]
    ].sum()
    wide["mi"] = month_index_of(wide["month"], frames)
    joined = out[["event_id", "hcp_id", "brand_id", "event_month_index"]].merge(
        wide, on=["hcp_id", "brand_id"], how="left"
    )
    offset = joined["mi"] - joined["event_month_index"]
    pre_rx = joined[(offset >= -cohort.spec.pre_window_months) & (offset <= -1)]
    rx_agg = pre_rx.groupby(["event_id", "hcp_id"], as_index=False).agg(
        pre_trx_mean=("trx", "mean"), _competitor=("competitor_trx", "sum"), _own=("trx", "sum")
    )
    # Share rather than level: a competitor's absolute volume mostly measures how
    # big the prescriber is, which ``pre_trx_mean`` already carries.
    denominator = rx_agg["_competitor"] + rx_agg["_own"]
    rx_agg["pre_competitor_share"] = np.where(
        denominator > 0, rx_agg["_competitor"] / denominator, np.nan
    )
    out = out.merge(
        rx_agg[["event_id", "hcp_id", "pre_trx_mean", "pre_competitor_share"]],
        on=["event_id", "hcp_id"],
        how="left",
    )

    # The same level over the anchor window. This is the column the propensity model
    # sees; ``pre_trx_mean`` above is reported but withheld from the model. See
    # :data:`BASELINE_WINDOW_LEVELS` for why, and note the offsets are re-derived
    # from the spec rather than reusing ``pre_rx`` - the two windows must not overlap
    # and a shared slice is how that would quietly stop being true.
    anchor_offsets = cohort.spec.anchor_offsets
    anchor_rx = joined[offset.isin(anchor_offsets)]
    if anchor_rx.empty:
        out["anchor_trx_mean"] = np.nan
    else:
        anchor_trx = anchor_rx.groupby(["event_id", "hcp_id"], as_index=False).agg(
            anchor_trx_mean=("trx", "mean"), _months=("trx", "size")
        )
        # Same thinness rule as the NRx anchor: a month or two is not a level.
        anchor_trx.loc[anchor_trx["_months"] < cohort.spec.min_anchor_months, "anchor_trx_mean"] = (
            np.nan
        )
        out = out.merge(
            anchor_trx[["event_id", "hcp_id", "anchor_trx_mean"]],
            on=["event_id", "hcp_id"],
            how="left",
        )

    # --- field activity ---------------------------------------------------
    marketing = frames.marketing_activity.copy()
    marketing["mi"] = month_index_of(marketing["month"], frames)
    activity = _pre_window_sum(
        out,
        marketing[["hcp_id", "mi", "rep_calls", "emails_delivered", "samples_dropped"]],
        {
            "rep_calls": "pre_rep_calls",
            "emails_delivered": "pre_emails",
            "samples_dropped": "pre_samples",
        },
        months=3,
    )
    out = out.merge(activity, on=["event_id", "hcp_id"], how="left")

    # --- prescriber attributes -------------------------------------------
    hcp_cols = ["hcp_id", "specialty_code", "decile", "years_in_practice", "prior_engagement_count"]
    out = out.merge(frames.hcps[hcp_cols], on="hcp_id", how="left")

    invites = frames.invitations[["event_id", "hcp_id", "is_target_specialty"]].drop_duplicates(
        ["event_id", "hcp_id"]
    )
    out = out.merge(invites, on=["event_id", "hcp_id"], how="left")
    out["is_target_specialty"] = out["is_target_specialty"].astype("float64")

    # --- event-side friction ---------------------------------------------
    event_cols = ["event_id", "region_code", "topic_code", "planned_attendees", "event_month_index"]
    events = frames.events[event_cols].rename(columns={"region_code": "event_region"})
    out = out.merge(events.drop(columns=["event_month_index"]), on="event_id", how="left")
    hcp_region = frames.hcps.set_index("hcp_id")["region_code"]
    out["is_local_venue"] = (
        out["hcp_id"].map(hcp_region).to_numpy() == out["event_region"].to_numpy()
    ).astype("float64")
    out["event_size_planned"] = out["planned_attendees"].astype("float64")

    # Topic fit: the true selection model weights specialty-topic alignment at
    # 0.40, and it is observable, so the propensity model gets it. Encoded as a
    # match indicator against the topic's own target specialty rather than as a
    # high-cardinality interaction, which would be a per-cell mean with a handful
    # of observations behind it.
    topic_specialty = _topic_target_specialty(frames)
    out["specialty_matches_topic"] = (
        out["topic_code"].map(topic_specialty).to_numpy() == out["specialty_code"].to_numpy()
    ).astype("float64")

    per_month = (
        frames.events.groupby(["region_code", "event_month_index"], as_index=False)
        .size()
        .rename(columns={"size": "competing_events_same_month"})
    )
    out = out.merge(
        per_month,
        left_on=["event_region", "event_month_index"],
        right_on=["region_code", "event_month_index"],
        how="left",
    ).drop(columns=["region_code"])

    # --- prior exposure ---------------------------------------------------
    out = out.merge(_prior_attendance(out, frames), on=["event_id", "hcp_id"], how="left")
    out["prior_same_brand_attendances"] = out["prior_same_brand_attendances"].fillna(0.0)

    for column in FEATURE_COLUMNS:
        if column not in out:
            raise AssertionError(f"feature {column!r} was declared but never built")
        out[column] = pd.to_numeric(out[column], errors="coerce")

    out = out[["tenant_id", "event_id", "hcp_id", "brand_id", *FEATURE_COLUMNS]]
    out = out.drop_duplicates(["event_id", "hcp_id"]).reset_index(drop=True)
    assert_no_leakage(out, cohort)
    _LOG.info(
        "causal.features.built",
        units=len(out),
        features=len(FEATURE_COLUMNS),
        missing_rate=float(out[list(FEATURE_COLUMNS)].isna().to_numpy().mean()),
    )
    return out


def month_index_of(months: pd.Series, frames: PanelFrames) -> pd.Series:
    """``month_index`` against the frames' own anchor, for local convenience."""
    from .panel import month_index

    return month_index(months, frames.anchor)


def _topic_target_specialty(frames: PanelFrames) -> pd.Series:
    """The modal specialty among each topic's target-specialty invitees.

    Derived from the data rather than from a hardcoded mapping, so it works
    against a tenant's own taxonomy without this module knowing it.
    """
    invites = frames.invitations[["event_id", "hcp_id", "is_target_specialty"]]
    joined = invites.merge(frames.events[["event_id", "topic_code"]], on="event_id", how="inner")
    joined = joined.merge(frames.hcps[["hcp_id", "specialty_code"]], on="hcp_id", how="left")
    targeted = joined[joined["is_target_specialty"].astype(bool)]
    if targeted.empty:
        return pd.Series(dtype=object)
    modes = targeted.groupby("topic_code")["specialty_code"].agg(
        lambda s: s.mode().iloc[0] if not s.mode().empty else None
    )
    return modes


def _prior_attendance(units: pd.DataFrame, frames: PanelFrames) -> pd.DataFrame:
    """Count of, and recency of, earlier verified same-brand attendances.

    Strictly earlier: the offset filter is ``< 0``, so the unit's own attendance
    at the event under analysis cannot count itself. That mistake would make the
    feature a perfect predictor of treatment and the propensity model would
    collapse to it.
    """
    att = frames.attendance
    verified = att.loc[att["is_verified"].astype(bool), ["event_id", "hcp_id"]].drop_duplicates()
    other = verified.merge(
        frames.events[["event_id", "brand_id", "event_month_index"]], on="event_id", how="inner"
    ).rename(columns={"event_id": "other_event_id", "event_month_index": "other_month"})

    subject = units[["event_id", "hcp_id", "brand_id", "event_month_index"]]
    joined = subject.merge(other, on=["hcp_id", "brand_id"], how="left")
    gap = joined["other_month"] - joined["event_month_index"]
    earlier = joined[(gap < 0).fillna(False)].assign(gap=gap[(gap < 0).fillna(False)])
    if earlier.empty:
        return pd.DataFrame(
            columns=[
                "event_id",
                "hcp_id",
                "prior_same_brand_attendances",
                "months_since_last_attendance",
            ]
        )
    agg = earlier.groupby(["event_id", "hcp_id"], as_index=False).agg(
        prior_same_brand_attendances=("other_event_id", "nunique"),
        months_since_last_attendance=("gap", "max"),
    )
    # Positive months-ago reads more naturally than a negative offset.
    agg["months_since_last_attendance"] = -agg["months_since_last_attendance"]
    return agg
