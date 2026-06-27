from __future__ import annotations
import asyncpg
from asyncpg import Pool
from .config import settings

_db_pool: Pool | None = None


async def init_db_pool() -> None:
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=10)


async def close_db_pool() -> None:
    global _db_pool
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None


def get_db_pool() -> Pool:
    if _db_pool is None:
        raise RuntimeError("DB pool no inicializado")
    return _db_pool
