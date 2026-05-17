# AGENTS.md

## Project Overview

This project is a standalone FastAPI backend for Andres Blanco's portfolio website.

It powers an "Interview Andres" chatbot where visitors can ask questions about Andres's professional background, skills, work experience, and projects.

The chatbot must answer using a controlled biography document located at:

app/data/biography.md

The frontend portfolio website will call this API from a separate Next.js codebase.

## Tech Stack

Use:

- Python
- FastAPI
- OpenAI Python SDK
- Pydantic
- Uvicorn
- Railway
- uv for dependency and environment management

Do not use LangChain or LangGraph.

Do not add a database.

Do not add a vector database.

Do not add authentication.

## Dependency Management

Use uv instead of pip.

Use:

- pyproject.toml
- uv.lock
- uv sync
- uv run

Do not create requirements.txt unless explicitly requested later.

Do not instruct users to install dependencies with pip.

Development commands:

```bash
uv sync
uv run uvicorn app.main:app --reload
uv run pytest