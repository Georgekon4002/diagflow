"""
DiagFlow — Dual Database Engine Factory

Implements the "two-engine, one-DB-for-now" pattern:
- slis_engine: Read-only access to the existing Slis database
- config_engine: Read-write access to DiagFlow's own config/log tables

Both can point to the same physical database (as your supervisor prefers)
but the abstraction allows splitting to a separate DB later with a config change.
"""

from contextlib import contextmanager
import threading
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from diagflow.config import settings

# ── Engine instances (initialized lazily with thread safety) ──
_engine_lock = threading.Lock()
_slis_engine = None
_slis_engine_url: str | None = None
_config_engine = None
_config_engine_url: str | None = None
_SlisSession = None
_ConfigSession = None


def init_engines() -> None:
    """
    Initialize both database engines.
    Call this during application startup (lifespan).
    """
    global _slis_engine, _slis_engine_url, _config_engine, _config_engine_url, _SlisSession, _ConfigSession

    _slis_engine = get_slis_engine()
    _config_engine = get_config_engine()

    _SlisSession = sessionmaker(bind=_slis_engine)
    _ConfigSession = sessionmaker(bind=_config_engine)


def dispose_engines() -> None:
    """Dispose both engines. Call this during application shutdown."""
    global _slis_engine, _slis_engine_url, _config_engine, _config_engine_url, _SlisSession, _ConfigSession
    with _engine_lock:
        if _slis_engine:
            try:
                _slis_engine.dispose()
            except Exception:
                pass
            _slis_engine = None
            _slis_engine_url = None
            _SlisSession = None
        if _config_engine:
            try:
                _config_engine.dispose()
            except Exception:
                pass
            _config_engine = None
            _config_engine_url = None
            _ConfigSession = None


def get_config_engine():
    """Get or lazily initialize the pooled config database SQLAlchemy engine."""
    global _config_engine, _config_engine_url
    import sqlalchemy
    from sqlalchemy.engine import Engine

    url = settings.config_db_connection_string
    if _config_engine is not None and _config_engine_url == url and isinstance(_config_engine, Engine):
        return _config_engine

    with _engine_lock:
        if _config_engine is None or _config_engine_url != url or not isinstance(_config_engine, Engine):
            old_engine = _config_engine
            eng = sqlalchemy.create_engine(
                url,
                echo=bool(getattr(settings, "sql_echo", False)),
                pool_pre_ping=True,
                pool_recycle=1800,
                pool_size=5,
                max_overflow=10,
                connect_args={"timeout": 10},
            )
            if isinstance(eng, Engine):
                _config_engine = eng
                _config_engine_url = url
                if old_engine is not None and old_engine is not eng:
                    try:
                        old_engine.dispose()
                    except Exception:
                        pass
            return eng
        return _config_engine


def get_slis_engine():
    """Get or lazily initialize the pooled Slis database SQLAlchemy engine."""
    global _slis_engine, _slis_engine_url
    import sqlalchemy
    from sqlalchemy.engine import Engine

    url = settings.slis_db_connection_string
    if _slis_engine is not None and _slis_engine_url == url and isinstance(_slis_engine, Engine):
        return _slis_engine

    with _engine_lock:
        if _slis_engine is None or _slis_engine_url != url or not isinstance(_slis_engine, Engine):
            old_engine = _slis_engine
            eng = sqlalchemy.create_engine(
                url,
                echo=bool(getattr(settings, "sql_echo", False)),
                pool_pre_ping=True,
                pool_recycle=1800,
                pool_size=5,
                max_overflow=10,
                connect_args={"timeout": 10},
            )
            if isinstance(eng, Engine):
                _slis_engine = eng
                _slis_engine_url = url
                if old_engine is not None and old_engine is not eng:
                    try:
                        old_engine.dispose()
                    except Exception:
                        pass
            return eng
        return _slis_engine


@contextmanager
def get_slis_session() -> Generator[Session, None, None]:
    """
    Get a Slis database session (read-only).

    Usage:
        with get_slis_session() as session:
            results = session.execute(...)
    """
    global _SlisSession
    if _SlisSession is None:
        _SlisSession = sessionmaker(bind=get_slis_engine())
    session = _SlisSession()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def get_config_session() -> Generator[Session, None, None]:
    """
    Get a Config database session (read-write).

    Usage:
        with get_config_session() as session:
            session.add(...)
            session.commit()
    """
    global _ConfigSession
    if _ConfigSession is None:
        _ConfigSession = sessionmaker(bind=get_config_engine())
    session = _ConfigSession()
    try:
        yield session
    finally:
        session.close()
