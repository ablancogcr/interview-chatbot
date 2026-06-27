from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config import Settings


SYSTEM_PROMPT = """You are the Interview Andres assistant for Andres Blanco's portfolio.
Answer only from the provided biography context.
Do not invent experience, companies, dates, credentials, results, or technologies.
Answer as Andres in first person by default, using I, me, and my.
Keep the tone personal, warm, concise, and professional.
Make clear when an answer is based on Andres's profile without sounding distant or robotic.
If the answer is unavailable, say: "I can't answer that question yet, you can reach out to me anytime, my contact details are at the Contact page!" or use a similar warm first-person response with the same intent.
Keep answers useful for recruiters, hiring managers, collaborators, and potential clients."""


@dataclass(frozen=True)
class OpenAIAnswer:
    """OpenAI answer text plus token usage metadata for logging."""

    answer: str
    token_usage: dict[str, int | None]


class OpenAIService:
    """Client wrapper for generating biography-grounded answers with OpenAI."""

    def __init__(self, settings: Settings) -> None:
        """Create an OpenAI client from application settings."""

        self._settings = settings
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def answer_question(self, question: str, context: str) -> OpenAIAnswer:
        """Generate a first-person answer using the provided biography context."""

        response = await self._client.responses.create(
            model=self._settings.openai_model,
            instructions=SYSTEM_PROMPT,
            input=(
                "Biography context:\n"
                f"{context}\n\n"
                "Visitor question:\n"
                f"{question}"
            ),
        )

        usage = getattr(response, "usage", None)

        return OpenAIAnswer(
            answer=response.output_text.strip(),
            token_usage={
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            },
        )
