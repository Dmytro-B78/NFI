#!/usr/bin/env python3
"""
Wrapper for `freqtrade trade` that raises the SQLAlchemy connection pool
size for Postgres before freqtrade creates its DB engine.

Why this exists:
    freqtrade.persistence.models.init_db() calls create_engine(db_url) with
    no pool_size/max_overflow kwargs, so every db_url gets SQLAlchemy's
    defaults: pool_size=5, max_overflow=10 (15 connections total).
    Under concurrent FreqUI dashboard/websocket load this pool can be fully
    checked out. freqtrade's own internal trading loop
    (freqtradebot.process()) has no exception handling around its own DB
    calls, so if it can't get a connection within pool_timeout the whole
    process crashes ("Fatal exception!").
    freqtrade has no config option for pool_size/max_overflow
    (see freqtrade/freqtrade#12028 on GitHub), so this wrapper patches the
    create_engine() call inside freqtrade.persistence.models to pass larger
    values for Postgres db_urls, read from scripts/db_pool_config.json
    (config over hardcode).
    SQLite db_urls are left untouched: a bigger pool would not help there,
    since sqlite still serializes all writes on its single-writer file lock.

Usage: identical to `freqtrade trade`, e.g.
    python scripts/run_freqtrade_pooled.py trade \
        --config user_data/config.json --strategy NostalgiaForInfinityX7
"""

import json
import sys
from pathlib import Path

POOL_CONFIG_PATH = Path(__file__).parent / "db_pool_config.json"


def _patch_pool_size() -> None:
    with open(POOL_CONFIG_PATH) as f:
        cfg = json.load(f)
    pool_size = cfg["pool_size"]
    max_overflow = cfg["max_overflow"]

    import freqtrade.persistence.models as models

    original_create_engine = models.create_engine

    def pooled_create_engine(db_url, *args, **kwargs):
        if str(db_url).startswith("postgresql"):
            kwargs.setdefault("pool_size", pool_size)
            kwargs.setdefault("max_overflow", max_overflow)
        return original_create_engine(db_url, *args, **kwargs)

    models.create_engine = pooled_create_engine


def main() -> None:
    _patch_pool_size()

    from freqtrade.main import main as freqtrade_main

    sys.exit(freqtrade_main(sys.argv[1:]))


if __name__ == "__main__":
    main()
