import os
from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
LOCAL_TRUSTED_HOSTS = ("localhost", "127.0.0.1", "testserver")
MIN_CHAT_SECRET_LENGTH = 32


class Settings(BaseModel):
    """Runtime configuration loaded from environment variables."""

    app_environment: str = Field(default="development")
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4.1-mini")
    openai_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    openai_max_retries: int = Field(default=1, ge=0, le=3)
    openai_max_output_tokens: int = Field(default=350, ge=64, le=1000)
    allowed_origins: list[str] = Field(default_factory=list)
    trusted_hosts: list[str] = Field(default_factory=lambda: list(LOCAL_TRUSTED_HOSTS))
    trusted_proxy_cidrs: list[str] = Field(default_factory=list)
    chat_api_secret: str = Field(default="")
    chat_rate_limit: int = Field(default=10, ge=1, le=1000)
    chat_global_rate_limit: int = Field(default=60, ge=1, le=10_000)
    chat_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    chat_rate_limit_max_keys: int = Field(default=10_000, ge=100, le=1_000_000)
    chat_max_concurrency: int = Field(default=4, ge=1, le=100)
    chat_concurrency_wait_seconds: float = Field(default=0.25, ge=0, le=5)
    chat_max_body_bytes: int = Field(default=16_384, ge=1024, le=1_048_576)
    log_chat_content: bool = Field(default=True)
    api_title: str = Field(default="Interview")
    api_version: str = Field(default="0.1.0")

    @field_validator("app_environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        """Normalize environment names for reliable production checks."""

        return value.strip().lower()

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, values: list[str]) -> list[str]:
        """Reject malformed proxy networks during configuration loading."""

        for value in values:
            ip_network(value, strict=False)
        return values

    @property
    def is_production(self) -> bool:
        """Return whether strict production safeguards should be enforced."""

        return self.app_environment in {"production", "prod"}


def _parse_allowed_origins(value: str) -> list[str]:
    """Convert a comma-separated origin list into normalized origin strings."""

    return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]


def _parse_csv(value: str) -> list[str]:
    """Convert a comma-separated setting into stripped non-empty values."""

    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_bool(value: str) -> bool:
    """Parse an explicit environment boolean without truthy-string surprises."""

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def production_configuration_errors(
    settings: Settings,
    *,
    biography_ready: bool,
) -> list[str]:
    """Return production configuration failures without exposing secret values."""

    if not settings.is_production:
        return []

    errors: list[str] = []
    if not settings.openai_api_key:
        errors.append("OPENAI_API_KEY must be configured.")
    if len(settings.chat_api_secret) < MIN_CHAT_SECRET_LENGTH:
        errors.append(
            f"CHAT_API_SECRET must contain at least {MIN_CHAT_SECRET_LENGTH} characters."
        )
    if not settings.allowed_origins or "*" in settings.allowed_origins:
        errors.append("ALLOWED_ORIGINS must be an explicit non-wildcard allowlist.")
    elif any(not origin.startswith("https://") for origin in settings.allowed_origins):
        errors.append("Production ALLOWED_ORIGINS entries must use HTTPS.")
    if not settings.trusted_hosts or "*" in settings.trusted_hosts:
        errors.append("TRUSTED_HOSTS must be an explicit non-wildcard allowlist.")
    if not any(host not in LOCAL_TRUSTED_HOSTS for host in settings.trusted_hosts):
        errors.append("TRUSTED_HOSTS must include the production API hostname.")
    if not biography_ready:
        errors.append("app/data/biography.md must exist and contain biography content.")
    return errors


@lru_cache
def get_settings() -> Settings:
    """Load application settings from the process environment and local .env file."""

    load_dotenv(ENV_PATH)

    return Settings(
        app_environment=os.getenv("APP_ENV", "development"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "15")),
        openai_max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "1")),
        openai_max_output_tokens=int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "350")),
        allowed_origins=_parse_allowed_origins(os.getenv("ALLOWED_ORIGINS", "")),
        trusted_hosts=_parse_csv(
            os.getenv("TRUSTED_HOSTS", ",".join(LOCAL_TRUSTED_HOSTS))
        ),
        trusted_proxy_cidrs=_parse_csv(os.getenv("TRUSTED_PROXY_CIDRS", "")),
        chat_api_secret=os.getenv("CHAT_API_SECRET", ""),
        chat_rate_limit=int(os.getenv("CHAT_RATE_LIMIT", "10")),
        chat_global_rate_limit=int(os.getenv("CHAT_GLOBAL_RATE_LIMIT", "60")),
        chat_rate_limit_window_seconds=int(
            os.getenv("CHAT_RATE_LIMIT_WINDOW_SECONDS", "60")
        ),
        chat_rate_limit_max_keys=int(os.getenv("CHAT_RATE_LIMIT_MAX_KEYS", "10000")),
        chat_max_concurrency=int(os.getenv("CHAT_MAX_CONCURRENCY", "4")),
        chat_concurrency_wait_seconds=float(
            os.getenv("CHAT_CONCURRENCY_WAIT_SECONDS", "0.25")
        ),
        chat_max_body_bytes=int(os.getenv("CHAT_MAX_BODY_BYTES", "16384")),
        log_chat_content=_parse_bool(os.getenv("LOG_CHAT_CONTENT", "true")),
        api_title=os.getenv("API_TITLE", "Interview"),
        api_version=os.getenv("API_VERSION", "0.1.0"),
    )
