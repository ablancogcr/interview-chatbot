import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import Settings, _parse_allowed_origins
from app.security import (
    ConcurrencyLimiter,
    RateLimiter,
    enforce_chat_access,
    get_client_ip,
    privacy_safe_client_id,
)


def make_request(
    headers: dict[str, str] | None = None,
    *,
    client_host: str = "127.0.0.1",
    method: str = "POST",
    path: str = "/chat",
) -> Request:
    """Build a minimal Starlette request for security helper tests."""

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in (headers or {}).items()
            ],
            "client": (client_host, 12345),
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


def test_rate_limiter_removes_expired_buckets() -> None:
    """Expired identities do not remain in memory indefinitely."""

    limiter = RateLimiter(
        max_requests=2,
        window_seconds=10,
        max_keys=2,
        cleanup_interval_seconds=1,
    )
    limiter.check("first", now=lambda: 100.0)
    limiter.check("second", now=lambda: 100.0)

    limiter.check("third", now=lambda: 111.0)

    assert limiter.tracked_keys == 1


def test_rate_limiter_rejects_new_keys_at_capacity() -> None:
    """The limiter bounds memory when all retained buckets are active."""

    limiter = RateLimiter(max_requests=2, window_seconds=60, max_keys=1)
    limiter.check("first", now=lambda: 100.0)

    with pytest.raises(HTTPException) as exc_info:
        limiter.check("second", now=lambda: 100.0)

    assert exc_info.value.status_code == 429


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


def test_malformed_host_cannot_change_protected_scope_path() -> None:
    """Access control uses the routed ASGI path, not reconstructed request.url."""

    settings = Settings(chat_api_secret="server-secret")
    request = make_request({"Host": "example.com/health?ignored="})

    assert request.scope["path"] == "/chat"

    with pytest.raises(HTTPException) as exc_info:
        enforce_chat_access(request, settings)

    assert exc_info.value.status_code == 401


def test_forwarded_for_is_ignored_from_untrusted_peer() -> None:
    """Direct callers cannot spoof their rate-limit identity."""

    request = make_request(
        {"X-Forwarded-For": "198.51.100.25"},
        client_host="203.0.113.10",
    )

    assert get_client_ip(request, ["10.0.0.0/8"]) == "203.0.113.10"


def test_forwarded_for_uses_rightmost_untrusted_address() -> None:
    """Trusted proxy chains resolve to the nearest untrusted client address."""

    request = make_request(
        {"X-Forwarded-For": "198.51.100.25, 10.1.1.5"},
        client_host="10.2.2.6",
    )

    assert get_client_ip(request, ["10.0.0.0/8"]) == "198.51.100.25"


def test_malformed_forwarded_for_from_trusted_proxy_is_rejected() -> None:
    """Malformed trusted forwarding data cannot create arbitrary buckets."""

    request = make_request(
        {"X-Forwarded-For": "not-an-ip"},
        client_host="10.2.2.6",
    )

    with pytest.raises(HTTPException) as exc_info:
        get_client_ip(request, ["10.0.0.0/8"])

    assert exc_info.value.status_code == 400


def test_browser_origin_is_checked_even_with_valid_secret() -> None:
    """Browser requests require both the server secret and an allowed origin."""

    settings = Settings(
        allowed_origins=["https://andresblanco.dev"],
        chat_api_secret="server-secret",
    )

    with pytest.raises(HTTPException) as exc_info:
        enforce_chat_access(
            make_request(
                {
                    "Origin": "https://attacker.example",
                    "X-Interview-Secret": "server-secret",
                }
            ),
            settings,
        )

    assert exc_info.value.status_code == 403


def test_privacy_identifier_does_not_expose_ip() -> None:
    """Logs and provider safety identifiers do not contain the raw address."""

    identifier = privacy_safe_client_id("198.51.100.25", "a-strong-secret")

    assert identifier.startswith("visitor_")
    assert "198.51.100.25" not in identifier


def test_concurrency_limiter_rejects_when_capacity_is_busy() -> None:
    """Concurrent chat work is bounded and capacity is always reusable."""

    async def exercise() -> None:
        limiter = ConcurrencyLimiter(max_concurrency=1, wait_seconds=0.01)
        await limiter.acquire()
        try:
            with pytest.raises(HTTPException) as exc_info:
                await limiter.acquire()
            assert exc_info.value.status_code == 503
        finally:
            limiter.release()

        await limiter.acquire()
        limiter.release()

    asyncio.run(exercise())
