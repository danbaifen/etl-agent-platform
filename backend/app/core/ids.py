from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7：48 位毫秒时间戳 + 版本位 + 随机位。"""
    unix_ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")

    msb = (unix_ms & 0xFFFFFFFFFFFF) << 16
    msb |= 0x7000
    msb |= (rand >> 68) & 0x0FFF

    lsb = 0x8000000000000000
    lsb |= rand & 0x3FFFFFFFFFFFFFFF

    return uuid.UUID(int=(msb << 64) | lsb)
