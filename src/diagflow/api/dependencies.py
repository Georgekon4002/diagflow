"""
DiagFlow — FastAPI Dependency Injection

Provides shared service instances via FastAPI's dependency injection system.
"""

from functools import lru_cache

from diagflow.services.assignment import AssignmentService
from diagflow.services.diagnostician import DiagnosticianService
from diagflow.services.pamakristos import PamakristosScheduler


@lru_cache()
def get_assignment_service() -> AssignmentService:
    """Get the singleton AssignmentService instance."""
    return AssignmentService()


@lru_cache()
def get_diagnostician_service() -> DiagnosticianService:
    """Get the singleton DiagnosticianService instance."""
    return DiagnosticianService()


@lru_cache()
def get_pamakristos_scheduler() -> PamakristosScheduler:
    """Get the singleton PamakristosScheduler instance."""
    return PamakristosScheduler()
