"""Environment-only application configuration with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    environment: str
    log_level: str
    database_url: str | None
    database_pool_size: int
    database_max_overflow: int
    database_pool_timeout: int
    database_pool_recycle: int
    cors_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3010",
        "http://127.0.0.1:3010",
    )
    demo_admin_password: str = "admin-password"


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    database_url = os.getenv("DATABASE_URL")
    if database_url and "<" in database_url:
        database_url = None
    elif database_url and database_url.startswith("postgresql://"):
        database_url = database_url.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    origins = tuple(
        item.strip()
        for item in os.getenv(
            "CORS_ORIGINS",
            (
                "http://localhost:3000,http://127.0.0.1:3000,"
                "http://localhost:3010,http://127.0.0.1:3010"
            ),
        ).split(",")
        if item.strip()
    )
    demo_admin_password = os.getenv("DEMO_ADMIN_PASSWORD", "admin-password")
    if len(demo_admin_password) < 8:
        raise ValueError("DEMO_ADMIN_PASSWORD must contain at least 8 characters")
    return Settings(
        app_name=os.getenv("APP_NAME", "AuditForge API"),
        environment=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        database_url=database_url,
        database_pool_size=_positive_int("DATABASE_POOL_SIZE", 5),
        database_max_overflow=_positive_int("DATABASE_MAX_OVERFLOW", 5),
        database_pool_timeout=_positive_int("DATABASE_POOL_TIMEOUT", 30),
        database_pool_recycle=_positive_int("DATABASE_POOL_RECYCLE", 1800),
        cors_origins=origins,
        demo_admin_password=demo_admin_password,
    )
