"""
DiagFlow — ORM Models (Config Tables)

These are DiagFlow's own tables for configuration, capacity, availability,
partnerships, and the all-important assignment_log for audit.

NOTE: Column names and types are based on the planned schema.
These will be validated and adjusted once Slis DB access is available.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all DiagFlow ORM models."""
    pass


class Diagnostician(Base):
    """Master list of diagnosticians."""

    __tablename__ = "diagnosticians"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    name: str = Column(String(200), nullable=False)
    active: bool = Column(Boolean, default=True, nullable=False)
    can_ct: bool = Column(Boolean, default=True)
    can_mri: bool = Column(Boolean, default=True)
    created_at: datetime = Column(DateTime, server_default=func.now())
    updated_at: datetime = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    skills = relationship("DiagnosticianSkill", back_populates="diagnostician", lazy="selectin")
    capacity = relationship("DiagnosticianCapacity", back_populates="diagnostician", uselist=False)
    lab_preferences = relationship("DiagnosticianLabPreference", back_populates="diagnostician")
    availability_records = relationship("DiagnosticianAvailability", back_populates="diagnostician")


class DiagnosticianSkill(Base):
    """Specific exam codes and preference per diagnostician."""

    __tablename__ = "diagnostician_skills"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    diagnostician_id: int = Column(Integer, ForeignKey("diagnosticians.id"), nullable=False)
    exam_code: str = Column(String(50), nullable=False)
    is_preferred: bool = Column(Boolean, default=False)
    notes: Optional[str] = Column(String(500), nullable=True)

    diagnostician = relationship("Diagnostician", back_populates="skills")


class DiagnosticianCapacity(Base):
    """Daily hard quota and optional soft sub-caps per body-part category."""

    __tablename__ = "diagnostician_capacity"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    diagnostician_id: int = Column(
        Integer, ForeignKey("diagnosticians.id"), nullable=False, unique=True
    )
    daily_hard_quota: int = Column(Integer, nullable=False, default=15) # TODO: Migrate to 7 daily columns if ORM used
    quota_monday: int = Column(Integer, nullable=False, default=15)
    quota_tuesday: int = Column(Integer, nullable=False, default=15)
    quota_wednesday: int = Column(Integer, nullable=False, default=15)
    quota_thursday: int = Column(Integer, nullable=False, default=15)
    quota_friday: int = Column(Integer, nullable=False, default=15)
    quota_saturday: int = Column(Integer, nullable=False, default=0)
    quota_sunday: int = Column(Integer, nullable=False, default=0)

    # Soft sub-caps — optional limits per body-part category
    # When a diagnostician hits these, they get a scoring penalty, not a hard stop
    abdomen_soft_cap: Optional[int] = Column(Integer, nullable=True)
    neuro_soft_cap: Optional[int] = Column(Integer, nullable=True)
    msk_soft_cap: Optional[int] = Column(Integer, nullable=True)
    chest_soft_cap: Optional[int] = Column(Integer, nullable=True)

    diagnostician = relationship("Diagnostician", back_populates="capacity")


class DiagnosticianLabPreference(Base):
    """Which labs a diagnostician will accept work from."""

    __tablename__ = "diagnostician_lab_preference"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    diagnostician_id: int = Column(Integer, ForeignKey("diagnosticians.id"), nullable=False)
    lab_id: str = Column(String(50), nullable=False)
    lab_name: str = Column(String(200), nullable=False)
    accepted: bool = Column(Boolean, default=True)

    diagnostician = relationship("Diagnostician", back_populates="lab_preferences")


class DiagnosticianAvailability(Base):
    """Daily availability calendar — leave, on-call, etc."""

    __tablename__ = "diagnostician_availability"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    diagnostician_id: int = Column(Integer, ForeignKey("diagnosticians.id"), nullable=False)
    date: date = Column(Date, nullable=False)
    status: str = Column(
        String(50), nullable=False, default="available"
    )  # available, on_leave, half_day
    is_pamakristos_oncall: bool = Column(Boolean, default=False)
    notes: Optional[str] = Column(String(500), nullable=True)

    diagnostician = relationship("Diagnostician", back_populates="availability_records")


class Partnership(Base):
    """Issuing doctor → preferred diagnostician mapping."""

    __tablename__ = "partnerships"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    issuing_doctor_id: str = Column(String(50), nullable=False)
    issuing_doctor_name: str = Column(String(200), nullable=False)
    preferred_diagnostician_id: int = Column(
        Integer, ForeignKey("diagnosticians.id"), nullable=False
    )
    priority: int = Column(Integer, default=1)  # Higher = stronger preference
    notes: Optional[str] = Column(String(500), nullable=True)

    diagnostician = relationship("Diagnostician")


class AssignmentLog(Base):
    """
    Audit trail for every assignment decision.

    This is the most important table — it records what the engine suggested,
    what the human decided, which rules fired, and the full score breakdown.
    Used for auditing, weight tuning, and tracking override patterns.
    """

    __tablename__ = "assignment_log"

    id: int = Column(Integer, primary_key=True, autoincrement=True)

    # Exam identifiers
    exam_id: str = Column(String(50), nullable=False)
    patient_id: str = Column(String(50), nullable=False)
    exam_modality: str = Column(String(10), nullable=True)  # CT or MRI
    exam_body_part: str = Column(String(100), nullable=True)
    issuing_doctor_id: str = Column(String(50), nullable=True)
    lab_id: str = Column(String(50), nullable=True)

    # Assignment decision
    suggested_diagnostician_id: int = Column(
        Integer, ForeignKey("diagnosticians.id"), nullable=False
    )
    final_diagnostician_id: int = Column(
        Integer, ForeignKey("diagnosticians.id"), nullable=False
    )
    was_overridden: bool = Column(Boolean, default=False, nullable=False)
    override_reason: Optional[str] = Column(String(500), nullable=True)

    # Rule engine output (stored as JSON strings)
    rules_fired: Optional[str] = Column(Text, nullable=True)
    score_breakdown: Optional[str] = Column(Text, nullable=True)
    alternative_candidates: Optional[str] = Column(Text, nullable=True)

    # Comment analysis
    comment_raw: Optional[str] = Column(Text, nullable=True)
    comment_parsed: Optional[str] = Column(Text, nullable=True)

    # Timestamps
    decision_timestamp: datetime = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    suggested_diagnostician = relationship(
        "Diagnostician", foreign_keys=[suggested_diagnostician_id]
    )
    final_diagnostician = relationship(
        "Diagnostician", foreign_keys=[final_diagnostician_id]
    )
