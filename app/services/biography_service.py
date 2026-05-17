import re
from dataclasses import dataclass
from pathlib import Path


BIOGRAPHY_PATH = Path(__file__).resolve().parents[1] / "data" / "biography.md"
BIOGRAPHY_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "biography.example.md"
)
MAX_SECTIONS = 3

STOP_WORDS = {
    "about",
    "after",
    "and",
    "are",
    "can",
    "did",
    "does",
    "for",
    "from",
    "has",
    "have",
    "his",
    "how",
    "into",
    "is",
    "me",
    "more",
    "of",
    "on",
    "or",
    "tell",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class BiographySection:
    """A retrievable section from the controlled biography markdown file."""

    title: str
    content: str


def _keywords(text: str) -> set[str]:
    """Extract normalized non-stopword keywords from text for overlap scoring."""

    words = re.findall(r"[a-zA-Z0-9']+", text.lower())
    return {word for word in words if len(word) > 2 and word not in STOP_WORDS}


def load_biography(path: Path = BIOGRAPHY_PATH) -> str:
    """Load the private biography file, falling back to the public placeholder."""

    if path.exists():
        return path.read_text(encoding="utf-8")

    return BIOGRAPHY_EXAMPLE_PATH.read_text(encoding="utf-8")


def split_sections(markdown: str) -> list[BiographySection]:
    """Split markdown content into sections using markdown headings as titles."""

    sections: list[BiographySection] = []
    current_title = "Profile"
    current_lines: list[str] = []

    for line in markdown.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            if current_lines:
                sections.append(
                    BiographySection(
                        title=current_title,
                        content="\n".join(current_lines).strip(),
                    )
                )
            current_title = heading.group(2).strip()
            current_lines = []
            continue

        current_lines.append(line)

    if current_lines:
        sections.append(
            BiographySection(title=current_title, content="\n".join(current_lines).strip())
        )

    return [section for section in sections if section.content]


def retrieve_sections(question: str, limit: int = MAX_SECTIONS) -> list[BiographySection]:
    """Return the highest-scoring biography sections for a visitor question."""

    sections = split_sections(load_biography())
    question_keywords = _keywords(question)

    if not question_keywords:
        return sections[:limit]

    scored_sections: list[tuple[int, int, BiographySection]] = []
    for index, section in enumerate(sections):
        section_keywords = _keywords(f"{section.title} {section.content}")
        score = len(question_keywords & section_keywords)
        scored_sections.append((score, -index, section))

    scored_sections.sort(reverse=True, key=lambda item: (item[0], item[1]))
    matches = [section for score, _, section in scored_sections if score > 0]

    return matches[:limit]


def format_context(sections: list[BiographySection]) -> str:
    """Format selected biography sections into context for the OpenAI prompt."""

    if not sections:
        return "No relevant biography sections were found for this question."

    return "\n\n".join(f"## {section.title}\n{section.content}" for section in sections)
