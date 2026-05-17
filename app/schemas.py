from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request body for the chat endpoint."""

    question: str = Field(..., min_length=1, max_length=1000)


class ChatResponse(BaseModel):
    """Response body returned by the chat endpoint."""

    answer: str
    sources: list[str]


class HealthResponse(BaseModel):
    """Response body returned by the health endpoint."""

    status: str


class ApiInfoResponse(BaseModel):
    """Response body returned by the root endpoint."""

    name: str
    status: str
    docs: str
