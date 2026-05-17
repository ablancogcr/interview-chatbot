import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import Settings, _parse_allowed_origins
from app.security import RateLimiter, enforce_chat_access


def make_request(headers: dict[str, str] | None = None) -> Request:
    """Build a minimal Starlette request for security helper tests."""

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/chat",
            "headers": [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in (headers or {}).items()
            ],
            "client": ("127.0.0.1", 12345),
            "scheme": "https",
            "server": ("testserver", 443),
            "query_string": b"",
        }
    )


def test_chat_rejects_disallowed_origin() -> None:
    """Origin protection rejects browser requests from unapproved origins."""

    settings = Settings(allowed_origins=["https://andresblanco.dev"])

    with pytest.raises(HTTPException) as exc_info:
        enforce_chat_access(make_request({"Origin": "https://example.com"}), settings)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "This origin is not allowed to call the chat endpoint."


def test_rate_limiter_rejects_after_limit() -> None:
    """Rate limiter raises HTTP 429 after the configured request count."""

    limiter = RateLimiter(max_requests=2, window_seconds=60)
    current_time = 100.0

    limiter.check("127.0.0.1", now=lambda: current_time)
    limiter.check("127.0.0.1", now=lambda: current_time)

    with pytest.raises(HTTPException) as exc_info:
        limiter.check("127.0.0.1", now=lambda: current_time)

    assert getattr(exc_info.value, "status_code") == 429


def test_allowed_origins_strip_trailing_slashes() -> None:
    """Allowed origin parsing normalizes accidental trailing slashes."""

    assert _parse_allowed_origins("https://andresblanco.dev/") == [
        "https://andresblanco.dev"
    ]


def test_chat_rejects_missing_origin() -> None:
    """Origin fallback rejects browser requests without an Origin header."""

    settings = Settings(allowed_origins=["https://andresblanco.dev"])

    with pytest.raises(HTTPException) as exc_info:
        enforce_chat_access(make_request(), settings)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "This origin is not allowed to call the chat endpoint."


def test_chat_secret_allows_server_to_server_request_without_origin() -> None:
    """Shared-secret mode allows server calls that do not include Origin."""

    settings = Settings(
        allowed_origins=["https://andresblanco.dev"],
        chat_api_secret="server-secret",
    )

    enforce_chat_access(make_request({"X-Interview-Secret": "server-secret"}), settings)


def test_chat_secret_rejects_missing_secret() -> None:
    """Shared-secret mode rejects calls that omit the private chat secret."""

    settings = Settings(
        allowed_origins=["https://andresblanco.dev"],
        chat_api_secret="server-secret",
    )

    with pytest.raises(HTTPException) as exc_info:
        enforce_chat_access(make_request({"Origin": "https://andresblanco.dev"}), settings)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid chat API secret."
