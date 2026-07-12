import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from math import log
from pathlib import Path


BIOGRAPHY_PATH = Path(__file__).resolve().parents[1] / "data" / "biography.md"
BIOGRAPHY_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "biography.example.md"
)
MAX_SECTIONS = 3
TITLE_WEIGHT = 3
TAG_WEIGHT = 4
QUESTION_TITLE_EXACT_BOOST = 100.0
QUESTION_TITLE_NEAR_BOOST = 55.0
TAG_MATCH_BOOST = 8.0
BM25_K1 = 1.5
BM25_B = 0.75

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
    tags: tuple[str, ...] = ()
    category: str | None = None
    heading_level: int = 1
    index: int = 0


def _tokens(text: str) -> list[str]:
    """Extract normalized non-stopword tokens from text."""

    words = re.findall(r"[a-zA-Z0-9']+", text.lower())
    return [word for word in words if len(word) > 2 and word not in STOP_WORDS]


def _keywords(text: str) -> set[str]:
    """Extract normalized non-stopword keywords from text."""

    return set(_tokens(text))


def _normalize_question(text: str) -> str:
    """Normalize a question or heading for exact and fuzzy title matching."""

    return " ".join(re.findall(r"[a-zA-Z0-9']+", text.lower()))


def _split_metadata_values(value: str) -> tuple[str, ...]:
    """Split comma- or semicolon-separated metadata values."""

    return tuple(part.strip() for part in re.split(r"[,;]", value) if part.strip())


def _build_section(
    title: str,
    heading_level: int,
    index: int,
    lines: list[str],
) -> BiographySection:
    """Build a section and remove supported retrieval metadata from content."""

    tags: list[str] = []
    category: str | None = None
    content_lines: list[str] = []
    metadata_open = True

    for line in lines:
        stripped = line.strip()
        metadata_match = re.match(r"^(tags?|category):\s*(.+?)\s*$", stripped, re.I)

        if metadata_open and not stripped and not content_lines:
            continue

        if metadata_open and metadata_match:
            key = metadata_match.group(1).lower()
            value = metadata_match.group(2)
            if key.startswith("tag"):
                tags.extend(_split_metadata_values(value))
            else:
                category = value.strip()
            continue

        metadata_open = False
        content_lines.append(line)

    return BiographySection(
        title=title,
        content="\n".join(content_lines).strip(),
        tags=tuple(tags),
        category=category,
        heading_level=heading_level,
        index=index,
    )


def biography_file_is_ready(path: Path = BIOGRAPHY_PATH) -> bool:
    """Return whether the real biography exists and contains non-whitespace text."""

    return path.is_file() and bool(path.read_text(encoding="utf-8").strip())


def load_biography(
    path: Path = BIOGRAPHY_PATH,
    *,
    allow_example: bool = True,
) -> str:
    """Load the biography, allowing the public placeholder only in development."""

    if biography_file_is_ready(path):
        return path.read_text(encoding="utf-8").strip()

    if not allow_example:
        raise RuntimeError("The production biography is missing or empty.")

    return BIOGRAPHY_EXAMPLE_PATH.read_text(encoding="utf-8")


def split_sections(markdown: str) -> list[BiographySection]:
    """Split markdown content into sections using markdown headings as titles."""

    sections: list[BiographySection] = []
    current_title = "Profile"
    current_heading_level = 1
    current_lines: list[str] = []
    section_index = 0

    for line in markdown.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            if current_lines:
                sections.append(
                    _build_section(
                        current_title,
                        current_heading_level,
                        section_index,
                        current_lines,
                    )
                )
                section_index += 1
            current_title = heading.group(2).strip()
            current_heading_level = len(heading.group(1))
            current_lines = []
            continue

        current_lines.append(line)

    if current_lines:
        sections.append(
            _build_section(
                current_title,
                current_heading_level,
                section_index,
                current_lines,
            )
        )

    return [section for section in sections if section.content]


