# GroceryGenie - Backend Service

This is the FastAPI backend service for the GroceryGenie voice-first shopping assistant.

*   **Main documentation**: Refer to the main [root README](file:///d:/Project/GrocerGo/README.md).
*   **Web client**: Refer to the [Frontend README](file:///d:/Project/GrocerGo/frontend/README.md).

## Features
*   **FastAPI & SQLAlchemy**: Modern asynchronous REST APIs and ORM.
*   **Agent Orchestrator**: Sub-goal decomposition, dependency DAG executor, tool routing, and synthesis.
*   **Persistent Fact Classifier**: Custom LLM classifier that extracts persistent facts from customer conversations and saves them to Postgres.
*   **Local Speech Processing**: Speech-to-Text (ASR) via Parakeet and Text-to-Speech (TTS) via Piper, with emotional presets and barge-in.
*   **RAG System**: Hybrid Search using BM25 and Qdrant vector retrieval. Store layout query via Neo4j.

## Getting Started

### 1. Requirements
*   Python >= 3.12
*   [uv](https://github.com/astral-sh/uv)

### 2. Install Dependencies
Run from the root directory:
```bash
uv sync
```

### 3. Running Database Migrations
Initialize the Postgres schema:
```bash
$env:DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/grocergenie"
uv run alembic upgrade head
```

### 4. Running the Development Server
Start the local server:
```bash
$env:PYTHONPATH="."
uv run uvicorn app.main:app --reload --port 8000
```

### 5. Running Tests
Run pytest suite:
```bash
$env:PYTHONPATH="."
uv run pytest -v
```
