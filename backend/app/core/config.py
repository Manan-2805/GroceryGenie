import json
import logging
import os
from pathlib import Path
from typing import Any

# Resolve MODELS_DIR: inside Docker, it's mounted at /app/models; otherwise, at backend/models on the host
if Path("/app/models").exists():
    MODELS_DIR = Path("/app/models")
else:
    MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"

if Path("/app/uploads").exists() or os.path.exists("/.dockerenv"):
    UPLOADS_DIR = Path("/app/uploads")
else:
    UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"

os.environ["HF_HOME"] = str(MODELS_DIR / "huggingface")

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("app.core.config")

# Model names that strictly require temperature=1.0
TEMPERATURE_RESTRICTED_MODELS = {"kimi-k2.6", "kimi-k2.5", "moonshot-v1"}


def detect_gpu_providers() -> list[str]:
    """Auto-detect available GPU providers for ONNX Runtime.

    Returns a list of ONNX execution providers in priority order.
    On Windows with NVIDIA GPU: ['CUDAExecutionProvider', 'DmlExecutionProvider', 'CPUExecutionProvider']
    On Linux with NVIDIA GPU: ['CUDAExecutionProvider', 'CPUExecutionProvider']
    On systems without GPU: ['CPUExecutionProvider']
    """
    providers = []

    # Check for CUDA via torch
    try:
        import torch

        if torch.cuda.is_available():
            providers.append("CUDAExecutionProvider")
            gpu_name = torch.cuda.get_device_name(0)
            logger.info(f"GPU detected via torch: {gpu_name}")
    except ImportError:
        logger.debug("torch not available, skipping CUDA check")
    except Exception as e:
        logger.debug(f"torch CUDA check failed: {e}")

    # Check for DirectML on Windows
    if os.name == "nt":
        import importlib.util

        if importlib.util.find_spec("onnxruntime") is not None:
            providers.append("DmlExecutionProvider")
            logger.info("DirectML provider available on Windows")
        else:
            logger.debug("onnxruntime-directml not available")

    # Fallback to CPU
    if not providers:
        logger.info("No GPU detected, using CPU execution provider")
        providers.append("CPUExecutionProvider")

    return providers


