"""
DiagFlow — Dual Database Engine Factory

Implements the "two-engine, one-DB-for-now" pattern:
- slis_engine: Read-only access to the existing Slis database
- config_engine: Read-write access to DiagFlow's own config/log tables

Both can point to the same physical database (as your supervisor prefers)
but the abstraction allows splitting to a separate DB later with a config change.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from diagflow.config import settings

# ── Engine instances (initialized lazily) ──
_slis_engine = None
_config_engine = None
_SlisSession = None
_ConfigSession = None


def init_engines() -> None:
    """
    Initialize both database engines.
    Call this during application startup (lifespan).
    """
    global _slis_engine, _config_engine, _SlisSession, _ConfigSession

    # Slis engine — read-only access to the existing Slis schema
    _slis_engine = create_engine(
        settings.slis_db_connection_string,
        echo=(settings.app_env == "development"),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

    # Config engine — DiagFlow's own tables (may be the same DB)
    _config_engine = create_engine(
        settings.config_db_connection_string,
        echo=(settings.app_env == "development"),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

    _SlisSession = sessionmaker(bind=_slis_engine)
    _ConfigSession = sessionmaker(bind=_config_engine)


def dispose_engines() -> None:
    """Dispose both engines. Call this during application shutdown."""
    global _slis_engine, _config_engine
    if _slis_engine:
        _slis_engine.dispose()
    if _config_engine:
        _config_engine.dispose()


def get_slis_session() -> Session:
    """
    Get a Slis database session (read-only).

    Usage:
        with get_slis_session() as session:
            results = session.execute(...)
    """
    if _SlisSession is None:
        raise RuntimeError(
            "Database engines not initialized. Call init_engines() during startup."
        )
    session = _SlisSession()
    try:
        yield session
    finally:
        session.close()


def get_config_session() -> Session:
    """
    Get a Config database session (read-write).

    Usage:
        with get_config_session() as session:
            session.add(...)
            session.commit()
    """
    if _ConfigSession is None:
        raise RuntimeError(
            "Database engines not initialized. Call init_engines() during startup."
        )
    session = _ConfigSession()
    try:
        yield session
    finally:
        session.close()
