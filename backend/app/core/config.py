import os
from pathlib import Path

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

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # LLM Orchestrator (NIM / OpenAI compatible API)
    NIM_API_KEY: str = Field(default="placeholder_nim_api_key")
    NIM_BASE_URL: str = Field(default="https://integrate.api.nvidia.com/v1")
    NIM_MODEL: str = Field(default="meta/llama-3.1-70b-instruct")

    # Google OAuth credentials
    GOOGLE_CLIENT_ID: str = Field(default="placeholder_client_id")
    GOOGLE_CLIENT_SECRET: str = Field(default="placeholder_client_secret")
    FRONTEND_URL: str = Field(default="http://localhost:5173")
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
    ONNX_ASR_PROVIDERS: str = Field(default="CPUExecutionProvider")
    PARAKEET_CHUNK_SECONDS: int = Field(default=5)

    # Embedding model config
    EMBEDDING_MODEL_PATH: str = Field(default="BAAI/bge-small-en-v1.5")

    # Langfuse Configuration
    LANGFUSE_PUBLIC_KEY: str = Field(default="placeholder_langfuse_public_key")
    LANGFUSE_SECRET_KEY: str = Field(default="placeholder_langfuse_secret_key")
    LANGFUSE_HOST: str = Field(default="http://langfuse:3000")

    # Server config
    GRANIAN_WORKERS: int = Field(default=1)
    LOG_LEVEL: str = Field(default="INFO")
    RATE_LIMIT_PER_MINUTE: int = Field(default=60)
    ENV_MODE: str = Field(default="development")

    @property
    def parsed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def parsed_asr_providers(self) -> list[str]:
        return [
            prov.strip() for prov in self.ONNX_ASR_PROVIDERS.split(",") if prov.strip()
        ]


settings = Settings()