def _section_tokens(section: BiographySection) -> list[str]:
    """Return weighted tokens for hybrid lexical retrieval."""

    tokens: list[str] = []
    tokens.extend(_tokens(section.title) * TITLE_WEIGHT)
    tokens.extend(_tokens(" ".join(section.tags)) * TAG_WEIGHT)
    if section.category:
        tokens.extend(_tokens(section.category) * TAG_WEIGHT)
    tokens.extend(_tokens(section.content))
    return tokens


def _bm25_scores(
    question_tokens: list[str],
    sections: list[BiographySection],
) -> dict[int, float]:
    """Score sections with a small local BM25 implementation."""

    document_tokens = [_section_tokens(section) for section in sections]
    document_lengths = [len(tokens) for tokens in document_tokens]
    average_length = (
        sum(document_lengths) / len(document_lengths) if document_lengths else 0.0
    )
    document_frequencies: Counter[str] = Counter()

    for tokens in document_tokens:
        document_frequencies.update(set(tokens))

    scores: dict[int, float] = {}
    total_documents = len(sections)

    for section, tokens, document_length in zip(
        sections, document_tokens, document_lengths, strict=True
    ):
        term_frequencies = Counter(tokens)
        score = 0.0

        for token in set(question_tokens):
            frequency = term_frequencies[token]
            if not frequency:
                continue

            document_frequency = document_frequencies[token]
            inverse_document_frequency = log(
                1 + (total_documents - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            length_normalization = 1 - BM25_B
            if average_length:
                length_normalization += BM25_B * document_length / average_length
            denominator = frequency + BM25_K1 * length_normalization
            score += (
                inverse_document_frequency
                * frequency
                * (BM25_K1 + 1)
                / denominator
            )

        scores[section.index] = score

    return scores


def _question_title_score(question: str, section: BiographySection) -> float:
    """Boost exact or near-exact question matches against interview headings."""

    if section.heading_level < 3:
        return 0.0

    normalized_question = _normalize_question(question)
    normalized_title = _normalize_question(section.title)
    if not normalized_question or not normalized_title:
        return 0.0

    if normalized_question == normalized_title:
        return QUESTION_TITLE_EXACT_BOOST

    similarity = SequenceMatcher(
        None, normalized_question, normalized_title
    ).ratio()
    if similarity >= 0.85:
        return QUESTION_TITLE_NEAR_BOOST

    return 0.0


def _tag_score(question_keywords: set[str], section: BiographySection) -> float:
    """Boost sections whose explicit metadata matches the question."""

    metadata_keywords = _keywords(" ".join(section.tags))
    if section.category:
        metadata_keywords.update(_keywords(section.category))

    return len(question_keywords & metadata_keywords) * TAG_MATCH_BOOST


def retrieve_sections(
    question: str,
    limit: int = MAX_SECTIONS,
    *,
    allow_example: bool = True,
) -> list[BiographySection]:
    """Return the highest-scoring biography sections for a visitor question."""

    sections = split_sections(load_biography(allow_example=allow_example))
    question_tokens = _tokens(question)
    question_keywords = set(question_tokens)

    if not question_keywords:
        return sections[:limit]

    bm25_scores = _bm25_scores(question_tokens, sections)
    scored_sections: list[tuple[float, int, BiographySection]] = []
    for section in sections:
        score = (
            bm25_scores.get(section.index, 0.0)
            + _question_title_score(question, section)
            + _tag_score(question_keywords, section)
        )
        scored_sections.append((score, -section.index, section))

    scored_sections.sort(reverse=True, key=lambda item: (item[0], item[1]))
    matches = [section for score, _, section in scored_sections if score > 0]

    return matches[:limit]


def format_context(sections: list[BiographySection]) -> str:
    """Format selected biography sections into context for the OpenAI prompt."""

    if not sections:
        return "No relevant biography sections were found for this question."

    return "\n\n".join(f"## {section.title}\n{section.content}" for section in sections)
