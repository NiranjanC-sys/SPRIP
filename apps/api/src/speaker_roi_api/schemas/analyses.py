"""Analysis, impact, forecast and scenario schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import Field

from speaker_roi_api.schemas.common import AuditStamp, Schema


class AnalysisRunCreate(Schema):
    brand_id: uuid.UUID = Field(validation_alias="brandId")
    analysis_type: str = Field(validation_alias="analysisType", max_length=60)
    config: dict | None = None


class AnalysisRunOut(Schema):
    id: uuid.UUID
    brand_id: uuid.UUID = Field(serialization_alias="brandId")
    analysis_type: str = Field(serialization_alias="analysisType")
    status: str
    started_at: datetime | None = Field(default=None, serialization_alias="startedAt")
    completed_at: datetime | None = Field(default=None, serialization_alias="completedAt")
    config: dict | None = None
    result_summary: dict | None = Field(default=None, serialization_alias="resultSummary")
    audit: AuditStamp | None = None


class EventImpactOut(Schema):
    id: uuid.UUID
    event_id: uuid.UUID = Field(serialization_alias="eventId")
    run_id: uuid.UUID = Field(serialization_alias="runId")
    brand_id: uuid.UUID | None = Field(default=None, serialization_alias="brandId")
    outcome_metric: str = Field(serialization_alias="outcomeMetric")
    att: float | None = None
    incremental_nrx: float | None = Field(default=None, serialization_alias="incrementalNrx")
    p_value: float | None = Field(default=None, serialization_alias="pValue")
    ci_low: float | None = Field(default=None, serialization_alias="ciLow")
    ci_high: float | None = Field(default=None, serialization_alias="ciHigh")
    evidence_status: str = Field(serialization_alias="evidenceStatus")
    evidence_grade: str = Field(serialization_alias="evidenceGrade")
    n_treated: int = Field(serialization_alias="nTreated")
    n_control: int = Field(serialization_alias="nControl")
    audit: AuditStamp | None = None


class ForecastOut(Schema):
    id: uuid.UUID
    run_id: uuid.UUID = Field(serialization_alias="runId")
    brand_id: uuid.UUID | None = Field(default=None, serialization_alias="brandId")
    scenario_id: uuid.UUID | None = Field(default=None, serialization_alias="scenarioId")
    candidate_program_id: uuid.UUID | None = Field(
        default=None, serialization_alias="candidateProgramId"
    )
    mode: str
    point_estimate: float | None = Field(default=None, serialization_alias="pointEstimate")
    pi_low: float | None = Field(default=None, serialization_alias="piLow")
    pi_high: float | None = Field(default=None, serialization_alias="piHigh")
    n_effective: float | None = Field(default=None, serialization_alias="nEffective")


class ScenarioCreate(Schema):
    code: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    brand_id: uuid.UUID | None = Field(default=None, validation_alias="brandId")
    horizon_start: date = Field(validation_alias="horizonStart")
    horizon_end: date = Field(validation_alias="horizonEnd")
    budget_total: float = Field(validation_alias="budgetTotal", ge=0)
    currency: str = Field(min_length=3, max_length=3)
    note: str | None = Field(default=None, max_length=500)


class ScenarioPatch(Schema):
    name: str | None = Field(default=None, max_length=200)
    budget_total: float | None = Field(default=None, validation_alias="budgetTotal", ge=0)
    note: str | None = Field(default=None, max_length=500)
    version: int | None = None


class ScenarioOut(Schema):
    id: uuid.UUID
    code: str
    name: str
    brand_id: uuid.UUID | None = Field(default=None, serialization_alias="brandId")
    status: str
    horizon_start: date = Field(serialization_alias="horizonStart")
    horizon_end: date = Field(serialization_alias="horizonEnd")
    budget_total: float = Field(serialization_alias="budgetTotal")
    currency: str
    note: str | None = None
    audit: AuditStamp | None = None


__all__ = [
    "AnalysisRunCreate",
    "AnalysisRunOut",
    "EventImpactOut",
    "ForecastOut",
    "ScenarioCreate",
    "ScenarioOut",
    "ScenarioPatch",
]
