"""Application configuration.

All runtime configuration is sourced from environment variables (twelve-factor
style) with safe development defaults. Production deployments MUST override
``SECRET_KEY`` and ``DATABASE_URL``.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HHRN_", env_file=".env", extra="ignore")

    app_name: str = "Home Health RN AI Platform"
    environment: str = "development"
    debug: bool = False

    # Security
    secret_key: str = "dev-only-secret-change-me"
    access_token_expire_minutes: int = 60 * 8  # one shift
    refresh_token_expire_minutes: int = 60 * 24 * 7
    jwt_algorithm: str = "HS256"

    # Database
    database_url: str = "postgresql+psycopg2://hhrn:hhrn@db:5432/hhrn"

    # Object storage for uploaded documents / images / audio
    storage_dir: str = "/data/storage"

    # OCR / transcription engines: "stub" (deterministic, no external deps)
    # or "tesseract" (requires the tesseract binary in the container).
    ocr_engine: str = "stub"
    transcription_engine: str = "stub"

    # Hard safety invariants. These exist so that the values are visible and
    # auditable in configuration, but the platform REFUSES to start if they
    # are ever turned off — see app.core.safety.enforce_safety_invariants().
    allow_auto_submit: bool = False
    allow_auto_sign: bool = False
    allow_ai_final_codes: bool = False

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
