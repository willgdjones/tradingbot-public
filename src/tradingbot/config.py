"""Central configuration, loaded from the gitignored ``.env`` file.

Every module reads settings from here rather than touching ``os.environ`` or
``.env`` directly. Secrets (API keys, DB URL) live only in ``.env`` (see
AGENTS.md) and must never be logged or committed.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the trading bot.

    Values come from environment variables / ``.env``. Only ``DATABASE_URL`` is
    required for the foundation (schema, ledger, risk). Venue keys are optional
    here so that research and backtest code can run without live credentials.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database -----------------------------------------------------------
    database_url: str = Field(
        default="postgresql://localhost:5433/tradingbot",
        alias="DATABASE_URL",
    )

    # --- Venue credentials (optional; trading-only keys, never withdrawals) --
    polymarket_us_key_id: str | None = Field(default=None, alias="POLYMARKET_US_KEY_ID")
    polymarket_us_secret: str | None = Field(default=None, alias="POLYMARKET_US_SECRET")
    alpaca_paper_key: str | None = Field(default=None, alias="ALPACA_PAPER_KEY")
    alpaca_paper_secret: str | None = Field(default=None, alias="ALPACA_PAPER_SECRET")
    alpaca_live_key: str | None = Field(default=None, alias="ALPACA_LIVE_KEY")
    alpaca_live_secret: str | None = Field(default=None, alias="ALPACA_LIVE_SECRET")
    x_consumer_key: str | None = Field(default=None, alias="X_CONSUMER_KEY")
    x_consumer_secret: str | None = Field(default=None, alias="X_CONSUMER_SECRET")
    x_bearer_token: str | None = Field(default=None, alias="X_BEARER_TOKEN")
    kalshi_api_key_id: str | None = Field(default=None, alias="KALSHI_API_KEY_ID")
    kalshi_private_key_path: str | None = Field(default=None, alias="KALSHI_PRIVATE_KEY_PATH")
    typesafe_api_key: SecretStr | None = Field(
        default=None, alias="TYPESAFE_API_KEY", repr=False
    )

    @property
    def sqlalchemy_database_url(self) -> str:
        """DB URL forced onto the psycopg (v3) driver for SQLAlchemy.

        ``.env`` stores a plain ``postgresql://`` URL (also usable by ``psql``
        and ``pg_dump``). SQLAlchemy would otherwise default to psycopg2, which
        is not installed, so we pin the psycopg3 dialect here.
        """
        url = self.database_url
        if url.startswith("postgresql+"):
            return url
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://") :]
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
