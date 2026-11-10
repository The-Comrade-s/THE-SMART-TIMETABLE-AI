"""Centralised configuration. All values come from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str
    institution_name: str
    app_env: str
    database_url: str
    db_pool_size: int
    db_max_overflow: int
    db_connect_timeout: int
    default_theme: str

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    theme = os.getenv("DEFAULT_THEME", "dark").strip().lower()
    return Settings(
        app_name=os.getenv("APP_NAME", "Smart Timetable System"),
        institution_name=os.getenv("INSTITUTION_NAME", "Your Institution Name"),
        app_env=os.getenv("APP_ENV", "development"),
        database_url=os.getenv("DATABASE_URL", ""),
        db_pool_size=_int("DB_POOL_SIZE", 5),
        db_max_overflow=_int("DB_MAX_OVERFLOW", 10),
        db_connect_timeout=_int("DB_CONNECT_TIMEOUT", 5),
        default_theme=theme if theme in ("dark", "light") else "dark",
    )
