import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    telegram_bot_token: str = Field(default="123456789:replace_with_your_bot_token")
    telegram_chat_id: int = Field(default=123456789)

    check_interval_min_seconds: int = Field(default=120)
    check_interval_max_seconds: int = Field(default=300)

    deal_score_threshold: int = Field(default=75)
    risk_score_max: int = Field(default=45)
    default_min_profit: int = Field(default=1000)

    # PostgreSQL
    postgres_user: str = Field(default="resell")
    postgres_password: str = Field(default="resell_pass")
    postgres_db: str = Field(default="resell_radar")
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)

    # Auto-detect: use SQLite if PG is unreachable (dev mode)
    _pg_available: bool | None = None

    @property
    def database_url(self) -> str:
        if self._check_pg():
            return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        return "sqlite+aiosqlite:///resell_radar.db"

    @property
    def database_url_sync(self) -> str:
        if self._check_pg():
            return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        return "sqlite:///resell_radar.db"

    def _check_pg(self) -> bool:
        if self._pg_available is not None:
            return self._pg_available
        try:
            import socket
            s = socket.create_connection((self.postgres_host, self.postgres_port), timeout=1)
            s.close()
            self._pg_available = True
        except Exception:
            self._pg_available = False
        return self._pg_available

    # Redis
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    # MinIO
    minio_root_user: str = Field(default="minioadmin")
    minio_root_password: str = Field(default="minioadmin")
    minio_bucket: str = Field(default="resell-radar")
    minio_endpoint: str = Field(default="localhost:9000")

    # DeepSeek (primary AI)
    deepseek_api_key: str | None = Field(default=None)

    # Gemini (fallback AI)
    gemini_api_key: str | None = Field(default=None)

    # Ollama settings (optional local AI)
    ollama_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="qwen2.5:14b")
    ollama_vision_model: str = Field(default="llava:7b")

    # OLX
    olx_bearer_token: str | None = Field(default=None)

    # Celery
    celery_broker_url: str | None = Field(default=None)
    disable_internal_scheduler: bool = Field(default=False)

    @property
    def effective_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
