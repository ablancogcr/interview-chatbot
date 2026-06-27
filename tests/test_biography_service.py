from app.services import biography_service


def test_split_sections_parses_metadata_and_excludes_it_from_context() -> None:
    markdown = """## Web Analytics Experience
Tags: analytics, BigQuery, dashboards
Category: Experience

Built reporting pipelines and dashboard systems.
"""

    sections = biography_service.split_sections(markdown)

    assert len(sections) == 1
    assert sections[0].title == "Web Analytics Experience"
    assert sections[0].tags == ("analytics", "BigQuery", "dashboards")
    assert sections[0].category == "Experience"
    assert "Tags:" not in sections[0].content
    assert "Category:" not in sections[0].content

    context = biography_service.format_context(sections)

    assert "## Web Analytics Experience" in context
    assert "Built reporting pipelines" in context
    assert "Tags:" not in context
    assert "Category:" not in context


def test_retrieve_sections_prefers_exact_interview_question(
    monkeypatch,
) -> None:
    markdown = """## Technical Profile
Python, SQL, dashboards, and web analytics experience.

### Tell me about yourself.
I am an analytics and automation professional with a technical background.

## Other Background
General professional information.
"""
    monkeypatch.setattr(biography_service, "load_biography", lambda: markdown)

    sections = biography_service.retrieve_sections("Tell me about yourself.")

    assert sections[0].title == "Tell me about yourself."


def test_retrieve_sections_uses_tag_matches(monkeypatch) -> None:
    markdown = """## Reporting Project
Tags: ETL, BigQuery, analytics engineering

Built automated reporting for business stakeholders.

## Customer Service
Managed support teams and service quality.
"""
    monkeypatch.setattr(biography_service, "load_biography", lambda: markdown)

    sections = biography_service.retrieve_sections("What ETL work has Andres done?")

    assert sections[0].title == "Reporting Project"


def test_retrieve_sections_bm25_prefers_specific_section(monkeypatch) -> None:
    markdown = """## Professional Summary
Analytics professional with broad experience across reporting and operations.

## Web Analytics Data Pipeline
Built BigQuery SQL pipelines for dashboard automation and web analytics reporting.

## Customer Service
Led customer support teams and improved operational workflows.
"""
    monkeypatch.setattr(biography_service, "load_biography", lambda: markdown)

    sections = biography_service.retrieve_sections(
        "Which BigQuery SQL dashboard project has Andres built?"
    )

    assert sections[0].title == "Web Analytics Data Pipeline"


def test_retrieve_sections_returns_first_sections_for_empty_keywords(monkeypatch) -> None:
    markdown = """## First
First section.

## Second
Second section.

## Third
Third section.

## Fourth
Fourth section.
"""
    monkeypatch.setattr(biography_service, "load_biography", lambda: markdown)

    sections = biography_service.retrieve_sections("to be of me")

    assert [section.title for section in sections] == ["First", "Second", "Third"]


def test_retrieve_sections_returns_empty_when_no_section_matches(monkeypatch) -> None:
    markdown = """## Professional Summary
Analytics and reporting background.

## Customer Service
Support leadership and operations.
"""
    monkeypatch.setattr(biography_service, "load_biography", lambda: markdown)

    sections = biography_service.retrieve_sections("Kubernetes infrastructure")

    assert sections == []
    assert (
        biography_service.format_context(sections)
        == "No relevant biography sections were found for this question."
    )
