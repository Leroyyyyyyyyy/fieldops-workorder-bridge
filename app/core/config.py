from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables (or a local .env).

    Secrets never live in code. `database_url` is the single source of truth for
    the connection and must use the asyncpg driver, e.g.
    postgresql+asyncpg://user:pass@host:5432/dbname
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://fieldops:fieldops@localhost:5432/fieldops"
    # Log SQL emitted by SQLAlchemy. Off by default; noisy in production.
    db_echo: bool = False


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so settings are parsed once per process."""
    return Settings()
