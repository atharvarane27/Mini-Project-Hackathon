from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings


def create_db_engine(
    database_url: str | None = None,
    **engine_kwargs: Any,
) -> Engine:
    """Create and configure a SQLAlchemy Engine.

    Supports:
    - Supabase PostgreSQL / psycopg3 with connection pooling and SSL
    - Local PostgreSQL fallback
    - SQLite in-memory or file (enabling foreign keys via PRAGMA)
    """
    settings = get_settings()
    url = database_url or settings.DATABASE_URL

    kwargs: dict[str, Any] = {
        "echo": settings.DEBUG and settings.ENVIRONMENT == "development",
        **engine_kwargs,
    }

    if url.startswith("sqlite"):
        # For testing / hermetic SQLite
        if ":memory:" in url or url == "sqlite://":
            kwargs.setdefault("connect_args", {"check_same_thread": False})
            kwargs.setdefault("poolclass", StaticPool)
        else:
            kwargs.setdefault("connect_args", {"check_same_thread": False})

        eng = create_engine(url, **kwargs)

        # Enforce foreign key constraints on SQLite
        @event.listens_for(eng, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return eng

    # PostgreSQL (Supabase or local PostgreSQL)
    kwargs.setdefault("pool_size", settings.DATABASE_POOL_SIZE)
    kwargs.setdefault("max_overflow", settings.DATABASE_MAX_OVERFLOW)
    kwargs.setdefault("pool_timeout", settings.DATABASE_POOL_TIMEOUT)
    kwargs.setdefault("pool_recycle", settings.DATABASE_POOL_RECYCLE)
    kwargs.setdefault("pool_pre_ping", True)

    connect_args: dict[str, Any] = kwargs.get("connect_args", {})
    if settings.DB_BACKEND == "supabase" and "sslmode" not in url:
        connect_args.setdefault("sslmode", "require")
    if connect_args:
        kwargs["connect_args"] = connect_args

    return create_engine(url, **kwargs)


# Global Engine and SessionFactory
engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db_context(
    session_factory: sessionmaker[Session] = SessionLocal,
) -> Generator[Session, None, None]:
    """Transaction-scoped database session context manager.

    Automatically commits on normal exit, rolls back on any exception, and closes on finally.
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for transaction-scoped database session."""
    with get_db_context() as session:
        yield session
