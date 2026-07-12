from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """Request body for the chat endpoint."""

    question: str = Field(..., min_length=1, max_length=1000)

    @field_validator("question", mode="before")
    @classmethod
    def normalize_question(cls, value: object) -> object:
        """Strip surrounding whitespace before length validation."""

        return value.strip() if isinstance(value, str) else value

    @field_validator("question")
    @classmethod
    def require_readable_question(cls, value: str) -> str:
        """Reject control-only or punctuation-only requests."""

        if not any(character.isalnum() for character in value):
            raise ValueError("Question must contain readable text.")
        return value


class ChatResponse(BaseModel):
    """Response body returned by the chat endpoint."""

    answer: str
    sources: list[str]


class HealthResponse(BaseModel):
    """Response body returned by the health endpoint."""

    status: str


class ReadinessResponse(BaseModel):
    """Non-sensitive readiness checks for deployment probes."""

    status: str
    checks: dict[str, bool]


class ApiInfoResponse(BaseModel):
    """Response body returned by the root endpoint."""

    name: str
    status: str
    docs: str
