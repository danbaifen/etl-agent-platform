"""M01 基线约束：认证、租户/项目隔离、能力校验、幂等。

这些不是单独的验收条目，但它们是 AC-01「强制职责分离」与后续所有审批链路的前提：
身份上下文错了，后面的审批事实就不可信。
"""

from __future__ import annotations

import uuid

import pytest

from tests.helpers import ACCOUNTS, PASSWORD, idem, login

pytestmark = pytest.mark.acceptance


async def test_unauthenticated_is_rejected(client):
    resp = await client.get("/api/v1/auth/session")
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == "AUTH_UNAUTHENTICATED"
    assert body["trace_id"]


async def test_login_returns_hashed_session_only_once(client, seeded):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"provider": "LOCAL", "external_subject": ACCOUNTS["admin"], "credential": PASSWORD},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["session_token"]) >= 32
    assert data["user"]["display_name"] == "项目管理员"

    # 会话接口不再回传令牌明文
    session = await client.get("/api/v1/auth/session")
    assert "session_token" not in session.text


async def test_wrong_password_is_rejected(client, seeded):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"provider": "LOCAL", "external_subject": ACCOUNTS["admin"], "credential": "wrong-pass-123"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


async def test_unknown_subject_is_rejected(client, seeded):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"provider": "LOCAL", "external_subject": "ghost@example.com", "credential": PASSWORD},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


async def test_session_carries_tenant_and_project_scope(as_admin, seeded):
    resp = await as_admin.get("/api/v1/auth/session")
    data = resp.json()["data"]
    assert data["tenant"]["code"] == "acme"
    assert data["project"]["id"] == str(seeded["project_id"])
    assert data["roles"] == ["PROJECT_ADMIN"]
    assert "iam:role:assign" in data["capabilities"]


async def test_project_scope_isolation(make_client, as_admin, seeded):
    """非成员访问他人项目成员列表 → 403 IAM_NOT_MEMBER，不能靠改 URL 越权。"""
    created = await as_admin.post(
        "/api/v1/projects",
        json={"code": "other-proj", "name": "另一个项目"},
        headers=idem(),
    )
    assert created.status_code in (200, 201), created.text
    other_project = created.json()["data"]["id"]

    # Maker 只加入主项目，未加入 other-proj
    invited = await as_admin.post(
        f"/api/v1/projects/{seeded['project_id']}/members",
        json={"external_subject": ACCOUNTS["maker"], "role_codes": ["MAKER"]},
        headers=idem(),
    )
    assert invited.status_code == 201, invited.text

    maker = make_client()
    await login(maker, "maker")

    # 自己项目可读
    own = await maker.get(f"/api/v1/projects/{seeded['project_id']}/members")
    assert own.status_code == 200, own.text

    resp = await maker.get(f"/api/v1/projects/{other_project}/members")
    # 契约：会话项目与请求项目不一致 → 409 IAM_SCOPE_MISMATCH（SPEC 第 7 章）
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "IAM_SCOPE_MISMATCH"


async def test_capability_is_enforced_server_side(make_client, seeded):
    """Maker 没有成员管理能力，即使直接调接口也被拒。"""
    maker = make_client()
    await login(maker, "maker")
    resp = await maker.post(
        f"/api/v1/projects/{seeded['project_id']}/members",
        json={"external_subject": ACCOUNTS["operator"], "role_codes": ["OPERATOR"]},
        headers=idem(),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "AUTH_FORBIDDEN"


async def test_idempotency_key_required(as_admin, seeded):
    resp = await as_admin.post(
        "/api/v1/projects",
        json={"code": "no-key-proj", "name": "缺幂等键"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SYS_IDEMPOTENCY_KEY_REQUIRED"


async def test_same_key_different_body_conflicts(as_admin, seeded):
    key = str(uuid.uuid4())
    first = await as_admin.post(
        "/api/v1/projects",
        json={"code": "idem-proj", "name": "幂等项目"},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code in (200, 201), first.text

    second = await as_admin.post(
        "/api/v1/projects",
        json={"code": "idem-proj-2", "name": "不同的请求体"},
        headers={"Idempotency-Key": key},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "SYS_IDEMPOTENCY_CONFLICT"


async def test_role_revocation_removes_capability(make_client, as_admin, seeded):
    """撤销角色后重新登录，能力清单应同步收缩（能力来自角色推导，不缓存）。"""
    project_id = seeded["project_id"]
    created = await as_admin.post(
        f"/api/v1/projects/{project_id}/members",
        json={"external_subject": ACCOUNTS["operator"], "role_codes": ["OPERATOR"]},
        headers=idem(),
    )
    assert created.status_code == 201, created.text
    member = created.json()["data"]

    operator = make_client()
    await login(operator, "operator")
    before = (await operator.get("/api/v1/auth/session")).json()["data"]
    assert "exec:run:control" in before["capabilities"]

    assignments = await as_admin.get(f"/api/v1/projects/{project_id}/roles")
    assert assignments.status_code == 200

    from app.core.db import get_session_factory
    from app.modules.iam.models import IamMemberRole
    from sqlalchemy import select

    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(IamMemberRole).where(IamMemberRole.member_id == uuid.UUID(member["id"]))
            )
        ).scalars().all()
        assignment_id = rows[0].id

    revoked = await as_admin.delete(
        f"/api/v1/projects/{project_id}/members/{member['id']}/roles/{assignment_id}"
    )
    assert revoked.status_code == 200, revoked.text

    after_client = make_client()
    await login(after_client, "operator")
    after = (await after_client.get("/api/v1/auth/session")).json()["data"]
    assert "exec:run:control" not in after["capabilities"]
