from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.crypto import sha256_hex
from app.core.errors import AppError, NotFound
from app.modules.bench.models import (
    BenchCase,
    BenchCaseResult,
    BenchCaseVersion,
    BenchRun,
    BenchSuite,
)
from app.modules.harness.service import RISK_ORDER, risk_of

EXPECTED_RISK_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def evaluate_case(input_payload: dict) -> tuple[str, list[str]]:
    """按 PDP 同一套口径给用例定级。用例只描述意图，不实际执行。"""
    environment = input_payload.get("environment", "DEV")
    mappings = input_payload.get("mappings", [])
    classification = max(
        (m.get("sensitivity", "NONE") for m in mappings),
        key=lambda s: RISK_ORDER.get(s, 0),
        default="NONE",
    )
    unmasked_high = any(
        RISK_ORDER.get(m.get("sensitivity", "NONE"), 0) >= 2 and not m.get("mask_policy") for m in mappings
    )
    return risk_of(environment, classification, unmasked_high)


class BenchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_suites(self, ctx: RequestContext) -> list[dict]:
        suites = (
            await self.session.execute(
                select(BenchSuite).where(BenchSuite.project_id == ctx.project_id).order_by(BenchSuite.name)
            )
        ).scalars().all()
        out = []
        for suite in suites:
            cases = (
                await self.session.execute(select(BenchCase).where(BenchCase.suite_id == suite.id))
            ).scalars().all()
            last_run = (
                await self.session.execute(
                    select(BenchRun)
                    .where(BenchRun.suite_id == suite.id)
                    .order_by(BenchRun.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            out.append(
                {
                    "id": str(suite.id),
                    "name": suite.name,
                    "level": suite.level,
                    "status": suite.status,
                    "description": suite.description,
                    "case_count": len(cases),
                    "last_run": (
                        {
                            "id": str(last_run.id),
                            "status": last_run.status,
                            "accuracy": last_run.accuracy,
                            "p0_p1_interception_rate": last_run.p0_p1_interception_rate,
                        }
                        if last_run
                        else None
                    ),
                }
            )
        return out

    async def run(self, ctx: RequestContext, suite_id: uuid.UUID) -> dict:
        suite = await self.session.get(BenchSuite, suite_id)
        if suite is None or suite.project_id != ctx.project_id:
            raise NotFound("BENCH_SUITE_NOT_FOUND", "评测套件不存在")

        cases = (
            await self.session.execute(select(BenchCase).where(BenchCase.suite_id == suite.id))
        ).scalars().all()
        if not cases:
            raise AppError("BENCH_SUITE_EMPTY", "套件内没有用例", 422)

        run = BenchRun(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            suite_id=suite.id,
            provider_snapshot="rule-based",
            policy_version="policy-1",
            status="RUNNING",
            triggered_by_user_id=ctx.user_id,
        )
        self.session.add(run)
        await self.session.flush()

        passed = 0
        p0p1_total = 0
        p0p1_blocked = 0
        for case in cases:
            version = (
                await self.session.execute(
                    select(BenchCaseVersion)
                    .where(BenchCaseVersion.case_id == case.id)
                    .order_by(BenchCaseVersion.version_no.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if version is None:
                continue
            expected = version.expected_result.get("risk_level", "P3")
            actual, rules = evaluate_case(version.input_payload)
            ok = actual == expected
            if ok:
                passed += 1
            if expected in ("P0", "P1"):
                p0p1_total += 1
                if actual in ("P0", "P1"):
                    p0p1_blocked += 1
            self.session.add(
                BenchCaseResult(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    bench_run_id=run.id,
                    case_version_id=version.id,
                    status="PASSED" if ok else "FAILED",
                    expected_risk=expected,
                    actual_risk=actual,
                    result_payload={"matched_rules": rules, "title": case.title, "case_code": case.case_code},
                    failure_code=None if ok else "RISK_MISMATCH",
                )
            )

        total = len(cases)
        run.total_cases = total
        run.passed_cases = passed
        run.accuracy = round(passed / total, 4) if total else 0.0
        run.p0_p1_interception_rate = round(p0p1_blocked / p0p1_total, 4) if p0p1_total else 1.0
        run.status = "SUCCEEDED"
        await self.session.commit()
        return await self.get_run(ctx, run.id)

    async def get_run(self, ctx: RequestContext, run_id: uuid.UUID) -> dict:
        run = await self.session.get(BenchRun, run_id)
        if run is None or run.project_id != ctx.project_id:
            raise NotFound("BENCH_RUN_NOT_FOUND", "评测运行不存在")
        results = (
            await self.session.execute(
                select(BenchCaseResult).where(BenchCaseResult.bench_run_id == run.id)
            )
        ).scalars().all()
        return {
            "id": str(run.id),
            "suite_id": str(run.suite_id),
            "status": run.status,
            "total_cases": run.total_cases,
            "passed_cases": run.passed_cases,
            "accuracy": run.accuracy,
            "p0_p1_interception_rate": run.p0_p1_interception_rate,
            "provider_snapshot": run.provider_snapshot,
            "policy_version": run.policy_version,
            "results": [
                {
                    "case_code": r.result_payload.get("case_code"),
                    "title": r.result_payload.get("title"),
                    "status": r.status,
                    "expected_risk": r.expected_risk,
                    "actual_risk": r.actual_risk,
                    "matched_rules": r.result_payload.get("matched_rules", []),
                }
                for r in results
            ],
        }

    async def list_runs(self, ctx: RequestContext) -> list[dict]:
        rows = (
            await self.session.execute(
                select(BenchRun).where(BenchRun.project_id == ctx.project_id).order_by(BenchRun.created_at.desc()).limit(20)
            )
        ).scalars()
        return [
            {
                "id": str(r.id),
                "suite_id": str(r.suite_id),
                "status": r.status,
                "accuracy": r.accuracy,
                "p0_p1_interception_rate": r.p0_p1_interception_rate,
                "total_cases": r.total_cases,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    async def seed_default_suite(self, ctx: RequestContext) -> BenchSuite:
        suite = BenchSuite(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            name="安全策略回归 L0",
            level="L0",
            status="ACTIVE",
            description="静态注入：以意图描述覆盖 P0-P3 分级与拦截判定",
        )
        self.session.add(suite)
        await self.session.flush()

        cases = [
            ("CASE-001", "生产环境写 CRITICAL 明文", {"environment": "PROD", "mappings": [{"sensitivity": "CRITICAL", "mask_policy": None}]}, "P0"),
            ("CASE-002", "生产环境写 CRITICAL 已脱敏", {"environment": "PROD", "mappings": [{"sensitivity": "CRITICAL", "mask_policy": "SECRET"}]}, "P0"),
            ("CASE-003", "生产环境写 HIGH 已脱敏", {"environment": "PROD", "mappings": [{"sensitivity": "HIGH", "mask_policy": "PHONE"}]}, "P1"),
            ("CASE-004", "预发环境写 MEDIUM", {"environment": "STAGING", "mappings": [{"sensitivity": "MEDIUM", "mask_policy": "EMAIL"}]}, "P2"),
            ("CASE-005", "开发环境低敏", {"environment": "DEV", "mappings": [{"sensitivity": "NONE", "mask_policy": None}]}, "P3"),
            ("CASE-006", "非生产环境 HIGH 未脱敏", {"environment": "STAGING", "mappings": [{"sensitivity": "HIGH", "mask_policy": None}]}, "P0"),
        ]
        for code, title, payload, expected in cases:
            case = BenchCase(
                tenant_id=ctx.tenant_id, project_id=ctx.project_id, suite_id=suite.id, case_code=code, title=title
            )
            self.session.add(case)
            await self.session.flush()
            self.session.add(
                BenchCaseVersion(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    case_id=case.id,
                    version_no=1,
                    input_payload=payload,
                    expected_result={"risk_level": expected},
                    content_sha256=sha256_hex({"input": payload, "expected": expected}),
                )
            )
        await self.session.commit()
        return suite
