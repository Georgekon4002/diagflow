"""
DiagFlow — Application Settings

Loads configuration from environment variables / .env file.
Uses Pydantic Settings for validation and type coercion.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


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

    # ── LLM / Comment Parser ──
    llm_api_url: str = Field(
        default="https://api.openai.com/v1/chat/completions",
        description="LLM API endpoint for comment parsing.",
    )
    llm_api_key: str = Field(
        default="",
        description="API key for the LLM service.",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="LLM model identifier.",
    )

    # ── Rule Engine Weights ──
    # These control the relative importance of each scoring factor.
    # They should sum to roughly 1.0 for interpretability but are normalized internally.
    weight_capacity: float = Field(default=0.30, ge=0.0, le=1.0)
    weight_skills: float = Field(default=0.25, ge=0.0, le=1.0)
    weight_partnership: float = Field(default=0.25, ge=0.0, le=1.0)
    weight_patient_history: float = Field(default=0.15, ge=0.0, le=1.0)
    weight_subcategory_penalty: float = Field(default=0.05, ge=0.0, le=1.0)

    # ── Application ──
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    app_env: str = Field(default="development")
    log_level: str = Field(default="DEBUG")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Singleton settings instance — import this wherever needed
settings = Settings()
