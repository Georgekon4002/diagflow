"""
DiagFlow — Pydantic Request/Response Schemas

Defines all API data contracts using Pydantic v2 models.
"""

from datetime import date as dt_date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


def _validate_iso_date_str(v: str | None) -> str | None:
    if v is None or str(v).strip() == "":
        return None
    s = str(v).strip()
    if len(s) == 10:
        try:
            return dt_date.fromisoformat(s).isoformat()
        except ValueError as exc:
            raise ValueError(f"Invalid ISO date format (expected YYYY-MM-DD): {v}") from exc
    try:
        # Allow valid ISO-8601 timestamps (e.g. 2026-11-24T00:00:00), reject arbitrary trailing junk
        parsed_dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return parsed_dt.date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid ISO date format (expected YYYY-MM-DD): {v}") from exc


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


class BulkConfirmItem(BaseModel):
    """Individual item for bulk confirming with optional pre-known diagnostician."""

    exam_id: str
    diagnostician_id: int | None = None


class BulkConfirmRequest(BaseModel):
    """Request body for confirming suggested assignments for multiple exams."""

    exam_ids: list[str] = Field(default_factory=list)
    items: list[BulkConfirmItem] | None = None


class BulkOverrideRequest(BaseModel):
    """Request body for overriding assignments for multiple exams."""

    exam_ids: list[str]
    override_diagnostician_id: int
    reason: str = Field(default="Bulk assignment", description="Why the operator chose a different diagnostician")


class SetOncallRequest(BaseModel):
    """Request body for setting Παμακάριστος on-call diagnostician."""

    date: str = Field(..., description="Date in ISO format (YYYY-MM-DD)")
    diagnostician_id: int = Field(..., gt=0)

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        res = _validate_iso_date_str(v)
        if not res:
            raise ValueError("date is required in YYYY-MM-DD format")
        return res


class AdminChangeCredentialsRequest(BaseModel):
    """Request body for updating admin credentials."""

    old_password: str = Field(..., description="Current admin password")
    new_username: Optional[str] = Field(default=None, description="New admin username")
    new_password: Optional[str] = Field(default=None, description="New admin password")


class AdminChangeCredentialsResponse(BaseModel):
    """Response after updating admin credentials."""

    message: str
    username: str


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
    eliminated: bool = False
    elimination_reason: str | None = None


class SuggestionResponse(BaseModel):
    """Response for an assignment suggestion."""

    exam_id: str
    patient_id: str | None = None
    exam_summary: str
    suggested_diagnostician_id: int
    suggested_diagnostician_name: str
    confidence_score: float
    score_breakdown: list[ScoreComponentResponse]
    alternatives: list[AlternativeCandidate]
    rules_fired: list[str]
    solver_status: str
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
    stat: Optional[int] = 0

    # Populated after suggestion is generated
    suggestion: Optional[SuggestionResponse] = None


class DiagnosticianResponse(BaseModel):
    """Response for a diagnostician."""

    id: int
    name: str
    can_ct: bool
    can_mri: bool
    quota_monday: int
    quota_tuesday: int
    quota_wednesday: int
    quota_thursday: int
    quota_friday: int
    quota_saturday: int
    quota_sunday: int
    current_day_count: int
    counts_by_date: dict[str, int] = Field(default_factory=dict)
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


class BulkEligibleRequest(BaseModel):
    exam_ids: list[str | int]


class BulkEligibleResponseItem(BaseModel):
    diagnostician_id: int
    is_eligible: bool
    reject_reason: str | None


class BulkEligibleResponse(BaseModel):
    diagnosticians: list[BulkEligibleResponseItem]


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    app: str
    environment: str


# ── Advanced Options Schemas ──

class ExamRoutingRuleBase(BaseModel):
    lab_id: int | None = None
    issuing_doctor_id: str | None = None
    issuing_doctor_name: str | None = None
    is_pamakristos: bool = False
    exam_codes: str
    diagnostician_id: int
    description: str
    is_active: bool = True

class ExamRoutingRuleCreate(ExamRoutingRuleBase):
    pass

class ExamRoutingRuleUpdate(BaseModel):
    lab_id: int | None = None
    issuing_doctor_id: str | None = None
    issuing_doctor_name: str | None = None
    is_pamakristos: bool | None = None
    exam_codes: str | None = None
    diagnostician_id: int | None = None
    description: str | None = None
    is_active: bool | None = None

class ExamRoutingRuleResponse(ExamRoutingRuleBase):
    id: int
    diagnostician_name: str

class ExclusiveLabRuleBase(BaseModel):
    diagnostician_id: int
    lab_id: int
    lab_name: str | None = None
    is_active: bool = True

class ExclusiveLabRuleCreate(ExclusiveLabRuleBase):
    pass

class ExclusiveLabRuleUpdate(BaseModel):
    diagnostician_id: int | None = None
    lab_id: int | None = None
    lab_name: str | None = None
    is_active: bool | None = None

class ExclusiveLabRuleResponse(ExclusiveLabRuleBase):
    id: int
    diagnostician_name: str

class ModalityQuotaBase(BaseModel):
    diagnostician_id: int = Field(..., gt=0)
    modality: Literal["CT", "MRI", "MRA"]
    max_count: int = Field(..., ge=0)
    is_active: bool = True

    @field_validator("modality", mode="before")
    @classmethod
    def normalize_modality_case(cls, v: str) -> str:
        return str(v).upper().strip() if v is not None else v

class ModalityQuotaCreate(ModalityQuotaBase):
    pass

class ModalityQuotaUpdate(BaseModel):
    diagnostician_id: int | None = Field(default=None, gt=0)
    modality: Literal["CT", "MRI", "MRA"] | None = None
    max_count: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @field_validator("modality", mode="before")
    @classmethod
    def normalize_modality_case(cls, v: str | None) -> str | None:
        return str(v).upper().strip() if v is not None else None

class ModalityQuotaResponse(BaseModel):
    id: int
    diagnostician_id: int
    modality: str
    max_count: int
    is_active: bool = True
    diagnostician_name: str


class SlisSearchRequest(BaseModel):
    start_date: str | None = None
    end_date: str | None = None
    extracode: str | None = None
    patient_query: str | None = None
    doctor_query: str | None = None
    diagnostician_query: str | None = None

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_search_dates(cls, v: str | None) -> str | None:
        return _validate_iso_date_str(v)


class SlisReassignRequest(BaseModel):
    exammoreid: int
    diagnostician_id: int
    diagnostician_name: str = ""
    force: bool = True


class UnassignRequest(BaseModel):
    exam_id: str | int


class BulkUnassignRequest(BaseModel):
    exam_ids: list[str | int]

