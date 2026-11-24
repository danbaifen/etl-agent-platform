"""AC-01：独立配置三角色，系统强制拦截申请人自批与职责混用。

对应项目要求 2.8.10 第 1 条与 2.8.2 强制职责分离规则。
"""

from __future__ import annotations

import pytest

from tests.helpers import ACCOUNTS, idem

pytestmark = pytest.mark.acceptance


async def _invite(client, project_id, account: str, role_codes: list[str]):
    return await client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"external_subject": ACCOUNTS[account], "role_codes": role_codes},
        headers=idem(),
    )


async def test_configure_three_independent_roles(as_admin, seeded):
    """三个独立人员分别持有 Maker / 数据审批 / 安全审批，配置成功。"""
    project_id = seeded["project_id"]

    r1 = await _invite(as_admin, project_id, "maker", ["MAKER"])
    r2 = await _invite(as_admin, project_id, "checker_data", ["CHECKER_DATA"])
    r3 = await _invite(as_admin, project_id, "checker_security", ["CHECKER_SECURITY"])

    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    assert r3.status_code == 201, r3.text

    assert [r["code"] for r in r1.json()["data"]["roles"]] == ["MAKER"]
    assert [r["code"] for r in r2.json()["data"]["roles"]] == ["CHECKER_DATA"]
    assert [r["code"] for r in r3.json()["data"]["roles"]] == ["CHECKER_SECURITY"]


async def test_reject_maker_plus_checker_in_one_invite(as_admin, seeded):
    """一次邀请同时给 Maker 与审批人 → 409，且成员不应被创建（先校验后落库）。"""
    project_id = seeded["project_id"]

    resp = await _invite(as_admin, project_id, "operator", ["MAKER", "CHECKER_DATA"])

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["code"] == "IAM_ROLE_DUTY_CONFLICT"
    assert body["data"]["rule"] == "SEPARATION_OF_DUTY"

    members = await as_admin.get(f"/api/v1/projects/{project_id}/members?limit=50")
    subjects = {m["display_name"] for m in members.json()["data"]["items"]}
    assert "陈默" not in subjects, "角色冲突时不应留下半成品成员记录"


async def test_reject_maker_then_checker_on_same_member(as_admin, seeded):
    """已有 Maker 的成员再分配审批角色 → 409。"""
    project_id = seeded["project_id"]
    created = await _invite(as_admin, project_id, "auditor", ["MAKER"])
    assert created.status_code == 201, created.text
    member_id = created.json()["data"]["id"]

    resp = await as_admin.post(
        f"/api/v1/projects/{project_id}/members/{member_id}/roles",
        json={"role_code": "CHECKER_SECURITY", "reason": "临时顶班"},
        headers=idem(),
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "IAM_ROLE_DUTY_CONFLICT"


async def test_reject_both_checker_slots_on_same_member(as_admin, seeded):
    """同一人兼任数据审批与安全审批 → 409（四眼原则失效）。"""
    project_id = seeded["project_id"]
    created = await _invite(as_admin, project_id, "auditor", ["CHECKER_DATA"])
    assert created.status_code == 201, created.text
    member_id = created.json()["data"]["id"]

    resp = await as_admin.post(
        f"/api/v1/projects/{project_id}/members/{member_id}/roles",
        json={"role_code": "CHECKER_SECURITY", "reason": "人手不足"},
        headers=idem(),
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "IAM_ROLE_DUTY_CONFLICT"


async def test_checker_cannot_gain_maker_later(as_admin, seeded):
    """反向顺序同样拦截：先审批角色，后加 Maker。"""
    project_id = seeded["project_id"]
    created = await _invite(as_admin, project_id, "operator", ["CHECKER_DATA"])
    assert created.status_code == 201, created.text
    member_id = created.json()["data"]["id"]

    resp = await as_admin.post(
        f"/api/v1/projects/{project_id}/members/{member_id}/roles",
        json={"role_code": "MAKER", "reason": "改为提需求"},
        headers=idem(),
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "IAM_ROLE_DUTY_CONFLICT"


async def test_approval_slots_and_capabilities_are_role_scoped(make_client, seeded):
    """审批槽与能力清单由角色推导：Maker 无审批槽，两个审批人各自只有一个槽。"""
    from tests.helpers import login

    project_id = seeded["project_id"]

    admin = make_client()
    await login(admin, "admin")
    await _invite(admin, project_id, "maker", ["MAKER"])
    await _invite(admin, project_id, "checker_data", ["CHECKER_DATA"])
    await _invite(admin, project_id, "checker_security", ["CHECKER_SECURITY"])

    seen = {}
    for account in ("maker", "checker_data", "checker_security"):
        c = make_client()
        await login(c, account)
        resp = await c.get("/api/v1/auth/session")
        assert resp.status_code == 200, resp.text
        seen[account] = resp.json()["data"]

    assert seen["maker"]["approval_slots"] == []
    assert seen["checker_data"]["approval_slots"] == ["DATA"]
    assert seen["checker_security"]["approval_slots"] == ["SECURITY"]

    assert "studio:session:write" in seen["maker"]["capabilities"]
    assert "studio:session:write" not in seen["checker_data"]["capabilities"]
    assert "bench:run:trigger" in seen["checker_security"]["capabilities"]
