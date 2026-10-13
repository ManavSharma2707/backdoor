"""Application settings.

One `Settings` object, validated at start. In production the process refuses to start
with weak or missing secrets (see `security.md` section 5).
"""

from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LOCAL_DATABASE_URL = "postgresql+psycopg://backroom:backroom@localhost:5432/backroom"
DEV_JWT_SECRET = "dev-only-jwt-secret-do-not-use-outside-local-development"  # noqa: S105
DEV_JOB_TOKEN = "dev-only-job-token-do-not-use-outside-local-development"  # noqa: S105
PLACEHOLDER_PREFIXES = ("replace-with", "change-me", "dev-only", "example")
MIN_SECRET_LENGTH = 32


class ConfigError(RuntimeError):
    """Raised when production settings are unsafe or incomplete."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"

    database_url: str = LOCAL_DATABASE_URL
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=2, ge=0, le=20)
    database_transaction_pooler: bool = False

    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    jwt_issuer: str = "backroom"
    jwt_audience: str = "backroom-web"
    access_token_minutes: int = Field(default=15, ge=1, le=120)
    refresh_token_days: int = Field(default=14, ge=1, le=60)
    cookie_secure: bool = False
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    job_token: SecretStr = SecretStr(DEV_JOB_TOKEN)

    allow_registration: bool = False
    demo_login_enabled: bool = False
    allow_demo_reset: bool = False
    simulate_weekly: bool = False
    agents_enabled: bool = True

    gemini_api_key: SecretStr = SecretStr("")
    gemini_model_fast: str = ""
    gemini_model_smart: str = ""
    gemini_embed_model: str = ""
    embed_dim: int = 768

    demo_owner_password: SecretStr = SecretStr("")
    seed_base: int = 20261011

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip().rstrip("/") for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def _production_checks(self) -> Self:
        if self.app_env != "production":
            return self
        problems: list[str] = []
        for name, secret in (("JWT_SECRET", self.jwt_secret), ("JOB_TOKEN", self.job_token)):
            value = secret.get_secret_value()
            if len(value) < MIN_SECRET_LENGTH:
                problems.append(f"{name} must be at least {MIN_SECRET_LENGTH} characters")
            elif value.startswith(PLACEHOLDER_PREFIXES):
                problems.append(f"{name} is a placeholder value")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true")
        if not self.cors_origins:
            problems.append("CORS_ORIGINS must list at least one origin")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must not contain a wildcard")
        if self.database_url == LOCAL_DATABASE_URL:
            problems.append("DATABASE_URL is still the local default")
        if problems:
            raise ConfigError("Unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
