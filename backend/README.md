# GroceryGenie - Backend Service

> **FastAPI Backend for the Voice-First AI Grocery Shopping Assistant**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.138-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)

---

## 📋 Overview

The GroceryGenie backend is a **high-performance asynchronous Python service** built with FastAPI and Granian. It provides:

- **REST API**: Full CRUD for products, cart, orders, addresses, users
- **WebSocket Voice API**: Real-time audio streaming with VAD, ASR, and TTS
- **AI Agent System**: Single-shot intent classification with flat tool registry (no DAG)
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
│  │  ┌──────────┐  ┌─────────────────────────────────┐  │   │
│  │  │ LLM Call │  │ Tool Registry (pure Python)     │  │   │
│  │  │(Provider)│  │ - cart_tools.py                  │  │   │
│  │  │ + Retry  │  │ - order_tools.py                 │  │   │
│  │  │ + Fallbk │  │ - product_tools.py               │  │   │
│  │  └──────────┘  │ - address_tools.py               │  │   │
│  │                 │ - seller_tools.py                │  │   │
│  │                 │ - profile_tools.py               │  │   │
│  │                 └─────────────────────────────────┘  │   │
│  │  ┌──────────┐  ┌─────────────────────────────────┐  │   │
│  │  │ Fast Path│  │ 0ms LLM bypass for 13+ commands │  │   │
│  │  └──────────┘  └─────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Voice Pipeline                           │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │ VAD      │  │ ASR      │  │ TTS              │   │   │
│  │  │ (RMS)    │  │(Parakeet)│  │(Piper + Emotion) │   │   │
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
# Multi-provider LLM config (JSON array) or use legacy NIM_* fields:
LLM_PROVIDERS=[{"name":"nvidia","api_key":"nvapi-...","base_url":"https://integrate.api.nvidia.com/v1","model":"meta/llama-3.1-70b-instruct","type":"primary","temperature":0.3,"timeout":60.0}]
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
│   ├── main.py                    # FastAPI app, lifespan, health checks
│   ├── prestart.py                # Pre-startup hooks
│   ├── api/
│   │   ├── addresses.py           # Address CRUD endpoints
│   │   ├── auth.py                # Google OAuth + JWT auth
│   │   ├── cart.py                # Shopping cart CRUD
│   │   ├── chat.py                # SSE text chat endpoint
│   │   ├── orders.py              # Order management + fulfillment
│   │   ├── products.py            # Product CRUD + RAG QA + image upload
│   │   ├── ratings.py             # Product ratings
│   │   ├── routes.py              # Additional route definitions
│   │   ├── users.py               # User profile + role management
│   │   └── ws.py                  # Voice WebSocket endpoint
│   ├── core/
│   │   ├── config.py              # Settings + GPU auto-detection
│   │   ├── dependencies.py        # FastAPI dependency injection
│   │   ├── limiter.py             # Rate limiting
│   │   └── security.py            # JWT encode/decode
│   ├── db/
│   │   ├── base.py                # SQLAlchemy engine + session (with audit columns)
│   │   ├── reset.py               # DB reset utility
│   │   ├── seed.py                # Seed data (24 products + dev user)
│   │   ├── models/                # SQLAlchemy models
│   │   │   ├── address.py         # Address model
│   │   │   ├── cart.py            # CartItem model
│   │   │   ├── enums.py           # UserRole, OrderStatus, FactCategory, ChatMode
│   │   │   ├── error.py           # AppError model
│   │   │   ├── memory.py          # PersistentFact model
│   │   │   ├── order.py           # Order + OrderItem models
│   │   │   ├── product.py         # Product model
│   │   │   ├── rating.py          # ProductRating model
│   │   │   ├── session.py         # ChatSession model
│   │   │   └── user.py            # User model
│   │   └── migrations/            # Alembic migration files
│   ├── middleware/
│   │   └── error_handler.py       # Global error handling + DB logging
│   └── services/
│       ├── cache.py               # Redis caching for products
│       ├── memory.py              # Redis session + Mem0 bridge
│       ├── search.py              # Hybrid search wrapper
│       ├── agent/
│       │   ├── orchestrator.py    # Main agent loop (flat tool architecture)
│       │   ├── llm.py             # Multi-provider LLM client with retry + fallback
│       │   ├── memory.py          # Persistent fact classifier
│       │   ├── prompt_logger.py   # Dev mode prompt logging
│       │   └── tools/             # Flat tool registry (no workers/DAG)
│       │       ├── __init__.py    # Tool registry + RBAC permissions
│       │       ├── address_tools.py  # Address CRUD
│       │       ├── cart_tools.py     # Cart operations
│       │       ├── order_tools.py    # Order placement + viewing
│       │       ├── product_tools.py  # Product search
│       │       ├── profile_tools.py  # Role switch + facts
│       │       └── seller_tools.py   # Seller product management + Qdrant sync
│       ├── voice/
│       │   ├── asr.py             # Parakeet ASR (speech-to-text)
│       │   └── tts.py             # Piper TTS (text-to-speech) with emotion presets
│       └── rag/
│           ├── embedder.py        # SentenceTransformer embeddings (BGE-small)
│           ├── retriever.py       # Qdrant hybrid search + RRF fusion
│           └── graph.py           # Neo4j store layout queries
├── tests/
│   ├── test_orchestrator.py       # Memory classification tests
│   ├── test_voice_pipeline.py     # ASR + TTS unit tests
│   └── test_e2e.py                # End-to-end Playwright browser tests
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
| POST | `/api/v1/auth/login` | Email/password login (dev mode) |
| POST | `/api/v1/auth/logout` | Logout |
| POST | `/api/v1/auth/dev-bypass` | Dev auth bypass |

