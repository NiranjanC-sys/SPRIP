"""Every mapped class, imported for its side effect on ``Base.metadata``.

Alembic autogenerate and the RLS/invariant tests both walk ``Base.metadata``. A
model module that nobody imports contributes no tables, so its migration silently
never happens and its RLS policy silently never exists. Importing all of them
here, in one place, is what makes "the metadata is complete" a property of the
package rather than of whichever module a caller happened to touch first.

Import order follows the foreign-key dependency order (``core`` owns
``tenants``, which every other schema references), so a plain ``import`` of this
module never trips SQLAlchemy's deferred-resolution machinery.
"""

from __future__ import annotations

from speaker_roi_core.db.base import Base, metadata_obj, sync_server_defaults
from speaker_roi_core.models.analytics import (
    AiInteraction,
    AnalysisRun,
    Cohort,
    CohortMember,
    DataHealthSnapshot,
    EstimatorSpec,
    EventImpact,
    EventImpactGate,
    EventStudyPoint,
    Forecast,
    OptimizerRun,
    PortfolioAggregate,
    PropensityScore,
    Review,
    RoiResult,
    Scenario,
    ScenarioAllocation,
    ScenarioConstraint,
    SensitivityResult,
)
from speaker_roi_core.models.audit import (
    AuditEvent,
    ErasureRequest,
    ExportLog,
    RetentionPolicyRun,
)
from speaker_roi_core.models.auth import (
    ApiKey,
    DelegatedAccessGrant,
    IdentityProvider,
    Invitation,
    LoginAttempt,
    Membership,
    MembershipBrandScope,
    MembershipVendorScope,
    PasswordResetToken,
    Session,
    User,
)
from speaker_roi_core.models.core import (
    UNATTRIBUTED_BRAND_ID,
    Attendance,
    Brand,
    Campaign,
    CandidateProgram,
    Currency_,
    Event,
    EventCost,
    EventInvitation,
    EventSpeaker,
    EventWorkflowTransition,
    FeatureFlag,
    FinanceAssumption,
    FinanceVersion,
    FxRate,
    Hcp,
    HcpIdentifier,
    HcpRxMonthly,
    MarketFactor,
    MarketingActivity,
    Notification,
    Product,
    SavedView,
    TaxonomyValue,
    Tenant,
    Vendor,
    VendorDatasetGrant,
)
from speaker_roi_core.models.ingestion import (
    ColumnMappingTemplate,
    DatasetContract,
    DataVersion,
    IdentityResolutionTask,
    QuarantineRow,
    RawObject,
    UploadIssue,
    UploadSession,
)
from speaker_roi_core.models.ml import (
    ConformalCalibration,
    DriftSnapshot,
    ModelFeature,
    ModelMetric,
    ModelPromotion,
    ModelSpec,
    ModelVersion,
    PooledPrior,
)

# Every scalar Python default is mirrored into a SQL ``DEFAULT`` now that all
# tables exist. Deliberately at import time and not in a migration hook: the
# generated DDL, `alembic autogenerate`'s comparison and the live database then
# all read from the same source, so a drift between them is not expressible.
SERVER_DEFAULTS_APPLIED: tuple[str, ...] = tuple(sync_server_defaults(metadata_obj))


__all__ = [  # noqa: RUF022 - grouped by schema, which is how these are reasoned about
    "Base",
    "metadata_obj",
    # auth
    "ApiKey",
    "DelegatedAccessGrant",
    "IdentityProvider",
    "Invitation",
    "LoginAttempt",
    "Membership",
    "MembershipBrandScope",
    "MembershipVendorScope",
    "PasswordResetToken",
    "Session",
    "User",
    # core
    "UNATTRIBUTED_BRAND_ID",
    "Attendance",
    "Brand",
    "Campaign",
    "CandidateProgram",
    "Currency_",
    "Event",
    "EventCost",
    "EventInvitation",
    "EventSpeaker",
    "EventWorkflowTransition",
    "FeatureFlag",
    "FinanceAssumption",
    "FinanceVersion",
    "FxRate",
    "Hcp",
    "HcpIdentifier",
    "HcpRxMonthly",
    "MarketFactor",
    "MarketingActivity",
    "Notification",
    "Product",
    "SavedView",
    "TaxonomyValue",
    "Tenant",
    "Vendor",
    "VendorDatasetGrant",
    # ingestion
    "ColumnMappingTemplate",
    "DataVersion",
    "DatasetContract",
    "IdentityResolutionTask",
    "QuarantineRow",
    "RawObject",
    "UploadIssue",
    "UploadSession",
    # analytics
    "AiInteraction",
    "AnalysisRun",
    "Cohort",
    "CohortMember",
    "DataHealthSnapshot",
    "EstimatorSpec",
    "EventImpact",
    "EventImpactGate",
    "EventStudyPoint",
    "Forecast",
    "OptimizerRun",
    "PortfolioAggregate",
    "PropensityScore",
    "Review",
    "RoiResult",
    "Scenario",
    "ScenarioAllocation",
    "ScenarioConstraint",
    "SensitivityResult",
    # ml
    "ConformalCalibration",
    "DriftSnapshot",
    "ModelFeature",
    "ModelMetric",
    "ModelPromotion",
    "ModelSpec",
    "ModelVersion",
    "PooledPrior",
    # audit
    "AuditEvent",
    "ErasureRequest",
    "ExportLog",
    "RetentionPolicyRun",
]
