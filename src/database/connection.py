"""Database engine, session factory, and helpers."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings
from src.database.models import Base

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.DATABASE_URL,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autocommit=False, autoflush=False
        )
    return _SessionLocal


def init_db() -> None:
    """Create all tables if they do not exist (idempotent)."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("Database tables initialised")


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Yield a transactional session; commits on success, rolls back on error."""
    SessionLocal = get_session_factory()
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
