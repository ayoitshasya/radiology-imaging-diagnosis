"""Database engine, session factory and declarative base."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all backend tables."""


def make_engine(url: str) -> Engine:
    """Engine with pre-ping, so a restarted Postgres does not break pooled connections."""
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Session factory bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session and always close it; used as a FastAPI dependency."""
    session = factory()
    try:
        yield session
    finally:
        session.close()
