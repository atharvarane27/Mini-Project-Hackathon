from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "change-me-in-production-track2-audit-platform-secret-key"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "AuditForge"
    APP_VERSION: s.env
.env.*
!.env.example
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cant.en  !.envG:__pycache__/e
*.py[cod]
.EL.venv/
v"Ivenv/  .pytI_.mypy_cache/
r .ruff_i/v1"

.coverage
hashtmlcov/gsnode_mo_B.next/
out/
raout/
padise"builos*.egg"]playwrightsetest-resTABASE_URL:*.log
.DS_St  .  "poThumbs.d+p*.tsbuil/p
# Large locgre*.zip
SFinDSet.zip
SFinDSet.csv
SFinDSet.cs"
SFin)
SFinDSet.csE_SFinDSet.csinEOF

cat > backend/app_OcaRFLOW: int = 5
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_POOL_RECYCLE: int = 1800

    # Security
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    @model_validator(mode="after")
    def validate_environment_secret(self) -> "Settings":
        if self.ENVIRONMENT != "development" and self.SECRET_KEY == DEFAULT_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY must be set to a non-default value outside the development environment."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
