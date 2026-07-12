import pytest
from pydantic import ValidationError

from app.schemas import ChatRequest


@pytest.mark.parametrize("question", ["   ", "\t\n", "!!!"])
def test_question_rejects_non_readable_input(question: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(question=question)


def test_question_is_stripped() -> None:
    assert ChatRequest(question="  What has Andres built?  ").question == (
        "What has Andres built?"
    )


def test_question_rejects_more_than_1000_characters_after_stripping() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(question="a" * 1001)
