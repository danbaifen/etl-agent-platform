from __future__ import annotations

import hashlib
import json
import time
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import AppError


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set_if_absent(self, key: str, value: str, ttl: int) -> None: ...


class MemoryIdempotencyStore:
    """进程内存储，仅用于单机开发与自动化测试。

    多实例部署必须使用 Redis 版本，否则幂等语义在实例间失效。
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}

    async def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expire_at = item
        if expire_at < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def set_if_absent(self, key: str, value: str, ttl: int) -> None:
        if await self.get(key) is None:
            self._data[key] = (value, time.monotonic() + ttl)


class RedisIdempotencyStore:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._client = redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set_if_absent(self, key: str, value: str, ttl: int) -> None:
        await self._client.set(key, value, ex=ttl, nx=True)


_store: IdempotencyStore | None = None


def get_store() -> IdempotencyStore:
    global _store
    if _store is None:
        settings = get_settings()
        if settings.idempotency_backend == "memory":
            _store = MemoryIdempotencyStore()
        else:
            _store = RedisIdempotencyStore(settings.redis_url)
    return _store


def reset_store() -> None:
    global _store
    _store = None


def _fingerprint(body: dict) -> str:
    payload = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def ensure_idempotency(key: str | None, scope: str, body: dict) -> None:
    """同键同体放行，同键不同体冲突。

    语义：24 小时内同一幂等键只允许对应一种请求体。重复提交由业务唯一约束兜底。
    """
    if not key:
        raise AppError("SYS_IDEMPOTENCY_KEY_REQUIRED", "缺少 Idempotency-Key 请求头", 400)

    storage_key = f"idem:{scope}:{key}"
    fp = _fingerprint(body)
    store = get_store()

    stored = await store.get(storage_key)
    if stored is None:
        await store.set_if_absent(storage_key, fp, 24 * 3600)
        return
    if stored != fp:
        raise AppError("SYS_IDEMPOTENCY_CONFLICT", "相同幂等键对应不同请求体", 409)
