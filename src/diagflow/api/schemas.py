"""
DiagFlow — Pydantic Request/Response Schemas

Defines all API data contracts using Pydantic v2 models.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Request schemas ──


class SuggestAssignmentRequest(BaseModel):
    """Request body for generating an assignment suggestion."""

    exam_id: str = Field(..., description="Slis exam identifier")


class ConfirmAssignmentRequest(BaseModel):
    """Request body for confirming a suggested assignment."""

    exam_id: str
    diagnostician_id: int


class OverrideAssignmentRequest(BaseModel):
    """Request body for overriding a suggested assignment."""

    exam_id: str
    original_diagnostician_id: int
    override_diagnostician_id: int
    reason: str = Field(default="", description="Why the operator chose a different diagnostician")


class SetOncallRequest(BaseModel):
    """Request body for setting Παμακάριστος on-call diagnostician."""

    date: str = Field(..., description="Date in ISO format (YYYY-MM-DD)")
    diagnostician_id: int


# ── Response schemas ──


class ScoreComponentResponse(BaseModel):
    """A single scoring component in the suggestion breakdown."""

    rule: str
    display_name: str
    raw_score: float
    weight: float
    weighted_score: float
    explanation: str


class AlternativeCandidate(BaseModel):
    """An alternative diagnostician candidate."""

    id: int
    name: str
    score: float


class SuggestionResponse(BaseModel):
    """Response for an assignment suggestion."""

    exam_id: str
    patient_id: str
    exam_summary: str
    suggested_diagnostician_id: int
    suggested_diagnostician_name: str
    confidence_score: float
    score_breakdown: list[ScoreComponentResponse]
    alternatives: list[AlternativeCandidate]
    rules_fired: list[str]
    solver_status: str
    is_direct_assignment: bool = False
    direct_assignment_reason: str = ""
    pipeline_timestamp: str


class ExamResponse(BaseModel):
    """Response for a pending exam."""

    exam_id: str
    patient_id: str
    patient_name: str
    modality: str
    body_part: str
    lab_id: str
    lab_name: str
    issuing_doctor_id: str
    issuing_doctor_name: str
    request_date: str
    status: str
    comments: str

    # Populated after suggestion is generated
    suggestion: Optional[SuggestionResponse] = None


class DiagnosticianResponse(BaseModel):
    """Response for a diagnostician."""

    id: int
    name: str
    can_ct: bool
    can_mri: bool
    daily_quota: int
    current_day_count: int
    available: bool


class AssignmentConfirmation(BaseModel):
    """Response after confirming or overriding an assignment."""

    exam_id: str
    diagnostician_id: int
    was_overridden: bool
    status: str = "confirmed"
    timestamp: str


class OncallResponse(BaseModel):
    """Response for Παμακάριστος on-call info."""

    date: str
    diagnostician_id: int
    diagnostician_name: str
    source: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    app: str
    version: str
    environment: str
