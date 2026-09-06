"""
Central runtime configuration. Every ``os.getenv`` in the codebase used to be
scattered across modules (and each one called ``load_dotenv()`` itself). Now
``.env`` is loaded once here and the rest of the app reads a single ``settings``
object.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    # --- environment -------------------------------------------------------
    environment: str = os.getenv("ENVIRONMENT", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    logfire_token: str | None = os.getenv("LOGFIRE_TOKEN") or None

    # --- CORS ------------------------------------------------------------
    frontend_origins: list[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv("FRONTEND_ORIGIN", "http://localhost:5173,http://localhost:5174")
        )
    )

    # --- Snowflake -----------------------------------------------------
    snowflake_account: str | None = os.getenv("SNOWFLAKE_ACCOUNT")
    snowflake_user: str | None = os.getenv("SNOWFLAKE_USER")
    snowflake_database: str = os.getenv("SNOWFLAKE_DATABASE", "RELIEFTRACE_DB")
    snowflake_schema: str = os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC")
    snowflake_warehouse: str = os.getenv("SNOWFLAKE_WAREHOUSE", "GENEROSITY_WH")
    snowflake_role: str | None = os.getenv("SNOWFLAKE_ROLE") or None
    snowflake_private_key_path: str | None = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
    snowflake_private_key: str | None = os.getenv("SNOWFLAKE_PRIVATE_KEY")
    snowflake_private_key_passphrase: str | None = os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
    snowflake_password: str | None = os.getenv("SNOWFLAKE_PASSWORD")
    # Size of the Snowflake connection pool. >1 lets the dashboard's queries
    # run concurrently instead of single-file behind one shared connection.
    snowflake_pool_size: int = int(os.getenv("SNOWFLAKE_POOL_SIZE", "3"))

    # --- cache / realtime backplane ----------------------------------
    redis_url: str = os.getenv("REDIS_URL", "").strip()
    events_channel: str = os.getenv("EVENTS_CHANNEL", "relieftrace:events")

    # --- API auth -------------------------------------------------------
    # When set, the write path and the AI briefing require this value in the
    # `X-API-Key` request header. Unset = auth disabled (local dev).
    api_key: str | None = os.getenv("API_KEY") or None

    # --- Gemini --------------------------------------------------------
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    # --- Solana -----------------------------------------------------
    solana_cluster: str = os.getenv("SOLANA_CLUSTER", "devnet")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


settings = Settings()
