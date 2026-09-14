from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from .config import Settings, load_settings
from .contracts import MarketDataProvider
from .providers.dhan import DhanMarketDataProvider
from .storage.sqlite_repository import SQLiteMarketRepository


@lru_cache(maxsize=1)
def settings(root: Path) -> Settings:
    return load_settings(root)


@lru_cache(maxsize=1)
def repository(root: Path) -> SQLiteMarketRepository:
    configured = settings(root).database_url
    prefix = "sqlite:///"
    if not configured.startswith(prefix):
        raise ValueError("V1 supports sqlite:/// URLs; add a repository adapter for another backend")
    return SQLiteMarketRepository(root / configured.removeprefix(prefix))


@lru_cache(maxsize=1)
def provider(root: Path) -> MarketDataProvider:
    load_dotenv(root / ".env")
    cfg = settings(root)
    if cfg.provider != "dhan":
        raise ValueError(f"Unsupported provider: {cfg.provider}")
    client_id = os.getenv("DHAN_CLIENT_ID")
    token = os.getenv("DHAN_API_TOKEN")
    if not client_id or not token:
        raise RuntimeError("Copy .env.example to .env and set DHAN_CLIENT_ID and DHAN_API_TOKEN")
    return DhanMarketDataProvider(client_id, token, cfg.max_retries, cfg.request_delay_seconds)
