import asyncio
import logging

import pytest

from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app, get_openai_service, settings
from app.services.openai_service import OpenAIAnswer, OpenAIServiceError


client = TestClient(app)


def auth_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if settings.chat_api_secret:
        headers["X-Interview-Secret"] = settings.chat_api_secret
    elif settings.allowed_origins:
        headers["Origin"] = settings.allowed_origins[0]
    return headers


class SuccessfulOpenAIService:
    async def answer_question(
        self,
        question: str,
        context: str,
        *,
        safety_identifier: str,
    ) -> OpenAIAnswer:
        return OpenAIAnswer(
            answer="A safe answer body.",
            token_usage={"input_tokens": 5, "output_tokens": 4, "total_tokens": 9},
        )


class FailingOpenAIService:
    async def answer_question(
        self,
        question: str,
        context: str,
        *,
        safety_identifier: str,
    ) -> OpenAIAnswer:
        raise OpenAIServiceError(503, "The interview service is unavailable.")


def test_malformed_host_is_rejected_before_chat_handler() -> None:
    headers = auth_headers()
    headers["Host"] = "testserver/health?ignored="

    response = client.post(
        "/chat",
        headers=headers,
        json={"question": "What has Andres built?"},
    )

    assert response.status_code == 400


def test_oversized_chat_body_is_rejected() -> None:
    headers = auth_headers()
    headers["Content-Type"] = "application/json"

    response = client.post(
        "/chat",
        headers=headers,
        content=b"x" * (settings.chat_max_body_bytes + 1),
    )

    assert response.status_code == 413


def test_whitespace_question_is_rejected_without_provider_call() -> None:
    app.dependency_overrides[get_openai_service] = lambda: SuccessfulOpenAIService()
    try:
        response = client.post(
            "/chat",
            headers=auth_headers(),
            json={"question": "   "},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def test_chat_logs_prompt_answer_and_safe_metadata_without_ip(caplog) -> None:
    app.dependency_overrides[get_openai_service] = lambda: SuccessfulOpenAIService()
    caplog.set_level(logging.INFO, logger="interview_api")
    try:
        response = client.post(
            "/chat",
            headers=auth_headers(),
            json={"question": "What is Andres's professional background?"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "request_id" in caplog.text
    assert "client_id" in caplog.text
    assert "What is Andres" in caplog.text
    assert "A safe answer body" in caplog.text
    assert "127.0.0.1" not in caplog.text


def test_chat_content_logging_can_be_disabled(caplog, monkeypatch) -> None:
    app.dependency_overrides[get_openai_service] = lambda: SuccessfulOpenAIService()
    monkeypatch.setattr(settings, "log_chat_content", False)
    caplog.set_level(logging.INFO, logger="interview_api")
    try:
        response = client.post(
            "/chat",
            headers=auth_headers(),
            json={"question": "Which projects has Andres built?"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Which projects has Andres" not in caplog.text
    assert "A safe answer body" not in caplog.text
    assert "request_id" in caplog.text


def test_provider_failure_returns_controlled_status() -> None:
    app.dependency_overrides[get_openai_service] = lambda: FailingOpenAIService()
    try:
        response = client.post(
            "/chat",
            headers=auth_headers(),
            json={"question": "What has Andres built?"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "The interview service is unavailable."}


def test_readiness_reports_checks_without_values(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "biography_file_is_ready", lambda: True)
    monkeypatch.setattr(settings, "openai_api_key", "configured")

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["openai_api_key"] is True
    assert "configured" not in response.text


def test_production_lifespan_fails_closed(monkeypatch) -> None:
    production_settings = settings.model_copy(
        update={
            "app_environment": "production",
            "openai_api_key": "",
            "chat_api_secret": "short",
        }
    )
    monkeypatch.setattr(main_module, "settings", production_settings)
    monkeypatch.setattr(main_module, "biography_file_is_ready", lambda: False)

    async def enter_lifespan() -> None:
        async with main_module.lifespan(app):
            pass

    with pytest.raises(RuntimeError, match="Invalid production configuration"):
        asyncio.run(enter_lifespan())


def test_cors_is_restricted() -> None:
    cors = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls is CORSMiddleware
    )

    assert cors.kwargs["allow_credentials"] is False
    assert set(cors.kwargs["allow_methods"]) == {"GET", "POST", "OPTIONS"}
    assert set(cors.kwargs["allow_headers"]) == {
        "Content-Type",
        "X-Interview-Secret",
    }