### Products
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/products` | List products (with filters, sorting, pagination) |
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
| GET | `/api/v1/orders` | List user orders (paginated) |
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

### Ratings
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/ratings` | Submit product rating |
| GET | `/api/v1/ratings/product/{id}` | Get product reviews |

### Users
| Method | Path | Description |
|--------|------|-------------|
| PATCH | `/api/v1/users/me/role` | Switch user role |
| GET | `/api/v1/users/facts` | List persistent facts |
| DELETE | `/api/v1/users/facts/{id}` | Delete a fact |

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
3. **VAD (RMS)**: Detects speech onset/offset with barge-in support
4. **ASR (Parakeet)**: Transcribes speech to text using ONNX model
5. **Agent Orchestrator**: Processes text through flat tool architecture
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

The AI agent uses a **single-shot intent classification** architecture with a flat tool registry:

1. **Fast Path Check**: 13+ command patterns matched via string matching (0 LLM calls)
2. **Intent Classification**: Single LLM call extracts tool name + parameters
3. **Tool Execution**: Pure Python functions execute the action (no LLM calls)
4. **Response Formatting**: LLM-generated natural language response from tool results
5. **Permission Gates**: Sensitive actions require user confirmation
6. **Memory**: Persistent facts stored in PostgreSQL, conversation in Redis
7. **RBAC**: Tool-level permission checks based on user role

### Tools
| Tool | Purpose |
|------|---------|
| `search_products` | Search/filter products with hybrid RRF search |
| `add_to_cart` | Add product to cart with stock validation |
| `remove_from_cart` | Remove product from cart |
| `update_cart_quantity` | Update cart item quantity |
| `view_cart` | View current cart contents |
| `place_order` | Place order using cart + default address |
| `view_orders` | View order history |
| `switch_role` | Switch between customer/seller roles |
| `manage_addresses` | CRUD for delivery addresses |
| `view_facts` | View persistent user facts |
| `seller_list_products` | List own products (seller) |
| `seller_create_product` | Create product (seller) |
| `seller_update_product` | Update product (seller) |
| `seller_delete_product` | Deactivate product (seller) |

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

# E2E tests (requires services + PLAYWRIGHT)
cd backend
$env:RUN_E2E="1"; uv run pytest tests/test_e2e.py -v
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
| LLM returns errors | Verify `LLM_PROVIDERS` (or `NIM_API_KEY`) and model availability |