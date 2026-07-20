# GroceryGenie - Backend Service

> **FastAPI Backend for the Voice-First AI Grocery Shopping Assistant**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.138-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)

---

## 📋 Overview

The GroceryGenie backend is a **high-performance asynchronous Python service** built with FastAPI and Granian. It provides:

- **REST API**: Full CRUD for products, cart, orders, addresses, users
- **WebSocket Voice API**: Real-time audio streaming with VAD, ASR, and TTS
- **AI Agent System**: DAG-based task decomposition with LLM-powered workers
- **RAG Pipeline**: Hybrid search (Qdrant vectors + PostgreSQL keyword)
- **Store Graph**: Neo4j-powered store layout and aisle mapping
- **GPU Acceleration**: Automatic CUDA/DirectML detection for ONNX models

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Application                      │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    API Layer                          │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │   │
│  │  │ /auth  │ │/products│ │ /cart  │ │ /orders│  ...  │   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘       │   │
│  │  ┌────────┐ ┌──────────────────────────────────┐    │   │
│  │  │/chat   │ │ /ws/voice (WebSocket)            │    │   │
│  │  └────────┘ └──────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Agent Orchestrator                       │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │ LLM Call │  │ DAG Exec │  │ 11 Workers       │   │   │
│  │  │ (NIM)    │  │ (asyncio)│  │ (Product, Cart,  │   │   │
│  │  │ + Retry  │  │ + Timeout│  │  Order, Address, │   │   │
│  │  └──────────┘  └──────────┘  │  Profile, etc.)  │   │   │
│  │                               └──────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Voice Pipeline                           │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │ VAD      │  │ ASR      │  │ TTS              │   │   │
│  │  │(Silero)  │  │(Parakeet)│  │(Piper + Emotion) │   │   │
│  │  └──────────┘  └──────────┘  └──────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │PostgreSQL│  │  Redis   │  │  Qdrant  │  │  Neo4j   │   │
│  │ (SQL)    │  │ (Session)│  │(Vectors) │  │ (Graph)  │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Setup

### Prerequisites

