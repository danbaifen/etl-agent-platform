from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://etlagent:etlagent_dev@localhost:5432/etlagent"
    redis_url: str = "redis://localhost:6379/0"

    # redis：多实例部署；memory：单机开发与自动化测试（不可用于生产）
    idempotency_backend: str = "redis"

    session_ttl_hours: int = 8
    session_cookie_name: str = "etl_session"
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"

    auth_provider_local_enabled: bool = True
    auth_provider_oidc_enabled: bool = False
    auth_max_failed_attempts: int = 5
    auth_lock_minutes: int = 15

    vault_addr: str = ""
    vault_token: str = ""

    log_level: str = "INFO"
    log_format: str = "json"

    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
