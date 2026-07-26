"""应用配置：环境变量 / .env 加载（前缀 CALLIODESMO_）。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CALLIODESMO_", env_file=".env", extra="ignore")

    environment: str = "development"
    debug: bool = True

    database_url: str = "postgresql+asyncpg://calliodesmo:calliodesmo@localhost:5432/calliodesmo"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "calliodesmo"

    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    llm_model: str = "openai/gpt-4o-mini"
    llm_api_key: str | None = None
    llm_api_base: str | None = None

    embedding_provider: str = "bge-m3"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024

    admin_username: str = "admin"
    admin_password: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