- Python >= 3.12
- [uv](https://github.com/astral-sh/uv) (fast Python package manager)
- PostgreSQL 16, Redis 7, Qdrant, Neo4j (via Docker or local)

### Installation

```bash
cd backend
uv sync
```

### Configuration

Create `.env.dev` in the project root:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/grocergenie
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6333
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=grocergeniepass
NIM_API_KEY=your_nim_api_key
NIM_BASE_URL=https://integrate.api.nvidia.com/v1
NIM_MODEL=meta/llama-3.1-70b-instruct
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
JWT_SECRET_KEY=your_jwt_secret
USE_GPU=true
```

### Database Migrations

```bash
uv run alembic upgrade head
```

### Run Development Server

```bash
uv run uvicorn app.main:app --reload --port 8000
```

### Run Tests

```bash
uv run pytest -v
```

---

## 📁 Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app, lifespan, health checks
│   ├── prestart.py                # Pre-startup hooks
│   ├── api/
│   │   ├── addresses.py           # Address CRUD endpoints
│   │   ├── auth.py                # Google OAuth + JWT auth
│   │   ├── cart.py                # Shopping cart CRUD
│   │   ├── chat.py                # SSE text chat endpoint
│   │   ├── orders.py              # Order management + fulfillment
│   │   ├── products.py            # Product CRUD + RAG QA
│   │   ├── ratings.py             # Product ratings
│   │   ├── users.py               # User profile + role management
│   │   └── ws.py                  # Voice WebSocket endpoint
│   ├── core/
│   │   ├── config.py              # Settings + GPU auto-detection
│   │   ├── dependencies.py        # FastAPI dependency injection
│   │   ├── limiter.py             # Rate limiting
│   │   └── security.py            # JWT encode/decode
│   ├── db/
│   │   ├── base.py                # SQLAlchemy engine + session
│   │   ├── reset.py               # DB reset utility
│   │   ├── seed.py                # Seed data
│   │   ├── models/
│   │   │   ├── address.py         # Address model
│   │   │   ├── cart.py            # CartItem model
│   │   │   ├── enums.py           # UserRole, OrderStatus, etc.
│   │   │   ├── memory.py          # PersistentFact model
│   │   │   ├── order.py           # Order + OrderItem models
│   │   │   ├── product.py         # Product model
│   │   │   ├── rating.py          # ProductRating model
│   │   │   ├── session.py         # ChatSession model
│   │   │   └── user.py            # User model
│   │   └── migrations/            # Alembic migration files
│   ├── middleware/
│   │   └── error_handler.py       # Global error handling
│   └── services/
│       ├── cache.py               # Redis caching for products
│       ├── memory.py              # Redis session + Mem0 stub
│       ├── search.py              # Hybrid search wrapper
│       ├── agent/
│       │   ├── orchestrator.py    # Main agent loop + DAG execution
│       │   ├── llm.py             # LLM client (NIM) with retry
│       │   ├── memory.py          # Persistent fact classifier
│       │   ├── dag.py             # DAG execution engine
│       │   └── workers/
│       │       ├── base.py        # Base worker class
│       │       ├── product.py     # Product search worker
│       │       ├── cart.py        # Cart action worker
│       │       ├── order.py       # Order status worker
│       │       ├── dietary.py     # Dietary analysis worker
│       │       ├── explainer.py   # Data summarization worker
│       │       ├── layout.py      # Store layout worker
│       │       ├── seller.py      # Seller dashboard worker
│       │       ├── address.py     # Address management worker
│       │       ├── checkout.py    # Checkout/order placement worker
│       │       ├── profile.py     # User profile worker
│       │       └── seller_product.py  # Seller product management
│       ├── voice/
│       │   ├── asr.py             # Parakeet ASR (speech-to-text)
│       │   └── tts.py             # Piper TTS (text-to-speech)
│       └── rag/
│           ├── embedder.py        # SentenceTransformer embeddings
│           ├── retriever.py       # Qdrant hybrid search
│           └── graph.py           # Neo4j store layout queries
├── tests/
│   ├── test_orchestrator.py       # DAG + memory tests
│   ├── test_voice_pipeline.py     # ASR + TTS unit tests
│   └── test_e2e.py                # End-to-end browser tests
├── alembic.ini                    # Alembic configuration
├── download_and_test.py           # Model download + pipeline test
└── pyproject.toml                 # Python dependencies + tooling
```

---

## 🔌 API Endpoints

### Authentication
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/auth/me` | Get current user |
| POST | `/api/v1/auth/login` | Email/password login |
| POST | `/api/v1/auth/register` | User registration |
| POST | `/api/v1/auth/logout` | Logout |
| POST | `/api/v1/auth/dev-bypass` | Dev auth bypass |

### Products
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/products` | List products (with filters) |
| GET | `/api/v1/products/{id}` | Get product details |
| POST | `/api/v1/products` | Create product (seller) |
| PUT | `/api/v1/products/{id}` | Update product (seller) |
| DELETE | `/api/v1/products/{id}` | Deactivate product (seller) |
| GET | `/api/v1/products/seller` | List seller's products |
| POST | `/api/v1/products/{id}/qa` | Product RAG Q&A (SSE) |
| POST | `/api/v1/products/upload` | Upload product image |

### Cart
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/cart` | Get cart contents |
| POST | `/api/v1/cart` | Add item to cart |
| PUT | `/api/v1/cart/{product_id}` | Update cart quantity |
| DELETE | `/api/v1/cart/{product_id}` | Remove from cart |

### Orders
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/orders` | List user orders |
| POST | `/api/v1/orders` | Place order |
| GET | `/api/v1/orders/{id}` | Get order details |
| PUT | `/api/v1/orders/{id}/status` | Update order status (seller) |
| GET | `/api/v1/orders/seller/queue` | Seller fulfillment queue |

### Addresses
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/addresses` | List saved addresses |
| POST | `/api/v1/addresses` | Create address |
| PUT | `/api/v1/addresses/{id}` | Update address |
| DELETE | `/api/v1/addresses/{id}` | Delete address |

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/chat/text` | SSE text chat with agent |

### WebSocket
| Path | Description |
|------|-------------|
| `/api/v1/ws/voice` | Voice chat WebSocket |

### Health
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Simple health check |
| GET | `/api/health` | Detailed health (DB, Redis, Qdrant, Neo4j, LLM, Voice) |

---

## 🎤 Voice Pipeline

The voice pipeline processes audio in real-time:

1. **Audio Capture**: Browser captures 16kHz PCM mono audio via Web Audio API
2. **WebSocket Stream**: Audio chunks sent to `/api/v1/ws/voice`
3. **VAD (Silero)**: Detects speech onset/offset with barge-in support
4. **ASR (Parakeet)**: Transcribes speech to text using ONNX model
5. **Agent Orchestrator**: Processes text through DAG-based AI agent
6. **TTS (Piper)**: Synthesizes response with emotion presets
7. **Audio Playback**: Streams PCM chunks back to browser

### Key Parameters
- Sample Rate: 16kHz
- Frame Size: 512 samples (1024 bytes)
- Max Speech Duration: 15 seconds
- Silence Threshold: 1.2 seconds
- Heartbeat Interval: 30 seconds

---

## 🤖 Agent System

The AI agent uses a **DAG-based task decomposition** architecture:

1. **Decomposition**: LLM breaks user request into sub-goals with dependencies
2. **DAG Execution**: Workers execute in parallel respecting dependency order
3. **Synthesis**: Results are combined into a natural language response
4. **Permission Gates**: Sensitive actions require user confirmation
5. **Memory**: Persistent facts stored in PostgreSQL, conversation in Redis

### Workers
| Worker | Purpose | Dependencies |
|--------|---------|-------------|
| ProductQueryWorker | Search/filter products | None |
| CartActionWorker | Add/remove/update cart | ProductQueryWorker |
| OrderStatusWorker | Check order status | None |
| DietaryFactWorker | Analyze ingredients | ProductQueryWorker |
| ExplainerWorker | Summarize data | Any |
| StoreLayoutWorker | Find aisle/section | ProductQueryWorker |
| SellerDashboardWorker | Seller stats | None |
| AddressWorker | Manage addresses | None |
| CheckoutWorker | Place orders | CartActionWorker |
| ProfileWorker | User profile | None |
| SellerProductWorker | Manage products | None |

---

## 🎮 GPU Support

GPU detection is automatic at startup:

```python
# In config.py - auto-detected providers
providers = detect_gpu_providers()
# Returns: ['CUDAExecutionProvider', 'DmlExecutionProvider', 'CPUExecutionProvider']
# Or: ['CPUExecutionProvider'] if no GPU
```

| Component | GPU Support | Library |
|-----------|-------------|---------|
| ASR (Parakeet) | CUDA + DirectML | onnxruntime |
| Embeddings | CUDA | sentence-transformers + torch |
| TTS (Piper) | CPU only | piper-tts (ONNX) |

---

## 🧪 Testing

```bash
# Run all tests
uv run pytest -v

# Voice pipeline tests
uv run pytest tests/test_voice_pipeline.py -v

# Orchestrator tests
uv run pytest tests/test_orchestrator.py -v

# E2E tests (requires services)
uv run pytest tests/test_e2e.py -v
```

---

## 🐳 Docker

```dockerfile
# Build production image
docker build -f Dockerfile.prod -t grocergenie-backend .
```

---

## 🔧 Troubleshooting

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError` | Run `uv sync` to install dependencies |
| Database connection failed | Ensure PostgreSQL is running and `DATABASE_URL` is correct |
| Voice model not found | Run `uv run download_and_test.py` |
| GPU not detected | Check `torch.cuda.is_available()` in Python |
| WebSocket disconnects | Check network, enable HTTP/2, verify heartbeat |
| LLM returns errors | Verify `NIM_API_KEY` and model availability |