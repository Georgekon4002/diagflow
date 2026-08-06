"""
DiagFlow — Application Settings

Loads configuration from environment variables / .env file.
Uses Pydantic Settings for validation and type coercion.
"""

import sys
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings

if getattr(sys, "frozen", False):
    _env_file = Path(sys.executable).parent / ".env"
else:
    _env_file = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables."""

    # ── Database ──
    slis_db_connection_string: str = Field(
        default="mssql+pyodbc://user:password@localhost/SlisDB?driver=ODBC+Driver+17+for+SQL+Server",
        description="SQLAlchemy connection string for the Slis database (read-only).",
    )
    config_db_connection_string: str = Field(
        default="mssql+pyodbc://user:password@localhost/SlisDB?driver=ODBC+Driver+17+for+SQL+Server",
        description=(
            "SQLAlchemy connection string for DiagFlow's config tables. "
            "Can be the same as slis_db_connection_string or a separate database."
        ),
    )

    # ── Mock Slis DB (SQLite, for development without a real Slis DB) ──
    use_mock_slis_db: bool = Field(
        default=True,
        description=(
            "When True, pending/assigned exam data is read from a local SQLite file "
            "(mock_slis_db_path) instead of the real Slis MSSQL database. "
            "Set to False in production once real DB access is available."
        ),
    )
    mock_slis_db_path: str = Field(
        default="db/mock_slis.db",
        description="Path to the SQLite mock Slis database file (relative to project root).",
    )



    # ── Rule Engine Weights ──
    # These control the relative importance of each scoring factor.
    # Rule hierarchy: availability(hard) → capacity(hard) → skills(hard) → history → partnership → lab → capacity(weight)
    # Sum ≈ 1.0 for interpretability; scores are clamped to [0, 1] internally.
    weight_partnership: float = Field(default=0.35, ge=0.0, le=1.0)
    weight_patient_history: float = Field(default=0.20, ge=0.0, le=1.0)
    weight_skills: float = Field(default=0.20, ge=0.0, le=1.0)  # Weighted bonus (hard filter handled in filters.py)
    weight_lab: float = Field(default=0.15, ge=0.0, le=1.0)  # Lab preference — now weighted, not hard filter
    weight_capacity: float = Field(default=0.10, ge=0.0, le=1.0)

    # ── Load Balancing ──
    # Scores within this threshold of the top score are treated as equivalent ("near-ties").
    # These near-tied candidates are ranked by workload (fewest exams today first) instead of score.
    # Default: 0.05 = 5 percentage points. Set to 0.0 to disable (strict score ordering).
    score_tie_tolerance: float = Field(default=0.05, ge=0.0, le=1.0)

    # ── Application ──
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    app_env: str = Field(default="development")
    log_level: str = Field(default="DEBUG")

    model_config = {
        "env_file": str(_env_file) if _env_file.exists() else ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Singleton settings instance — import this wherever needed
settings = Settings()
