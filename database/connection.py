"""Database connection management. Credentials are never logged or returned."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


class DatabaseNotConfigured(RuntimeError):
    """Raised when DATABASE_URL is not set."""


def build_engine(db_url: str) -> Engine:
    settings = get_settings()
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
                      connect_args={"connect_timeout": settings.db_connect_timeout})
    engine = create_engine(db_url, **kwargs)
    if db_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_conn, _record):  # enforce foreign keys on SQLite
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


def configure(url: Optional[str] = None) -> Engine:
    """(Re)initialise the process-wide engine and session factory."""
    global _engine, _session_factory
    db_url = url if url is not None else get_settings().database_url
    if not db_url.strip():
        raise DatabaseNotConfigured("DATABASE_URL is not set.")
    if _engine is not None:
        _engine.dispose()
    _engine = build_engine(db_url)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        configure()
    if _engine is None:
        raise DatabaseNotConfigured("Database is not initialised.")
    return _engine


def reset() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error, always close."""
    get_engine()
    if _session_factory is None:
        raise DatabaseNotConfigured("Database is not initialised.")
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def health_check(url: Optional[str] = None) -> Tuple[str, str]:
    """Return (state, message): ok | not_configured | error. Messages never contain credentials."""
    engine = None
    owned = False
    try:
        if url is None:
            engine = get_engine()
        else:
            if not url.strip():
                raise DatabaseNotConfigured("DATABASE_URL is not set.")
            engine, owned = build_engine(url), True
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok", "Connected"
    except DatabaseNotConfigured:
        return "not_configured", "DATABASE_URL is not set"
    except SQLAlchemyError as exc:
        logger.warning("Database health check failed: %s", type(exc).__name__)
        return "error", "Connection failed. Check DATABASE_URL and that the server is running"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Database health check error: %s", type(exc).__name__)
        return "error", "Unexpected database error"
    finally:
        if owned and engine is not None:
            engine.dispose()
