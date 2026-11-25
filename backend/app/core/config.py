import json
from pathlib import Path
from secrets import token_urlsafe
from typing import Any

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    DATABASE_URL: str | None = Field(default=None, repr=False)
    DB_HOST: str | None = None
    DB_USER: str = "postgres"
    DB_NAME: str = "grocergenie"
    POSTGRES_PASSWORD: SecretStr | None = None
    FRONTEND_URL: str = "http://localhost:5173"
    ALLOWED_ORIGINS: str = "http://localhost:5173"
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:5173/api/v1/auth/google/callback"
    SESSION_SIGNING_KEY: str = Field(
        default_factory=lambda: token_urlsafe(32), repr=False
    )
    ENV_MODE: str = "development"
    LOG_LEVEL: str = "INFO"
    DB_POOL_SIZE: int = Field(default=10, ge=1, le=30)
    LLM_PROVIDERS: str = ""

    MODELS_DIR: Path = BASE_DIR / "models"
    UPLOADS_DIR: Path = BASE_DIR / "uploads"
    ASR_MODEL: str = "nemo-conformer-aed"
    ASR_SUBDIR: str = "canary"
    ASR_QUANTIZATION: str = "int8"
    PIPER_VOICE_MODEL: Path | None = None
    PIPER_VOICE_CONFIG: Path | None = None

    @model_validator(mode="after")
    def validate_runtime(self) -> "Settings":
        if self.ENV_MODE == "production" and (
            "SESSION_SIGNING_KEY" not in self.model_fields_set
            or len(self.SESSION_SIGNING_KEY) < 32
            or not self.FRONTEND_URL.startswith("https://")
            or not self.GOOGLE_REDIRECT_URI.startswith("https://")
            or any(not origin.startswith("https://") for origin in self.parsed_origins)
        ):
            raise ValueError(
                "Production requires HTTPS origins and a stable session signing key."
            )
        if self.LLM_PROVIDERS:
            providers = json.loads(self.LLM_PROVIDERS)
            if not isinstance(providers, list) or any(
                not isinstance(p, dict)
                or not isinstance(p.get("model"), str)
                or not str(p.get("base_url", "")).startswith("https://")
                for p in providers
            ):
                raise ValueError(
                    "LLM_PROVIDERS must be a list of HTTPS provider configurations."
                )
        return self

    @property
    def database_url(self) -> URL:
        if self.DATABASE_URL:
            return make_url(self.DATABASE_URL)
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.DB_USER,
            password=self.POSTGRES_PASSWORD.get_secret_value()
            if self.DB_HOST and self.POSTGRES_PASSWORD
            else None,
            host=self.DB_HOST or "127.0.0.1",
            port=5432,
            database=self.DB_NAME,
        )

    @property
    def secure_cookies(self) -> bool:
        return self.FRONTEND_URL.startswith("https://")

    @property
    def parsed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def parsed_llm_providers(self) -> list[dict[str, Any]]:
        return list(json.loads(self.LLM_PROVIDERS)) if self.LLM_PROVIDERS else []

    @property
    def piper_model(self) -> Path:
        return self.PIPER_VOICE_MODEL or self.MODELS_DIR / "en_US-lessac-medium.onnx"

    @property
    def piper_config(self) -> Path:
        return (
            self.PIPER_VOICE_CONFIG or self.MODELS_DIR / "en_US-lessac-medium.onnx.json"
        )

    @property
    def voice_assets_present(self) -> bool:
        return (
            (self.MODELS_DIR / self.ASR_SUBDIR).is_dir()
            and self.piper_model.is_file()
            and self.piper_config.is_file()
        )


settings = Settings()
UPLOADS_DIR = settings.UPLOADS_DIR
