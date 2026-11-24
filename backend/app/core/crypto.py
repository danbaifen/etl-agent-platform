from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

UTC = timezone.utc


def _default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value.isoformat()
    raise TypeError(f"不可序列化类型：{type(value)!r}")


def canonical_json(payload: Any) -> str:
    """Canonical JSON：键排序、无多余空格、UTF-8 直出、时间统一 UTC ISO8601。

    摘要必须在服务端与校验端得到同一串，因此禁止依赖 dict 插入顺序与本地时区。
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def sha256_hex(payload: Any) -> str:
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = canonical_json(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def generate_keypair() -> tuple[str, str]:
    """返回 (private_pem, public_pem)。私钥只在进程内用于签发。"""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def sign(private_pem: str, message: str) -> str:
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    assert isinstance(key, Ed25519PrivateKey)
    return key.sign(message.encode("utf-8")).hex()


def verify(public_pem: str, message: str, signature_hex: str) -> bool:
    try:
        key = serialization.load_pem_public_key(public_pem.encode())
        assert isinstance(key, Ed25519PublicKey)
        key.verify(bytes.fromhex(signature_hex), message.encode("utf-8"))
        return True
    except Exception:
        return False
