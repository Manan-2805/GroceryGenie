# GrocerGo

GrocerGo is a premium, voice-first intelligent grocery shopping assistant. It enables customers to find products, verify dietary requirements/ingredients with strict safety guardrails, check store layouts (Neo4j aisle mappings), and order groceries using a natural language interface (text SSE or WS voice mode). It also provides a dashboard and inventory controls for sellers.

## Tech Stack
*   **Backend**: FastAPI, Async SQLAlchemy, Alembic, PostgreSQL, Redis, Qdrant Vector DB, Neo4j Graph DB, Langfuse.
*   **AI Models**: nemo-parakeet-tdt-0.6b-v3 (ONNX ASR), Piper ONNX (Local TTS), BAAI/bge-small-en-v1.5 (Local Embeddings), NVIDIA NIM LLM.
*   **MCP Server**: FastMCP server with 14 tools mapping to the database, vector store, and graph.
*   **Frontend**: React (TS), Vite, Tailwind CSS v3, TanStack Query, Zustand, Axios, Web Audio API (PCM microphone streaming & queue playback).

---

## Directory Structure
```
GrocerGo/
├── backend/             # FastAPI Backend Service
│   ├── app/             # Application source (api, core, db, services)
│   ├── tests/           # Unit tests for Orchestrator, DAG, STT, TTS
│   └── download_and_test.py  # Script to download ASR/TTS models & run test CLI
├── frontend/            # React + TypeScript Frontend
├── mcp_server/          # FastMCP server python module
├── models/              # Local ASR/TTS model artifacts (ignored in git)
└── docker-compose.dev.yml   # Dev services (Postgres, Redis, Qdrant, Neo4j, etc)
```

---

## Getting Started

### 1. Prerequisites
Make sure you have:
*   [Docker & Docker Compose](https://www.docker.com/)
*   [uv](https://github.com/astral-sh/uv) (fast Python package manager)
*   [Node.js](https://nodejs.org/) (for React frontend compilation)

### 2. Setup Environment Variables
Configure the environment file. Create a copy of `.env.example` as `.env.dev`:
```bash
cp .env.example .env.dev
```
Fill in your `NIM_API_KEY` and any other required keys.

### 3. Spin up Database Services
Launch the PostgreSQL, Redis, Qdrant, and Neo4j Docker services:
```bash
make dev
```
*(This starts the backend and frontend containers as well, but you can run them locally or in Docker).*

### 4. Database Migrations
Initialize the Postgres database schema:
```bash
make migrate
```

### 5. Download Models & CLI Test
We use local models for speech-to-text (ASR) and text-to-speech (TTS). Run the script to automatically download the voice models from Hugging Face into the root `models` folder:
```bash
cd backend
uv run download_and_test.py
```
Select option `1` to run the TTS -> Noise -> STT pipeline accuracy test.

### 6. Running Local Development Server
To run the backend server locally (outside Docker) for debugging:
```bash
cd backend
$env:PYTHONPATH="."
uv run uvicorn app.main:app --reload --port 8000
```
To run the React frontend locally:
```bash
cd frontend
npm run dev
```

---

## Running Verification Tests
Execute the pytest suite:
```bash
cd backend
$env:PYTHONPATH="."
uv run pytest -v
```

To run all styling, formatting, security, and pytest checks:
```bash
make check
```
