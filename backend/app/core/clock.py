from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc


def now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """统一为带时区时间。

    PostgreSQL 的 timestamptz 读回来带时区，SQLite 读回来是朴素时间；
    凡涉及库内时间与当前时间比较，都必须先过这一层，否则会出现
    「can't compare offset-naive and offset-aware datetimes」。
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def is_past(value: datetime | None) -> bool:
    normalized = as_utc(value)
    return normalized is not None and normalized <= now()
