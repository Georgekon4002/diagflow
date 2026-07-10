"""
DiagFlow — Slis Database Models (Read-Only Reflections)

These models represent the existing Slis tables that DiagFlow reads from.
They are PLACEHOLDER definitions — actual column names and types will be
mapped once Slis DB access is available.

IMPORTANT:
- These tables are READ-ONLY from DiagFlow's perspective
- The actual Slis schema may use different column names, types, or structures
- Update these models to match the real Slis schema when DB access is granted
- Only the final assignment write-back goes to Slis (via the assignment service)
"""

from sqlalchemy import Column, DateTime, String
from sqlalchemy.orm import DeclarativeBase


class SlisBase(DeclarativeBase):
    """
    Separate base class for Slis models.
    Keeps Slis table metadata separate from DiagFlow's own tables.
    """
    pass


class SlisExam(SlisBase):
    """
    Represents an exam/request in the Slis system.

    TODO: Map to actual Slis table/column names when DB access is available.
    Likely candidates:
    - Table might be called something like 'Εξετάσεις' or 'Requests' or 'Orders'
    - Columns will be in Greek or abbreviated
    """

    __tablename__ = "slis_exams"  # TODO: Replace with actual Slis table name

    exam_id = Column(String(50), primary_key=True)
    patient_id = Column(String(50), nullable=True)
    patient_name = Column(String(200), nullable=True)
    modality = Column(String(10), nullable=True)  # CT / MRI
    body_part = Column(String(100), nullable=True)
    lab_id = Column(String(50), nullable=True)
    lab_name = Column(String(200), nullable=True)
    issuing_doctor_id = Column(String(50), nullable=True)
    issuing_doctor_name = Column(String(200), nullable=True)
    request_date = Column(DateTime, nullable=True)
    status = Column(String(50), nullable=True)  # pending, assigned, completed
    comments = Column(String(2000), nullable=True)  # Free-text secretariat remarks


class SlisPatient(SlisBase):
    """
    Represents a patient in the Slis system.

    TODO: Map to actual Slis table/column names when DB access is available.
    """

    __tablename__ = "slis_patients"  # TODO: Replace with actual Slis table name

    patient_id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=True)
    date_of_birth = Column(DateTime, nullable=True)


class SlisAssignment(SlisBase):
    """
    Represents a past assignment in the Slis system.
    Used for patient history lookups.

    TODO: Map to actual Slis table/column names when DB access is available.
    """

    __tablename__ = "slis_assignments"  # TODO: Replace with actual Slis table name

    assignment_id = Column(String(50), primary_key=True)
    exam_id = Column(String(50), nullable=True)
    diagnostician_id = Column(String(50), nullable=True)
    diagnostician_name = Column(String(200), nullable=True)
    assigned_date = Column(DateTime, nullable=True)
    assigned_by = Column(String(200), nullable=True)
