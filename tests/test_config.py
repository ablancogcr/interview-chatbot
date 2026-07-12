import pytest

from app.config import Settings, _parse_bool, production_configuration_errors


def test_production_configuration_requires_security_controls() -> None:
    settings = Settings(app_environment="production")

    errors = production_configuration_errors(settings, biography_ready=False)

    assert any("OPENAI_API_KEY" in error for error in errors)
    assert any("CHAT_API_SECRET" in error for error in errors)
    assert any("TRUSTED_HOSTS" in error for error in errors)
    assert any("biography.md" in error for error in errors)


def test_valid_production_configuration_passes() -> None:
    settings = Settings(
        app_environment="production",
        openai_api_key="test-key",
        chat_api_secret="x" * 32,
        allowed_origins=["https://andresblanco.dev"],
        trusted_hosts=["api.andresblanco.dev"],
    )

    assert production_configuration_errors(settings, biography_ready=True) == []


def test_production_origin_requires_https() -> None:
    settings = Settings(
        app_environment="production",
        openai_api_key="test-key",
        chat_api_secret="x" * 32,
        allowed_origins=["http://andresblanco.dev"],
        trusted_hosts=["api.andresblanco.dev"],
    )

    errors = production_configuration_errors(settings, biography_ready=True)

    assert any("HTTPS" in error for error in errors)


@pytest.mark.parametrize("value", ["true", "1", "YES", "on"])
def test_parse_bool_accepts_enabled_values(value: str) -> None:
    assert _parse_bool(value) is True


@pytest.mark.parametrize("value", ["false", "0", "NO", "off"])
def test_parse_bool_accepts_disabled_values(value: str) -> None:
    assert _parse_bool(value) is False
