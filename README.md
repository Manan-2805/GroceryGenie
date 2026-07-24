# 🛒 GroceryGenie

> **Voice-First AI-Powered Grocery Shopping Assistant**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.138-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-6.0-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 Overview

GroceryGenie is a **premium, voice-first intelligent grocery shopping assistant** that revolutionizes how customers interact with online grocery stores. It enables:

- **🎤 Voice & Text AI Agent**: Natural language shopping assistant that can find products, manage carts, check orders, handle addresses, and more — with **≤1 LLM call per turn** for most actions
- **⚡ Zero-LLM Fast Path**: Button clicks, cart actions, order checks, and address management execute in **<10ms with 0 LLM calls**
- **🔍 Hybrid RRF Search**: Combines Qdrant vector embeddings + PostgreSQL BM25 keyword search fused via **Reciprocal Rank Fusion (k=60)** for accurate product discovery
- **🔄 Event-Driven Vector Sync**: Seller product create/update/deactivate automatically syncs to Qdrant in real-time — no manual re-indexing
- **🗺️ Store Layout Awareness**: Neo4j graph database maps products to aisles and sections
- **🏪 Seller Dashboard**: Complete inventory management — create, update, and deactivate products via text or voice
- **🔒 Safety-First**: Strict dietary/allergen guardrails with disclaimers, permission-gated actions

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────────┐   │
│  │ Text Chat│  │Voice Chat│  │  Pages   │  │ Zustand Store            │   │
│  │ (SSE)    │  │ (WebSock)│  │(Catalog, │  │ + React Query            │   │
│  │          │  │          │  │ Cart,etc)│  │                          │   │
│  └────┬─────┘  └────┬─────┘  └──────────┘  └──────────────────────────┘   │
└───────┼──────────────┼─────────────────────────────────────────────────────┘
        │              │