def detect_torch_device() -> str:
    """Detect the best available torch device."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        return "cpu"
    except ImportError:
        return "cpu"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent.parent.parent / ".env.dev"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@db:5432/grocergenie"
    )

    # Redis
    REDIS_URL: str = Field(default="redis://redis:6379/0")
    CHAT_SESSION_TTL_SECONDS: int = Field(default=3600)

    # Qdrant
    QDRANT_URL: str = Field(default="http://qdrant:6333")

    # Neo4j
    NEO4J_URI: str = Field(default="bolt://neo4j:7687")
    NEO4J_USER: str = Field(default="neo4j")
    NEO4J_PASSWORD: str = Field(default="grocergeniepass")

    # LLM Orchestrator (legacy single-provider fields - kept for backward compatibility)
    NIM_API_KEY: str = Field(default="placeholder_nim_api_key")
    NIM_BASE_URL: str = Field(default="https://integrate.api.nvidia.com/v1")
    NIM_MODEL: str = Field(default="meta/llama-3.1-70b-instruct")

    # Multi-provider LLM configuration (JSON list env var)
    LLM_PROVIDERS: str = Field(default="")

    # Google OAuth credentials
    GOOGLE_CLIENT_ID: str = Field(default="placeholder_client_id")
    GOOGLE_CLIENT_SECRET: str = Field(default="placeholder_client_secret")
    FRONTEND_URL: str = Field(default="http://localhost:5173")
    GOOGLE_REDIRECT_URI: str = Field(default="http://localhost:5173/api/v1/auth/google/callback")
    ALLOWED_ORIGINS: str = Field(default="http://localhost:5173,http://localhost:8000")

    # JWT Auth config
    JWT_SECRET_KEY: str = Field(default="dev_secret_key_extremely_secret_12345")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Voice Services config
    PIPER_VOICE_MODEL: str = Field(
        default=os.getenv(
            "PIPER_VOICE_MODEL", str(MODELS_DIR / "en_US-lessac-medium.onnx")
        )
    )
    PIPER_VOICE_CONFIG: str = Field(
        default=os.getenv(
            "PIPER_VOICE_CONFIG", str(MODELS_DIR / "en_US-lessac-medium.onnx.json")
        )
    )
    ONNX_ASR_PROVIDERS: str = Field(default="")  # Empty = auto-detect
    PARAKEET_CHUNK_SECONDS: int = Field(default=5)

    # Embedding model config
    EMBEDDING_MODEL_PATH: str = Field(default="BAAI/bge-small-en-v1.5")

    # Server config
    GRANIAN_WORKERS: int = Field(default=1)
    LOG_LEVEL: str = Field(default="INFO")
    RATE_LIMIT_PER_MINUTE: int = Field(default=60)
    ENV_MODE: str = Field(default="development")

    # GPU config
    USE_GPU: bool = Field(default=True)
    CUDA_DEVICE: int = Field(default=0)

    @field_validator("LLM_PROVIDERS", mode="before")
    @classmethod
    def parse_llm_providers(cls, v: str) -> str:
        """Validate LLM_PROVIDERS JSON string."""
        if v and v.strip():
            try:
                parsed = json.loads(v)
                if not isinstance(parsed, list) or len(parsed) == 0:
                    raise ValueError("LLM_PROVIDERS must be a non-empty JSON array")
                for i, provider in enumerate(parsed):
                    if not isinstance(provider, dict):
                        raise ValueError(f"Provider at index {i} must be an object")
                    for key in ("name", "api_key", "base_url", "model"):
                        if key not in provider:
                            raise ValueError(
                                f"Provider at index {i} missing required key '{key}'"
                            )
                    if "temperature" not in provider:
                        provider["temperature"] = 0.3
                    if "timeout" not in provider:
                        provider["timeout"] = 60.0
                    if "type" not in provider:
                        provider["type"] = "primary"
            except json.JSONDecodeError as e:
                raise ValueError(f"LLM_PROVIDERS is not valid JSON: {e}") from e
        return v

    @property
    def parsed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def parsed_llm_providers(self) -> list[dict[str, Any]]:
        """Parse LLM_PROVIDERS JSON string into a list of provider configs.
        Falls back to legacy NIM_* fields if LLM_PROVIDERS is empty.
        """
        if self.LLM_PROVIDERS and self.LLM_PROVIDERS.strip():
            parsed = json.loads(self.LLM_PROVIDERS)
            assert isinstance(parsed, list)  # nosec: type guard for mypy
            return parsed

        # Fallback to legacy single-provider config
        return [
            {
                "name": "legacy",
                "api_key": self.NIM_API_KEY,
                "base_url": self.NIM_BASE_URL,
                "model": self.NIM_MODEL,
                "temperature": 0.3,
                "timeout": 60.0,
                "type": "primary",
            }
        ]

    @property
    def parsed_asr_providers(self) -> list[str]:
        """Returns ONNX execution providers for ASR.

        If ONNX_ASR_PROVIDERS env var is set, parse it.
        Otherwise, auto-detect GPU providers.
        """
        if self.ONNX_ASR_PROVIDERS:
            return [
                prov.strip()
                for prov in self.ONNX_ASR_PROVIDERS.split(",")
                if prov.strip()
            ]
        return detect_gpu_providers()

    @property
    def torch_device(self) -> str:
        """Returns the best available torch device (cuda or cpu)."""
        if not self.USE_GPU:
            return "cpu"
        return detect_torch_device()


# ---------------------------------------------------------------------------
# Fuzzy matching thresholds — used by fast_path.py for option selection.
# Defined here so they can be tuned without touching fast_path logic.
# ---------------------------------------------------------------------------
FUZZY_COSINE_THRESHOLD: float = (
    0.7  # minimum cosine similarity to auto-select an option
)
FUZZY_SEQUENCE_THRESHOLD: float = (
    0.6  # minimum SequenceMatcher ratio to auto-select an option
)

settings = Settings()
