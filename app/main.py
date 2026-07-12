import json
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import (
    MIN_CHAT_SECRET_LENGTH,
    Settings,
    get_settings,
    production_configuration_errors,
)
from app.schemas import (
    ApiInfoResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    ReadinessResponse,
)
from app.security import (
    ConcurrencyLimiter,
    RateLimiter,
    RequestBodyLimitMiddleware,
    enforce_chat_access,
    get_client_ip,
    privacy_safe_client_id,
)
from app.services.biography_service import (
    biography_file_is_ready,
    format_context,
    retrieve_sections,
)
from app.services.openai_service import OpenAIService, OpenAIServiceError


LOG_FILE_PATH = Path(__file__).resolve().parents[1] / "logs" / "chat.log"
INSTANCE_HASH_SECRET = secrets.token_urlsafe(32)


def configure_logger() -> logging.Logger:
    """Configure console and file logging for chat events."""

    logging.basicConfig(level=logging.INFO)
    app_logger = logging.getLogger("interview_api")
    app_logger.setLevel(logging.INFO)

    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not any(
        isinstance(handler, RotatingFileHandler)
        and getattr(handler, "baseFilename", None) == str(LOG_FILE_PATH)
        for handler in app_logger.handlers
    ):
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        app_logger.addHandler(file_handler)

    return app_logger


logger = configure_logger()

settings = get_settings()
chat_rate_limiter = RateLimiter(
    max_requests=settings.chat_rate_limit,
    window_seconds=settings.chat_rate_limit_window_seconds,
    max_keys=settings.chat_rate_limit_max_keys,
)
global_chat_rate_limiter = RateLimiter(
    max_requests=settings.chat_global_rate_limit,
    window_seconds=settings.chat_rate_limit_window_seconds,
    max_keys=1,
)
chat_concurrency_limiter = ConcurrencyLimiter(
    max_concurrency=settings.chat_max_concurrency,
    wait_seconds=settings.chat_concurrency_wait_seconds,
)
chat_secret_scheme = APIKeyHeader(name="X-Interview-Secret", auto_error=False)


def _readiness_checks(current_settings: Settings) -> dict[str, bool]:
    """Build non-sensitive dependency and production-safety readiness checks."""

    biography_ready = biography_file_is_ready()
    production_errors = production_configuration_errors(
        current_settings,
        biography_ready=biography_ready,
    )
    return {
        "openai_api_key": bool(current_settings.openai_api_key),
        "biography": biography_ready,
        "chat_secret": (
            not current_settings.is_production
            or len(current_settings.chat_api_secret) >= MIN_CHAT_SECRET_LENGTH
        ),
        "trusted_hosts": bool(current_settings.trusted_hosts)
        and "*" not in current_settings.trusted_hosts,
        "production_configuration": not production_errors,
    }


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Fail production startup when required safeguards are missing."""

    errors = production_configuration_errors(
        settings,
        biography_ready=biography_file_is_ready(),
    )
    if errors:
        raise RuntimeError("Invalid production configuration: " + " ".join(errors))
    yield


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Interview-Secret"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.trusted_hosts,
)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_body_bytes=settings.chat_max_body_bytes,
)


@app.middleware("http")
async def protect_chat_endpoint(request: Request, call_next):
    """Apply chat-only access checks and rate limiting before routing requests."""

    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    request.state.started_at = time.monotonic()

    try:
        enforce_chat_access(request, settings)

        if request.scope.get("path") == "/chat" and request.method != "OPTIONS":
            client_ip = get_client_ip(request, settings.trusted_proxy_cidrs)
            identifier_secret = (
                settings.chat_api_secret
                or settings.openai_api_key
                or INSTANCE_HASH_SECRET
            )
            request.state.client_id = privacy_safe_client_id(
                client_ip,
                identifier_secret,
            )
            global_chat_rate_limiter.check("global")
            chat_rate_limiter.check(client_ip)
    except HTTPException as exc:
        error_headers = {
            "X-Request-ID": request_id,
            "X-Content-Type-Options": "nosniff",
        }
        if request.scope.get("path") == "/chat":
            error_headers["Cache-Control"] = "no-store"
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=error_headers,
        )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.scope.get("path") == "/chat":
        response.headers["Cache-Control"] = "no-store"
    return response


def get_openai_service(
    current_settings: Settings = Depends(get_settings),
) -> OpenAIService:
    """Provide an OpenAI service or return 503 when the API key is missing."""

    if not current_settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured.",
        )

    return OpenAIService(current_settings)


@app.get("/", response_model=ApiInfoResponse)
async def root() -> ApiInfoResponse:
    """Return basic API metadata for visitors and uptime checks."""

    return ApiInfoResponse(name=settings.api_title, status="ok", docs="/docs")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return a lightweight health check response."""

    return HealthResponse(status="ok")


@app.get("/ready", response_model=ReadinessResponse)
async def readiness() -> JSONResponse | ReadinessResponse:
    """Return deployment readiness without exposing configuration values."""

    checks = _readiness_checks(settings)
    ready = all(checks.values())
    payload = ReadinessResponse(
        status="ready" if ready else "not_ready",
        checks=checks,
    )
    if ready:
        return payload
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload.model_dump(),
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    http_request: Request,
    request: ChatRequest,
    openai_service: OpenAIService = Depends(get_openai_service),
    _chat_api_secret: str | None = Security(chat_secret_scheme),
) -> ChatResponse:
    """Answer a visitor question using retrieved biography sections."""

    await chat_concurrency_limiter.acquire()
    try:
        sections = retrieve_sections(
            request.question,
            allow_example=not settings.is_production,
        )
        context = format_context(sections)
        openai_answer = await openai_service.answer_question(
            request.question,
            context,
            safety_identifier=http_request.state.client_id,
        )
        sources = [section.title for section in sections]
    except OpenAIServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    finally:
        chat_concurrency_limiter.release()

    log_event = {
        "request_id": http_request.state.request_id,
        "client_id": http_request.state.client_id,
        "status": status.HTTP_200_OK,
        "latency_ms": round(
            (time.monotonic() - http_request.state.started_at) * 1000
        ),
        "model": settings.openai_model,
        "sources": sources,
        "token_usage": openai_answer.token_usage,
    }
    if settings.log_chat_content:
        log_event["prompt"] = request.question
        log_event["answer"] = openai_answer.answer

    logger.info(
        "chat_completed %s",
        json.dumps(log_event, ensure_ascii=True),
    )

    return ChatResponse(
        answer=openai_answer.answer,
        sources=sources,
    )
