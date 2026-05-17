import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings
from app.schemas import ApiInfoResponse, ChatRequest, ChatResponse, HealthResponse
from app.security import RateLimiter, enforce_chat_access, get_client_ip
from app.services.biography_service import format_context, retrieve_sections
from app.services.openai_service import OpenAIService


LOG_FILE_PATH = Path(__file__).resolve().parents[1] / "logs" / "chat.log"


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
chat_rate_limiter = RateLimiter()
chat_secret_scheme = APIKeyHeader(name="X-Interview-Secret", auto_error=False)

app = FastAPI(title=settings.api_title, version=settings.api_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def protect_chat_endpoint(request: Request, call_next):
    """Apply chat-only access checks and rate limiting before routing requests."""

    try:
        enforce_chat_access(request, settings)

        if request.url.path == "/chat" and request.method != "OPTIONS":
            chat_rate_limiter.check(get_client_ip(request))
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return await call_next(request)


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


@app.post("/chat", response_model=ChatResponse)
async def chat(
    http_request: Request,
    request: ChatRequest,
    openai_service: OpenAIService = Depends(get_openai_service),
    _chat_api_secret: str | None = Security(chat_secret_scheme),
) -> ChatResponse:
    """Answer a visitor question using retrieved biography sections."""

    sections = retrieve_sections(request.question)
    context = format_context(sections)
    openai_answer = await openai_service.answer_question(request.question, context)
    sources = [section.title for section in sections]

    logger.info(
        "chat_completed %s",
        json.dumps(
            {
                "client_ip": get_client_ip(http_request),
                "origin": http_request.headers.get("origin"),
                "model": settings.openai_model,
                "question": request.question,
                "answer": openai_answer.answer,
                "sources": sources,
                "token_usage": openai_answer.token_usage,
            },
            ensure_ascii=True,
        ),
    )

    return ChatResponse(
        answer=openai_answer.answer,
        sources=sources,
    )
