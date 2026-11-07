"""Alembic environment: runs migrations online against the configured database."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from backend.app.db import Base
from backend.app.models import AuditLog, Prediction, Review  # noqa: F401  (register tables)
from backend.app.settings import get_settings

config = context.config
target_metadata = Base.metadata


def database_url() -> str:
    """URL passed by a caller (tests) via config.attributes, else the app settings.

    Not read from alembic.ini: the URL holds a password, and ini interpolation would
    mangle any '%' in it.
    """
    return config.attributes.get("database_url") or get_settings().database_url.get_secret_value()


def run_migrations_online() -> None:
    """Run migrations in a transaction on a fresh connection."""
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (SQL script) mode is not supported; run against a database.")
run_migrations_online()
