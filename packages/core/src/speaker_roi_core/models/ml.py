"""Model registry: specifications, versions, metrics, calibration and drift.

Three of the four models in docs/PLAN_REVIEW.md F-1 live here. The fourth - M2,
the causal estimator - deliberately does not: it is a statistical procedure
applied to a versioned specification (``analytics.estimator_specs``), and forcing
it through a train/validate/promote lifecycle was one of the confusions in the
original plan.

The registry is authoritative in PostgreSQL (docs/PLAN_REVIEW.md F-5). Artifacts
live in object storage; this schema holds the pointer, the checksum and the
evidence that the artifact earned its ``ACTIVE`` state. That ordering matters:
if the registry were a directory listing, "which model produced this number in
March" would be answerable only by hoping nobody moved a file.

Two invariants are enforced in the database rather than in service code:

**At most one ACTIVE version per (tenant, model kind, brand).** A partial unique
index does this. Two active champions is not a state the application can be
allowed to reach, because scoring picks one arbitrarily and the reported number
becomes irreproducible.

**Promotion is a recorded decision, not a column update.** ``model_promotions``
is append-only and captures who promoted what, against which challenger, on which
metrics. Rollback is a new promotion row, never an edit.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from speaker_roi_core.db.base import (
    ActorMixin,
    Base,
    TenantMixin,
    TimestampMixin,
    VersionMixin,
    tenant_code_unique,
    tenant_lookup_index,
    uuid_pk,
)
from speaker_roi_core.db.types import (
    JSONB,
    Fraction,
    Measure,
    Quantity,
    Sha256,
    pg_enum,
)
from speaker_roi_core.enums import ModelKind, ModelLifecycleState


class ModelSpec(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """The training recipe for one model: features, target, split and gates.

    Separated from :class:`ModelVersion` because a spec is edited over months
    while versions are produced from it weekly. Keeping the promotion gates on
    the spec means the bar is set *before* a candidate is trained, which is the
    only ordering that makes the bar meaningful.
    """

    __tablename__ = "model_specs"
    __table_args__ = (
        tenant_code_unique("model_specs", "code"),
        tenant_lookup_index("model_specs", "model_kind", "is_active"),
        CheckConstraint("holdout_months >= 1", name="holdout_months_positive"),
        CheckConstraint("min_training_rows >= 1", name="min_training_rows_positive"),
        {"schema": "ml"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_kind: Mapped[ModelKind] = mapped_column(pg_enum(ModelKind), nullable=False)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    algorithm: Mapped[str] = mapped_column(String(60), nullable=False, default="lightgbm")
    #: LightGBM objective. Tweedie for attendance/reach counts (M4) because they
    #: are non-negative with a mass at zero; binary for propensity (M1);
    #: regression_l2 with inverse-variance weights for impact (M3).
    objective: Mapped[str | None] = mapped_column(String(60), nullable=True)
    hyperparameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    target_definition: Mapped[str] = mapped_column(String(200), nullable=False)
    feature_set: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    #: Features that must never enter this model. For M3 this includes anything
    #: derived from post-event outcomes - the leak that turns a forecaster into a
    #: very confident hindsight machine.
    forbidden_features: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    #: Splits are temporal, never random. A random split lets the model see
    #: future months while predicting past ones and reports an accuracy the
    #: product will never reproduce in use.
    split_strategy: Mapped[str] = mapped_column(String(40), nullable=False, default="temporal")
    holdout_months: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=6)
    calibration_months: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=6)
    min_training_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=200)

    #: Metric name -> threshold a challenger must clear to be promotable. Stored
    #: so the promotion decision is checkable after the fact.
    promotion_gates: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: Target miscoverage for the conformal interval (0.20 -> 80% intervals).
    conformal_alpha: Mapped[float] = mapped_column(Fraction, nullable=False, default=0.20)
    #: Hierarchy used for empirical-Bayes pooling, coarsest last. M3 walks this
    #: until a cell has enough effective sample size, then blends.
    pooling_hierarchy: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    #: Minimum effective sample size before a cell's own mean is trusted over the
    #: pooled prior.
    min_effective_sample: Mapped[float] = mapped_column(Measure, nullable=False, default=5)

    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    versions: Mapped[list[ModelVersion]] = relationship(back_populates="spec")


class ModelVersion(Base, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """One trained artifact and its lifecycle state.

    ``training_data_versions`` and ``random_seed`` are what make a version
    reproducible; ``artifact_checksum`` is what makes it *verifiable*. A scoring
    run recomputes the checksum before loading, so a swapped or truncated artifact
    fails loudly instead of quietly producing different numbers.

    The partial unique index enforcing a single ACTIVE champion per
    (tenant, kind, brand) is created in the migration - SQLAlchemy's ``Index``
    with ``postgresql_where`` is used below so autogenerate stays consistent.
    """

    __tablename__ = "model_versions"
    __table_args__ = (
        tenant_code_unique("model_versions", "model_spec_id", "version_number"),
        tenant_lookup_index("model_versions", "model_kind", "lifecycle_state"),
        tenant_lookup_index("model_versions", "model_spec_id", "created_at"),
        Index(
            "uq_model_versions_single_active_champion",
            "tenant_id",
            "model_kind",
            "brand_id",
            unique=True,
            postgresql_where=text("lifecycle_state = 'ACTIVE'"),
        ),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint(
            "lifecycle_state <> 'ACTIVE' OR artifact_key IS NOT NULL",
            name="active_version_has_artifact",
        ),
        CheckConstraint(
            "lifecycle_state <> 'REJECTED' OR rejection_reason IS NOT NULL",
            name="rejected_version_states_reason",
        ),
        CheckConstraint(
            "training_rows IS NULL OR training_rows >= 0", name="training_rows_non_negative"
        ),
        {"schema": "ml"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    model_spec_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ml.model_specs.id", ondelete="RESTRICT"), nullable=False
    )
    #: Denormalised from the spec so the partial unique index above can be
    #: expressed without a join.
    model_kind: Mapped[ModelKind] = mapped_column(pg_enum(ModelKind), nullable=False)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    lifecycle_state: Mapped[ModelLifecycleState] = mapped_column(
        pg_enum(ModelLifecycleState), nullable=False, default=ModelLifecycleState.DRAFT
    )

    #: Object-storage key of the serialised model. Never a local path - the API
    #: and the worker do not share a filesystem in any real deployment.
    artifact_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    artifact_checksum: Mapped[str | None] = mapped_column(Sha256, nullable=True)
    artifact_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Library versions at training time. A LightGBM major upgrade can change
    #: predictions on an identical artifact, so "what produced this" includes the
    #: runtime.
    runtime_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    training_run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    training_data_versions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    random_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    code_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    hyperparameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    training_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calibration_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    train_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    train_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    holdout_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    holdout_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    #: True when every promotion gate on the spec passed. Stored rather than
    #: recomputed so a later threshold change cannot rewrite history.
    gates_passed: Mapped[bool | None] = mapped_column(nullable=True)
    gate_results: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    #: True when the model was trained on synthetic data. This propagates to
    #: every number it produces, because a demo tenant's forecast must never be
    #: mistaken for a measured result (plan.md §11).
    trained_on_synthetic: Mapped[bool] = mapped_column(nullable=False, default=False)
    #: Free-text limitations for the model card (plan.md §12.8).
    known_limitations: Mapped[str | None] = mapped_column(Text, nullable=True)

    spec: Mapped[ModelSpec] = relationship(back_populates="versions")
    metrics: Mapped[list[ModelMetric]] = relationship(
        back_populates="model_version", cascade="all, delete-orphan"
    )
    features: Mapped[list[ModelFeature]] = relationship(
        back_populates="model_version", cascade="all, delete-orphan"
    )


class ModelMetric(Base, TenantMixin, TimestampMixin):
    """One evaluated metric on one dataset split.

    Split is part of the key because a training-set AUC and a holdout AUC are
    different claims, and reporting the former as model quality is the most
    common way a model looks good until it ships.
    """

    __tablename__ = "model_metrics"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "model_version_id",
            "split",
            "metric_name",
            "segment",
            name="uq_model_metrics_grain",
        ),
        {"schema": "ml"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ml.model_versions.id", ondelete="CASCADE"), nullable=False
    )
    #: ``train`` | ``validation`` | ``holdout`` | ``calibration`` | ``live``.
    split: Mapped[str] = mapped_column(String(20), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(60), nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Measure, nullable=True)
    #: ``ALL`` or a slice label. Per-segment metrics are what reveal that a model
    #: performs well overall and badly for the smallest region.
    segment: Mapped[str] = mapped_column(String(120), nullable=False, default="ALL")
    n_observations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Threshold this metric was judged against, if it is a promotion gate.
    threshold: Mapped[float | None] = mapped_column(Measure, nullable=True)
    passed: Mapped[bool | None] = mapped_column(nullable=True)

    model_version: Mapped[ModelVersion] = relationship(back_populates="metrics")


class ModelFeature(Base, TenantMixin):
    """Feature inventory and importance for one version.

    Importance is stored at feature grain and never at prescriber grain, so the
    explanation panel can say "recent brand momentum contributed most" without
    ever assembling the ranked prescriber list that plan.md §7.4 prohibits.
    """

    __tablename__ = "model_features"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "model_version_id", "feature_name", name="uq_model_features_version_name"
        ),
        {"schema": "ml"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ml.model_versions.id", ondelete="CASCADE"), nullable=False
    )
    feature_name: Mapped[str] = mapped_column(String(120), nullable=False)
    #: ``numeric`` | ``categorical`` | ``ordinal`` | ``boolean``.
    dtype: Mapped[str | None] = mapped_column(String(20), nullable=True)
    importance: Mapped[float | None] = mapped_column(Measure, nullable=True)
    importance_rank: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    #: Training-set distribution, used at scoring time to decide whether an input
    #: is inside the support the model was fitted on.
    train_min: Mapped[float | None] = mapped_column(Measure, nullable=True)
    train_max: Mapped[float | None] = mapped_column(Measure, nullable=True)
    train_p01: Mapped[float | None] = mapped_column(Measure, nullable=True)
    train_p99: Mapped[float | None] = mapped_column(Measure, nullable=True)
    #: Category levels seen in training. An unseen level is an out-of-support
    #: signal, not a value to silently encode as "other".
    observed_categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    null_rate: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    #: Human-readable text for the explanation panel and the model card.
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    model_version: Mapped[ModelVersion] = relationship(back_populates="features")


class ConformalCalibration(Base, TenantMixin, TimestampMixin):
    """Split-conformal residual quantiles for one model version and segment.

    This is what turns M3's point prediction into an interval with an actual
    coverage guarantee. The alternative - a modelled variance - assumes the model
    is correctly specified, which is exactly the assumption a planning tool
    should not be making about its own forecasts.

    Segmented because residual spread differs by brand and format; a single
    global quantile produces intervals that are too wide where the model is good
    and too narrow where it is not.
    """

    __tablename__ = "conformal_calibration"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "model_version_id",
            "segment",
            "alpha",
            name="uq_conformal_calibration_grain",
        ),
        CheckConstraint("alpha > 0 AND alpha < 1", name="alpha_is_proper_fraction"),
        CheckConstraint("n_calibration >= 0", name="n_calibration_non_negative"),
        CheckConstraint(
            "quantile_low IS NULL OR quantile_high IS NULL OR quantile_high >= quantile_low",
            name="quantiles_ordered",
        ),
        {"schema": "ml"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ml.model_versions.id", ondelete="CASCADE"), nullable=False
    )
    segment: Mapped[str] = mapped_column(String(120), nullable=False, default="ALL")
    alpha: Mapped[float] = mapped_column(Fraction, nullable=False, default=0.20)
    #: Residual quantiles at alpha/2 and 1 - alpha/2.
    quantile_low: Mapped[float | None] = mapped_column(Measure, nullable=True)
    quantile_high: Mapped[float | None] = mapped_column(Measure, nullable=True)
    n_calibration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Coverage actually achieved on the holdout. If this is materially below
    #: ``1 - alpha`` the intervals are lying and the version fails its gate.
    empirical_coverage: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    mean_interval_width: Mapped[float | None] = mapped_column(Measure, nullable=True)
    #: Below this calibration count the segment falls back to the global
    #: quantiles rather than fitting noise.
    is_fallback: Mapped[bool] = mapped_column(nullable=False, default=False)


class PooledPrior(Base, TenantMixin, TimestampMixin):
    """Empirical-Bayes prior for one pooling cell.

    M3's answer to the cold-start problem. A brand-topic-region cell with four
    historical events has a mean that is mostly noise; shrinking it toward the
    coarser cell's mean produces a usable estimate and, crucially, an
    ``n_effective`` that tells the planner how much to trust it.

    Cells are stored rather than recomputed at request time so a forecast can
    name the exact prior it used, and so "based on 11 similar events" is a fact
    rather than a paraphrase.
    """

    __tablename__ = "pooled_priors"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "model_version_id",
            "level",
            "cell_key",
            name="uq_pooled_priors_grain",
        ),
        CheckConstraint("n_observations >= 0", name="n_observations_non_negative"),
        {"schema": "ml"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ml.model_versions.id", ondelete="CASCADE"), nullable=False
    )
    #: Position in the pooling hierarchy, 0 being the finest cell.
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    #: Composite key of the cell, e.g. ``brand=CARDIOMAX|topic=HF|region=WEST``.
    cell_key: Mapped[str] = mapped_column(String(300), nullable=False)
    parent_cell_key: Mapped[str | None] = mapped_column(String(300), nullable=True)

    prior_mean: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    prior_variance: Mapped[float | None] = mapped_column(Measure, nullable=True)
    #: Raw cell mean before shrinkage, kept so the shrinkage is inspectable.
    raw_mean: Mapped[float | None] = mapped_column(Quantity, nullable=True)
    shrinkage_weight: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    #: Number of contributing estimates, and their inverse-variance-weighted
    #: effective count. The two differ sharply when a few precise estimates sit
    #: alongside many imprecise ones, which is the normal case here.
    n_observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_effective: Mapped[float | None] = mapped_column(Measure, nullable=True)
    #: Grade mix of the contributing estimates. A prior built only from
    #: DIRECTIONAL evidence is flagged and caps the forecast's own confidence.
    evidence_mix: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class ModelPromotion(Base, TenantMixin):
    """Append-only record of a champion change.

    plan.md §12.8 requires a promotion decision to be auditable and reversible.
    Reversal is a new row with ``is_rollback``, never an edit - "what was live on
    the 14th" must stay answerable after someone reverts on the 15th.
    """

    __tablename__ = "model_promotions"
    __rls__: ClassVar[str | None] = "append_only"
    __table_args__ = (
        tenant_lookup_index("model_promotions", "model_version_id", "created_at"),
        tenant_lookup_index("model_promotions", "model_kind", "created_at"),
        {"schema": "ml"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ml.model_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    model_kind: Mapped[ModelKind] = mapped_column(pg_enum(ModelKind), nullable=False)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    #: The version this one displaced. Null for the first champion.
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    from_state: Mapped[ModelLifecycleState | None] = mapped_column(
        pg_enum(ModelLifecycleState), nullable=True
    )
    to_state: Mapped[ModelLifecycleState] = mapped_column(
        pg_enum(ModelLifecycleState), nullable=False
    )
    decided_by: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    is_rollback: Mapped[bool] = mapped_column(nullable=False, default=False)
    #: Required when promoting a version that did not clear every gate.
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Champion-vs-challenger comparison at decision time.
    comparison: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DriftSnapshot(Base, TenantMixin, TimestampMixin):
    """Input and prediction drift for an active model version.

    plan.md §12.8 requires monitoring, and the honest framing is that a model
    silently degrades: nothing errors, the numbers just stop being right. Feature
    drift catches the input distribution moving; prediction drift catches the
    output moving; realised error - only computable once outcomes arrive - is the
    one that actually settles the question, months later.
    """

    __tablename__ = "drift_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "model_version_id",
            "computed_at",
            "feature_name",
            name="uq_drift_snapshots_grain",
        ),
        tenant_lookup_index("drift_snapshots", "breached"),
        {"schema": "ml"},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ml.model_versions.id", ondelete="CASCADE"), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    #: ``ALL`` for the aggregate prediction-drift row, otherwise a feature name.
    feature_name: Mapped[str] = mapped_column(String(120), nullable=False, default="ALL")
    #: Population stability index against the training distribution.
    psi: Mapped[float | None] = mapped_column(Measure, nullable=True)
    kolmogorov_smirnov: Mapped[float | None] = mapped_column(Measure, nullable=True)
    null_rate_delta: Mapped[float | None] = mapped_column(Measure, nullable=True)
    #: Share of scoring requests that fell outside training support. A rising
    #: value means the world moved, not that the users got adventurous.
    out_of_support_rate: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    prediction_mean: Mapped[float | None] = mapped_column(Measure, nullable=True)
    prediction_mean_baseline: Mapped[float | None] = mapped_column(Measure, nullable=True)
    #: Error against outcomes that have since been observed. Null until the
    #: forecast horizon has elapsed.
    realised_mae: Mapped[float | None] = mapped_column(Measure, nullable=True)
    realised_coverage: Mapped[float | None] = mapped_column(Fraction, nullable=True)
    n_scored: Mapped[int | None] = mapped_column(Integer, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Measure, nullable=True)
    breached: Mapped[bool] = mapped_column(nullable=False, default=False)


__all__ = [  # noqa: RUF022 - grouped by concern, not alphabetised
    "ModelSpec",
    "ModelVersion",
    "ModelMetric",
    "ModelFeature",
    "ConformalCalibration",
    "PooledPrior",
    "ModelPromotion",
    "DriftSnapshot",
]
