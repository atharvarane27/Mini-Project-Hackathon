"""Transaction-scoped SQLAlchemy sessions for Supabase or local PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, load_settings


def create_database_engine(settings: Settings | None = None) -> Engine:
    configured = settings or load_settings()
    if configured.database_url is None:
        raise RuntimeError("DATABASE_URL is required for database access")
    arguments: dict[str, object] = {"pool_pre_ping": True}
    if not configured.database_url.startswith("sqlite"):
        arguments.update(
            pool_size=configured.database_pool_size,
            max_overflow=configured.database_max_overflow,
            pool_timeout=configured.database_pool_timeout,
            pool_recycle=configured.database_pool_recycle,
        )
    return create_engine(configured.database_url, **arguments)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def transaction_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        with session.begin():
            yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
