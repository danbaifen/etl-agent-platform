from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

PASSWORD = "Passw0rd!2026"

ACCOUNTS = {
    "admin": "admin@example.com",
    "maker": "maker@example.com",
    "checker_data": "checker.data@example.com",
    "checker_security": "checker.security@example.com",
    "operator": "operator@example.com",
    "auditor": "auditor@example.com",
}

DISPLAY_NAMES = {
    "admin": "项目管理员",
    "maker": "张岚",
    "checker_data": "李维",
    "checker_security": "王策",
    "operator": "陈默",
    "auditor": "周昕",
}


async def login(client: AsyncClient, account: str, password: str = PASSWORD) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"provider": "LOCAL", "external_subject": ACCOUNTS[account], "credential": password},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == "OK", body
    return body["data"]


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utc_in(**kwargs) -> datetime:
    return utcnow() + timedelta(**kwargs)
