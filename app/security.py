import asyncio
import hashlib
import hmac
import time
from collections import deque
from collections.abc import Callable
from ipaddress import ip_address, ip_network
from secrets import compare_digest
from typing import Any

from fastapi import HTTPException, Request, status

from app.config import Settings


CHAT_RATE_LIMIT = 10
CHAT_RATE_LIMIT_WINDOW_SECONDS = 60
CHAT_SECRET_HEADER = "x-interview-secret"


class RateLimiter:
    """Simple in-memory sliding-window rate limiter for chat requests."""

    def __init__(
        self,
        max_requests: int = CHAT_RATE_LIMIT,
        window_seconds: int = CHAT_RATE_LIMIT_WINDOW_SECONDS,
        max_keys: int = 10_000,
        cleanup_interval_seconds: float | None = None,
    ) -> None:
        """Create a limiter with a maximum request count per time window."""

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.cleanup_interval_seconds = cleanup_interval_seconds or window_seconds
        self._requests: dict[str, deque[float]] = {}
        self._last_cleanup = 0.0

    @property
    def tracked_keys(self) -> int:
        """Return the current number of retained limiter buckets."""

        return len(self._requests)

    def _cleanup(self, current_time: float) -> None:
        """Remove expired buckets at a bounded interval."""

        if current_time - self._last_cleanup < self.cleanup_interval_seconds:
            return

        cutoff = current_time - self.window_seconds
        stale_keys = [
            key
            for key, timestamps in self._requests.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for key in stale_keys:
            del self._requests[key]
        self._last_cleanup = current_time

    def check(self, key: str, now: Callable[[], float] = time.monotonic) -> None:
        """Record a request for a key or raise HTTP 429 when the limit is exceeded."""

        current_time = now()
        cutoff = current_time - self.window_seconds
        self._cleanup(current_time)

        request_times = self._requests.get(key)
        if request_times is None:
            if len(self._requests) >= self.max_keys:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit capacity reached. Please try again later.",
                )
            request_times = deque()
            self._requests[key] = request_times

        while request_times and request_times[0] <= cutoff:
            request_times.popleft()

        if len(request_times) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many chat requests. Please try again in a minute.",
            )

        request_times.append(current_time)


class ConcurrencyLimiter:
    """Bound simultaneous chat work and fail quickly when capacity is exhausted."""

    def __init__(self, max_concurrency: int, wait_seconds: float) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._wait_seconds = wait_seconds

    async def acquire(self) -> None:
        """Acquire capacity or raise HTTP 503 after the configured short wait."""

        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self._wait_seconds,
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chat is busy. Please try again shortly.",
            ) from exc

    def release(self) -> None:
        """Release one unit of chat capacity."""

        self._semaphore.release()


class PayloadTooLargeError(Exception):
    """Raised internally when an HTTP request exceeds its body limit."""


class RequestBodyLimitMiddleware:
    """Enforce a streaming request-body limit for one configured route."""

    def __init__(self, app: Any, max_body_bytes: int, path: str = "/chat") -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.path = path

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_body_bytes:
                    await self._send_too_large(send)
                    return
            except ValueError:
                await self._send_too_large(send)
                return

        received_bytes = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    raise PayloadTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except PayloadTooLargeError:
            await self._send_too_large(send)

    @staticmethod
    async def _send_too_large(send: Any) -> None:
        body = b'{"detail":"Request body is too large."}'
        await send(
            {
                "type": "http.response.start",
                "status": status.HTTP_413_CONTENT_TOO_LARGE,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def get_client_ip(request: Request, trusted_proxy_cidrs: list[str] | None = None) -> str:
    """Return a validated client IP, trusting forwarding only from known proxies."""

    peer_host = request.client.host if request.client else ""
    try:
        peer_ip = ip_address(peer_host)
    except ValueError:
        return "unknown"

    trusted_networks = [
        ip_network(cidr, strict=False) for cidr in (trusted_proxy_cidrs or [])
    ]
    if not any(peer_ip in network for network in trusted_networks):
        return peer_ip.compressed

    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return peer_ip.compressed

    try:
        forwarded_ips = [
            ip_address(value.strip())
            for value in forwarded_for.split(",")
            if value.strip()
        ]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid forwarded client address.",
        ) from exc

    if not forwarded_ips:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid forwarded client address.",
        )

    for candidate in reversed(forwarded_ips):
        if not any(candidate in network for network in trusted_networks):
            return candidate.compressed
    return forwarded_ips[0].compressed


def privacy_safe_client_id(client_ip: str, secret: str) -> str:
    """Build a stable non-reversible identifier for logging and provider safety."""

    digest = hmac.new(
        secret.encode("utf-8"),
        client_ip.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"visitor_{digest[:24]}"


def enforce_chat_origin(request: Request, settings: Settings) -> None:
    """Require browser chat requests to come from a configured allowed origin."""

    if request.scope.get("path") != "/chat":
        return

    if not settings.allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chat origin protection is not configured.",
        )

    origin = request.headers.get("origin")
    if origin not in settings.allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This origin is not allowed to call the chat endpoint.",
        )


def enforce_chat_access(request: Request, settings: Settings) -> None:
    """Protect chat with a shared secret when configured, otherwise with Origin."""

    if request.scope.get("path") != "/chat":
        return

    if request.method == "OPTIONS":
        enforce_chat_origin(request, settings)
        return

    if settings.chat_api_secret:
        provided_secret = request.headers.get(CHAT_SECRET_HEADER, "")
        if not compare_digest(provided_secret, settings.chat_api_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid chat API secret.",
            )
        if request.headers.get("origin"):
            enforce_chat_origin(request, settings)
        return

    enforce_chat_origin(request, settings)
