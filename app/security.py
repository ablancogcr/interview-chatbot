import time
from collections import defaultdict, deque
from collections.abc import Callable
from secrets import compare_digest

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
    ) -> None:
        """Create a limiter with a maximum request count per time window."""

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: defaultdict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: Callable[[], float] = time.monotonic) -> None:
        """Record a request for a key or raise HTTP 429 when the limit is exceeded."""

        current_time = now()
        cutoff = current_time - self.window_seconds
        request_times = self._requests[key]

        while request_times and request_times[0] <= cutoff:
            request_times.popleft()

        if len(request_times) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many chat requests. Please try again in a minute.",
            )

        request_times.append(current_time)


def get_client_ip(request: Request) -> str:
    """Return the best available client IP address for logging and rate limiting."""

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()

    if request.client:
        return request.client.host

    return "unknown"


def enforce_chat_origin(request: Request, settings: Settings) -> None:
    """Require browser chat requests to come from a configured allowed origin."""

    if request.url.path != "/chat":
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

    if request.url.path != "/chat":
        return

    if settings.chat_api_secret:
        provided_secret = request.headers.get(CHAT_SECRET_HEADER, "")
        if not compare_digest(provided_secret, settings.chat_api_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid chat API secret.",
            )
        return

    enforce_chat_origin(request, settings)