┌───────▼──────────────▼─────────────────────────────────────────────────────┐
│                    Backend (FastAPI + Granian)                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │              Agent Orchestrator (Optimized)                         │   │
│  │  ┌──────────────────────┐  ┌──────────────┐  ┌──────────────────┐  │   │
│  │  │ 0ms Fast Path        │  │ Single LLM   │  │ Python Tools     │  │   │
│  │  │ (13+ patterns,       │  │ Router       │  │ (cart, orders,   │  │   │
│  │  │  0 LLM calls)        │  │ (1 call)     │  │  addresses, etc) │  │   │
│  │  └──────────────────────┘  └──────────────┘  └──────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                 Voice Pipeline                                      │   │
│  │  Mic → VAD (RMS) → ASR (Parakeet) → Agent → TTS (Piper)            │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────────────┐   │
│  │PostgreSQL│  │  Redis   │  │  Qdrant  │  │  Neo4j (Graph)         │   │
│  │ (BM25)   │  │ (Session)│  │(Vectors+ │  │ (Store Layout)         │   │
│  │          │  │          │  │Auto-Sync)│  │                        │   │
│  └──────────┘  └──────────┘  └──────────┘  └────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| [Docker & Docker Compose](https://www.docker.com/) | Latest | Infrastructure services |
| [Python 3.12+](https://python.org) | >= 3.12 | Backend runtime |
| [uv](https://github.com/astral-sh/uv) | Latest | Python package manager |
| [Node.js](https://nodejs.org/) | >= 18 | Frontend development |
| [NVIDIA GPU](https://nvidia.com) | Optional | GPU acceleration for ASR/embeddings |

### 1. Clone & Configure

```bash
git clone https://github.com/Manan-2805/GroceryGenie.git
cd GroceryGenie
cp .env.example .env.dev
```

Fill in your `LLM_PROVIDERS` (or `NIM_API_KEY`) and any other required keys in `.env.dev`.

### 2. Start Infrastructure

```bash
# Start PostgreSQL, Redis, Qdrant, Neo4j
docker compose -f docker-compose.infra.yml up -d
```

### 3. Setup Backend

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

### 4. Setup Frontend

```bash
cd frontend
npm install
npm run dev
```

### 5. Download Voice Models

```bash
cd backend
uv run download_and_test.py
# Select option 1 for TTS → ASR pipeline test
```

Open [http://localhost:5173](http://localhost:5173) to browse the app.

---

## 🎯 Key Features

### 🤖 AI Assistant (Agent)
- **Natural Language Understanding**: Ask questions, give commands in plain English
- **Single-shot Intent Classification**: One LLM call extracts tool + parameters
- **Zero-LLM Fast Path**: 13+ common commands handled with 0 LLM calls via string matching
- **Structured Options**: Agent can present clickable choices + free-form input
- **Multi-turn Conversations**: Remembers context across turns
- **Permission Gates**: Sensitive actions require explicit user approval
- **Persistent Memory**: Learns user preferences and dietary restrictions via PostgreSQL
- **Multi-provider LLM**: Automatic fallback between providers on timeout/auth failure

### 🎤 Voice Interface
- **Real-time ASR**: Parakeet ONNX model with GPU acceleration
- **Natural TTS**: Piper voice with emotion presets (excited, calm, neutral)
- **Barge-in**: Interrupt the agent while it's speaking
- **VAD**: RMS-based voice activity detection
- **Heartbeat**: Connection health monitoring with auto-reconnection

### 📦 Shopping Features
- **Product Search**: Hybrid vector + keyword search with filters
- **Cart Management**: Add/remove/update items with stock validation
- **Order Placement**: Full checkout flow with address selection
- **Address Management**: CRUD for saved delivery addresses
- **Order Tracking**: Real-time order status updates (placed → packed → out_for_delivery → delivered)
- **Product Ratings**: Rate delivered products with star ratings and comments
- **Dietary Analysis**: Ingredient allergen checking with safety guardrails

### 🏪 Seller Features
- **Inventory Management**: Product CRUD with low-stock alerts
- **Order Fulfillment**: Queue management with status transitions
- **Dashboard Analytics**: Sales metrics, pending orders, low stock items
- **Sales Analysis**: Revenue trends, category breakdown, AOV metrics

---

## 💻 Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Frontend** | React 19, TypeScript 6, Vite 8 | Web client |
| **Styling** | Tailwind CSS v3 | Responsive UI |
| **State** | Zustand + TanStack Query | Client state & API caching |
| **Routing** | React Router v7 | Page navigation |
| **Backend** | FastAPI + Granian | REST API + WebSocket |
| **ORM** | SQLAlchemy 2.0 + Alembic | Database ORM & migrations |
| **Database** | PostgreSQL 16 | Primary data store |
| **Cache** | Redis 7 | Session storage & caching |
| **Vector DB** | Qdrant | Product embeddings search |
| **Graph DB** | Neo4j | Store layout mapping |
| **ASR** | Parakeet ONNX (nemo-parakeet-tdt) | Speech-to-text |
| **TTS** | Piper ONNX | Text-to-speech |
| **VAD** | RMS-based (custom) | Voice activity detection |
| **Embeddings** | BAAI/bge-small-en-v1.5 | Product vector embeddings |
| **LLM** | Multi-provider (NVIDIA NIM, Kimi, Ollama, etc.) | Agent reasoning |
| **MCP** | FastMCP | Model Context Protocol server |

---

## 🎮 GPU Acceleration

GroceryGenie **automatically detects and utilizes NVIDIA GPUs** for accelerated processing:

| Component | Without GPU | With GPU |
|-----------|-------------|----------|
| ASR (Speech-to-Text) | CPU (via ONNX CPU) | CUDA + DirectML |
| Embeddings | CPU | CUDA |
| TTS (Piper) | CPU (ONNX model) | CPU (ONNX model) |

GPU detection is automatic at startup. To disable GPU:
```bash
export USE_GPU=false
```
Or set in `.env.dev`:
```env
USE_GPU=false
ONNX_ASR_PROVIDERS=CPUExecutionProvider
```

---

## 📁 Project Structure

```
GroceryGenie/
├── backend/                     # FastAPI Backend Service
│   ├── app/
│   │   ├── api/                 # REST + WebSocket endpoints
│   │   │   ├── chat.py          # SSE text chat endpoint
│   │   │   ├── ws.py            # Voice WebSocket endpoint
│   │   │   ├── cart.py          # Cart CRUD
│   │   │   ├── orders.py        # Order management
│   │   │   ├── products.py      # Product CRUD + RAG QA
│   │   │   ├── addresses.py     # Address management
│   │   │   └── auth.py          # Google OAuth + JWT
│   │   ├── core/
│   │   │   ├── config.py        # Settings + GPU detection
│   │   │   ├── security.py      # JWT + auth utilities
│   │   │   └── dependencies.py  # FastAPI dependency injection
│   │   ├── db/
│   │   │   ├── models/          # SQLAlchemy models
│   │   │   └── migrations/      # Alembic migrations
│   │   └── services/
│   │       ├── agent/           # AI Agent system
│   │       │   ├── orchestrator.py  # Main agent loop
│   │       │   ├── llm.py           # Multi-provider LLM client
│   │       │   ├── memory.py        # Persistent fact classifier
│   │       │   └── tools/           # Tool registry (flat, no DAG)
│   │       │       ├── cart_tools.py
│   │       │       ├── order_tools.py
│   │       │       ├── product_tools.py
│   │       │       ├── address_tools.py
│   │       │       ├── seller_tools.py
│   │       │       └── profile_tools.py
│   │       ├── voice/           # Voice pipeline
│   │       │   ├── asr.py       # Speech-to-text
│   │       │   └── tts.py       # Text-to-speech
│   │       └── rag/             # RAG system
│   │           ├── embedder.py  # Text embeddings
│   │           ├── retriever.py # Hybrid search
│   │           └── graph.py     # Neo4j graph queries
│   ├── tests/                   # Test suite
│   └── download_and_test.py     # Model download + test
├── frontend/                    # React + TypeScript Client
│   └── src/
│       ├── pages/               # Route pages
│       │   ├── Agent.tsx        # Full AI Assistant page
│       │   ├── Catalog.tsx      # Product catalog
│       │   ├── Cart.tsx         # Shopping cart
│       │   └── ...
│       ├── contexts/
│       │   └── VoiceSessionContext.tsx  # Voice WebSocket provider
│       ├── services/
│       │   └── api.ts           # API client with all services
│       └── store/
│           └── uiStore.ts       # Zustand UI state
├── mcp_server/
│   └── server.py                # FastMCP server with 17 tools
└── models/                      # Local ML models (gitignored)
```

---

## 🧪 Testing

```bash
# Backend tests
cd backend
uv run pytest -v

# Voice pipeline specific tests
uv run pytest tests/test_voice_pipeline.py -v

# E2E tests (requires running services)
uv run pytest tests/test_e2e.py -v

# Frontend checks
cd frontend
npm run check

# Full CI checks
make check
```

---

## 🐳 Docker Deployment

```bash
# 1. Start infrastructure (PostgreSQL, Redis, Qdrant, Neo4j)
docker compose -f docker-compose.infra.yml up -d

# 2. Start app services (backend + frontend)
docker compose -f docker-compose.prod.yml up --build -d
```

---

## 🔧 Configuration

Key environment variables (see `.env.dev` for full list):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@db:5432/grocergenie` | PostgreSQL connection |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant vector DB |
| `NEO4J_URI` | `bolt://neo4j:7687` | Neo4j graph DB |
| `LLM_PROVIDERS` | (JSON array) | Multi-provider LLM config |
| `NIM_API_KEY` | - | NVIDIA NIM API key (legacy) |
| `GOOGLE_CLIENT_ID` | - | Google OAuth client ID |
| `JWT_SECRET_KEY` | - | JWT signing secret |
| `USE_GPU` | `true` | Enable GPU acceleration |
| `ONNX_ASR_PROVIDERS` | (auto-detect) | ONNX execution providers |

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit changes: `git commit -am 'Add my feature'`
4. Push: `git push origin feature/my-feature`
5. Open a Pull Request

### Code Style
- **Python**: Ruff formatting (88 char lines), type hints
- **TypeScript**: ESLint + Prettier, strict mode
- **Commits**: Follow conventional commits

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

---

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| Voice not working | Check `health` endpoint → `voice_ok` must be true |
| Model download fails | Check internet + disk space in `models/` directory |
| GPU not detected | Verify CUDA installation + `torch.cuda.is_available()` |
| WebSocket disconnects | Check firewall, enable HTTP/2, verify heartbeat |
| LLM returns errors | Verify `LLM_PROVIDERS` or `NIM_API_KEY` and model availability |