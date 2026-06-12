"""Application configuration.

All runtime configuration is read from environment variables (12-factor style)
so the same image runs unchanged across development, testing, and production.
See `.env.example` for the full list.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import EmailStr, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Environment ----
    ENVIRONMENT: Literal["development", "testing", "production"] = "development"
    PROJECT_NAME: str = "Helios Core"
    API_V1_PREFIX: str = "/api/v1"

    # ---- Security ----
    SECRET_KEY: str = Field(..., min_length=16)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    JWT_ALGORITHM: str = "HS256"

    # ---- CORS ----
    # Comma-separated string in the environment, parsed into a list.
    BACKEND_CORS_ORIGINS: str = "http://localhost:5173"

    # ---- Database ----
    POSTGRES_USER: str = "helios"
    POSTGRES_PASSWORD: str = "helios"
    POSTGRES_DB: str = "helios"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    # ---- First admin (seed) ----
    FIRST_ADMIN_EMAIL: EmailStr = "admin@helios.local"
    FIRST_ADMIN_PASSWORD: str = "change_me_on_first_login"
    FIRST_ADMIN_NAME: str = "System Administrator"

    # ---- File storage / NAS ----
    NAS_ROOT: str = "/data/nas"
    STORAGE_ROOT: str = "/data/storage"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.BACKEND_CORS_ORIGINS.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor so the env is parsed once per process."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
