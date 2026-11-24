from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Any = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_engine_url: str | None = None


def _build_engine(url: str):
    kwargs: dict[str, Any] = {"future": True}
    if url.startswith("sqlite"):
        # 测试与本地单机运行：不启用连接池预检
        kwargs["pool_pre_ping"] = False
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20
    return create_async_engine(url, **kwargs)


def configure_database(url: str) -> None:
    """切换数据库连接。进程内只允许在启动阶段或测试夹具中调用。"""
    global _engine, _session_factory, _engine_url
    _engine = _build_engine(url)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    _engine_url = url


def get_engine():
    if _engine is None:
        configure_database(get_settings().database_url)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        configure_database(get_settings().database_url)
    assert _session_factory is not None
    return _session_factory


async def dispose_database() -> None:
    global _engine, _session_factory, _engine_url
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
    _engine_url = None


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
