import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseModel):
    """Runtime configuration loaded from environment variables."""

    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4.1-mini")
    allowed_origins: list[str] = Field(default_factory=list)
    chat_api_secret: str = Field(default="")
    api_title: str = Field(default="Interview")
    api_version: str = Field(default="0.1.0")


def _parse_allowed_origins(value: str) -> list[str]:
    """Convert a comma-separated origin list into normalized origin strings."""

    return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Load application settings from the process environment and local .env file."""

    load_dotenv(ENV_PATH)

    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        allowed_origins=_parse_allowed_origins(os.getenv("ALLOWED_ORIGINS", "")),
        chat_api_secret=os.getenv("CHAT_API_SECRET", ""),
        api_title=os.getenv("API_TITLE", "Interview"),
        api_version=os.getenv("API_VERSION", "0.1.0"),
    )
