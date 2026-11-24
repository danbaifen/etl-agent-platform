"""AC-02 ~ AC-09 端到端链路：连接 → 探查 → 生成 → 门禁冻结 → Prepare/Approve/Commit → 执行 → 质量 → Swap / 中断 / 回滚 → 评测。

数据面是真实 SQLite 仓库：执行阶段真的读源表、真的写影子表与错误表、真的做表改名 Swap。
因此这里断言的行数与拒绝率是实测结果，不是桩数据。
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from app.scripts.seed_demo import build_warehouse
from tests.helpers import ACCOUNTS, idem, login

pytestmark = pytest.mark.acceptance

DATA_DIR = os.path.join(tempfile.mkdtemp(prefix="etl-demo-"), "demo")


@pytest.fixture
async def chain(make_client, as_admin, seeded):
    source_path, target_path = build_warehouse(DATA_DIR)
    project_id = seeded["project_id"]

    for account, role in (
        ("maker", "MAKER"),
        ("checker_data", "CHECKER_DATA"),
        ("checker_security", "CHECKER_SECURITY"),
        ("operator", "OPERATOR"),
        ("auditor", "AUDITOR"),
    ):
        resp = await as_admin.post(
            f"/api/v1/projects/{project_id}/members",
            json={"external_subject": ACCOUNTS[account], "role_codes": [role]},
            headers=idem(),
        )
        assert resp.status_code == 201, resp.text

    clients = {}
    for account in ("maker", "checker_data", "checker_security", "operator", "auditor"):
        c = make_client()
        await login(c, account)
        clients[account] = c

    maker = clients["maker"]
    source = await maker.post(
        "/api/v1/connections",
        json={
            "name": "CRM 生产库",
            "connection_type": "SQLITE",
            "environment": "PROD",
            "safe_config": {"database_path": source_path.replace("\\", "/")},
        },
        headers=idem(),
    )
    assert source.status_code == 201, source.text
    target = await maker.post(
        "/api/v1/connections",
        json={
            "name": "Doris 生产仓",
            "connection_type": "SQLITE",
            "environment": "PROD",
            "safe_config": {"database_path": target_path.replace("\\", "/")},
        },
        headers=idem(),
    )
    assert target.status_code == 201, target.text

    return {
        "clients": clients,
        "source_id": source.json()["data"]["id"],
        "target_id": target.json()["data"]["id"],
        "source_path": source_path,
        "target_path": target_path,
        "project_id": project_id,
        "tenant_id": seeded["tenant_id"],
    }


async def _run_chain(chain, source_object: str, target_object: str, requirement: str) -> dict:
    maker = chain["clients"]["maker"]

    probe = await maker.post(
        f"/api/v1/connections/{chain['source_id']}/probe", json={"sample": True}, headers=idem()
    )
    assert probe.status_code == 202, probe.text
    target_probe = await maker.post(
        f"/api/v1/connections/{chain['target_id']}/probe", json={"sample": True}, headers=idem()
    )
    assert target_probe.status_code == 202, target_probe.text

    session = await maker.post(
        "/api/v1/studio/sessions",
        json={
            "source_connection_id": chain["source_id"],
            "target_connection_id": chain["target_id"],
            "source_object": source_object,
            "target_object": target_object,
            "requirement": requirement,
        },
        headers=idem(),
    )
    assert session.status_code == 201, session.text
    body = session.json()["data"]
    session_id = body["session_id"]

    # 缺参 → 中断 → 回答 → 从 Checkpoint 恢复生成
    rounds = 0
    while body.get("interrupt"):
        rounds += 1
        assert rounds <= 3, "澄清轮次异常，可能存在死循环"
        interrupt = body["interrupt"]
        field = interrupt["ui_schema"]["field"]
        answer = {"primary_key": "customer_id" if source_object == "crm_customer" else "event_id"}
        answer.setdefault(field, "UPSERT")
        resumed = await maker.post(
            f"/api/v1/studio/interrupts/{interrupt['id']}/answer",
            json={field: answer[field]},
            headers=idem(),
        )
        assert resumed.status_code == 200, resumed.text
        body = resumed.json()["data"]

    assert body["candidate"], "恢复后应生成候选方案"
    candidate = body["candidate"]

    frozen = await maker.post(f"/api/v1/candidates/{candidate['id']}/freeze", headers=idem())
    assert frozen.status_code == 200, frozen.text
    version = frozen.json()["data"]
    assert version["gate"]["status"] == "PASSED"

    preparation = await maker.post(f"/api/v1/versions/{version['version_id']}/prepare", headers=idem())
    assert preparation.status_code == 201, preparation.text
    prep = preparation.json()["data"]

    return {"session_id": session_id, "candidate": candidate, "version": version, "preparation": prep}


async def _approve_and_commit(chain, preparation: dict) -> dict:
    checker_data = chain["clients"]["checker_data"]
    checker_security = chain["clients"]["checker_security"]
    operator = chain["clients"]["operator"]

    slots = {s["slot_code"]: s for s in preparation["slots"]}
    assert set(slots) == {"DATA", "SECURITY"}, "P1 风险应同时要求业务与安全两个审批槽"

    # 四眼原则：申请人（Maker）不得审批自己的准备单
    self_approval = await chain["clients"]["maker"].post(
        f"/api/v1/preparations/{preparation['id']}/approve",
        json={"slot_code": "DATA", "decision": "APPROVE", "comment": "自己批自己"},
    )
    assert self_approval.status_code == 403, self_approval.text
    assert self_approval.json()["code"] == "HARNESS_SELF_APPROVAL_FORBIDDEN"

    # 非指定审批人也不能代批
    wrong_slot = await checker_data.post(
        f"/api/v1/preparations/{preparation['id']}/approve",
        json={"slot_code": "SECURITY", "decision": "APPROVE", "comment": "越槽审批"},
    )
    assert wrong_slot.status_code == 403
    assert wrong_slot.json()["code"] == "HARNESS_NOT_ASSIGNEE"

    r1 = await checker_data.post(
        f"/api/v1/preparations/{preparation['id']}/approve",
        json={"slot_code": "DATA", "decision": "APPROVE", "comment": "字段映射与质量规则已核对"},
    )
    assert r1.status_code == 200, r1.text
    r2 = await checker_security.post(
        f"/api/v1/preparations/{preparation['id']}/approve",
        json={"slot_code": "SECURITY", "decision": "APPROVE", "comment": "敏感字段已脱敏，预算可接受"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == "APPROVED"

    commit = await operator.post(f"/api/v1/preparations/{preparation['id']}/commit", headers=idem())
    assert commit.status_code == 201, commit.text
    return commit.json()["data"]


async def test_ac02_to_ac07_happy_path(chain):
    build = await _run_chain(
        chain,
        "crm_customer",
        "ads_customer",
        "把业务库订单表按 customer_id 主键同步到 Doris 宽表，手机号与邮箱要脱敏",
    )

    # AC-02：元数据探查可读、敏感字段已脱敏
    profile = await chain["clients"]["maker"].get(
        f"/api/v1/connections/{chain['source_id']}/profile"
    )
    assert profile.status_code == 200, profile.text
    objects = profile.json()["data"]["objects"]
    customer = next(o for o in objects if o["name"] == "crm_customer")
    phone = next(c for c in customer["columns"] if c["name"] == "phone")
    assert phone["sensitivity"] == "HIGH"
    assert all("****" in s or s.startswith("***") for s in phone["samples"] if s != "<NULL>"), phone["samples"]

    # AC-04：门禁通过 + 不可变版本摘要
    version = build["version"]
    assert len(version["sha256"]) == 64
    assert version["components"]["SEATUNNEL_HOCON"]

    # AC-05：三阶段协议 + 单次 Capability
    preparation = build["preparation"]
    for key in ("input_fingerprint", "snapshot_sha256", "budget", "rollback_plan", "slots"):
        assert preparation[key], f"准备单缺少 {key}"

    committed = await _approve_and_commit(chain, preparation)
    assert committed["capability"]["jti"]

    # 重放守卫：第二次 commit 应被拒
    again = await chain["clients"]["operator"].post(
        f"/api/v1/preparations/{preparation['id']}/commit", headers=idem()
    )
    assert again.status_code == 409

    # AC-06 / AC-07：真实执行 + 质量分流 + 原子 Swap
    run = await chain["clients"]["operator"].post(f"/api/v1/runs/{committed['exec_run_id']}/start")
    assert run.status_code == 200, run.text
    result = run.json()["data"]
    assert result["status"] == "SUCCEEDED", result
    assert result["read_rows"] == 12
    assert result["written_rows"] >= 10, result
    assert result["quality_report"]["swapped"] is True
    assert result["publication"]["status"] == "PUBLISHED"

    # 目标表已被影子表替换，行数应为有效行数
    conn = sqlite3.connect(chain["target_path"])
    try:
        rows = conn.execute("SELECT COUNT(*) FROM ads_customer").fetchone()[0]
        masked = conn.execute("SELECT phone FROM ads_customer LIMIT 1").fetchone()[0]
    finally:
        conn.close()
    assert rows == result["written_rows"]
    assert "****" in masked, f"目标表出现明文手机号：{masked}"

    # 证据链：Prepare / 审批 / Commit / 执行 / Swap 都应留下可校验记录
    evidence = await chain["clients"]["auditor"].get("/api/v1/evidence")
    assert evidence.status_code == 200, evidence.text
    chain_data = evidence.json()["data"]
    assert chain_data["length"] >= 4
    assert chain_data["intact"] is True, chain_data["problems"]
    assert {r["event_type"] for r in chain_data["records"]} >= {
        "PREPARATION_FROZEN",
        "APPROVAL_DECISION",
        "COMMIT",
        "ATOMIC_SWAP",
    }


async def test_ac08_supervision_abort_and_rollback(chain):
    build = await _run_chain(
        chain,
        "log_event",
        "ads_log",
        "把日志表按 event_id 主键 upsert 到宽表，时长字段必须是数值",
    )
    committed = await _approve_and_commit(chain, build["preparation"])

    run = await chain["clients"]["operator"].post(f"/api/v1/runs/{committed['exec_run_id']}/start")
    assert run.status_code == 200, run.text
    result = run.json()["data"]

    # 拒绝率 50% 超过 20% 预算 → 硬中断
    assert result["status"] == "ABORTED", result
    assert result["reject_rows"] >= 4
    assert result["failure"]["error_code"].startswith("SUPERVISION_")
    assert result["diagnosis"]["root_cause"]
    assert result["diagnosis"]["recommendation"]
    assert result["publication"]["status"] == "SKIPPED"

    # 受管回滚
    rollback = await chain["clients"]["operator"].post(
        f"/api/v1/runs/{result['id']}/rollback", json={"reason": "超预算中断后清理影子表"}
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["data"]["status"] == "ROLLED_BACK"

    conn = sqlite3.connect(chain["target_path"])
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()
    assert "ads_log__shadow" not in names
    assert "ads_log__err" not in names


async def test_ac09_benchmark_report(chain):
    operator = chain["clients"]["checker_security"]
    suites = await operator.get("/api/v1/bench/suites")
    assert suites.status_code == 200, suites.text
    items = suites.json()["data"]
    # 演示环境由 seed_demo 预置套件；测试库内现场建一个
    if not items:
        from sqlalchemy import select

        from app.core.context import RequestContext
        from app.core.db import get_session_factory
        from app.modules.bench.service import BenchService
        from app.modules.iam.models import IamUser

        async with get_session_factory()() as session:
            user = (
                await session.execute(select(IamUser).where(IamUser.external_subject == ACCOUNTS["maker"]))
            ).scalar_one()
            ctx = RequestContext(
                trace_id="test",
                user_id=user.id,
                display_name=user.display_name,
                tenant_id=chain["tenant_id"],
                project_id=chain["project_id"],
            )
            await BenchService(session).seed_default_suite(ctx)
        suites = await operator.get("/api/v1/bench/suites")
        items = suites.json()["data"]

    suite_id = items[0]["id"]
    run = await operator.post(f"/api/v1/bench/suites/{suite_id}/runs")
    assert run.status_code == 201, run.text
    data = run.json()["data"]
    assert data["total_cases"] >= 5
    assert 0.0 <= data["accuracy"] <= 1.0
    assert 0.0 <= data["p0_p1_interception_rate"] <= 1.0
    assert data["results"]

