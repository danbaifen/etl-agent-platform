from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.crypto import canonical_json, sha256_hex
from app.core.errors import AppError, NotFound
from app.modules.pipe.models import (
    PipeGateFinding,
    PipeGateRun,
    PipePipeline,
    PipeVersion,
    PipeVersionComponent,
    PipeSchedule,
)
from app.modules.studio.models import GenCandidate, StudioSession

UTC = timezone.utc
GATE_VERSION = "gate-1"
NUMERIC = {"INTEGER", "INT", "BIGINT", "DECIMAL", "NUMERIC", "REAL", "FLOAT", "DOUBLE"}


def _type_family(data_type: str) -> str:
    upper = (data_type or "").upper()
    for token in NUMERIC:
        if token in upper:
            return "NUMERIC"
    if "DATE" in upper or "TIME" in upper:
        return "TEMPORAL"
    if "BOOL" in upper:
        return "BOOLEAN"
    return "TEXT"


def run_gate(plan: dict, hocon: str) -> list[dict]:
    """确定性门禁：纯函数，不依赖模型、不访问数据面。

    同一份输入永远得到同一组 finding，因此可以放进版本冻结前的强制关卡。
    """
    findings: list[dict] = []

    def add(severity: str, code: str, path: str, message: str) -> None:
        findings.append({"severity": severity, "code": code, "path": path, "message": message})

    # G-001 HOCON 结构
    if hocon.count("{") != hocon.count("}"):
        add("BLOCKER", "GATE_HOCON_BRACE", "hocon", "HOCON 花括号不配对，无法解析")
    for section in ("env", "source", "sink"):
        if not re.search(rf"^\s*{section}\s*\{{", hocon, re.M):
            add("BLOCKER", "GATE_HOCON_SECTION", f"hocon.{section}", f"缺少必需段落 {section}")

    # G-002 主键
    primary_key = (plan.get("target") or {}).get("primary_key")
    if not primary_key:
        add("BLOCKER", "GATE_PRIMARY_KEY_MISSING", "plan.target.primary_key", "未声明主键，无法保证去重语义")
    else:
        mapped = {m["target"] for m in plan["transform"]["mappings"]}
        source_cols = {m["source"] for m in plan["transform"]["mappings"]}
        if primary_key not in mapped and primary_key not in source_cols:
            add("BLOCKER", "GATE_PRIMARY_KEY_UNMAPPED", "plan.target.primary_key", f"主键 {primary_key} 未出现在字段映射中")

    # G-003 映射
    mappings = plan["transform"]["mappings"]
    if not mappings:
        add("BLOCKER", "GATE_MAPPING_EMPTY", "plan.transform.mappings", "字段映射为空")
    targets = [m["target"] for m in mappings]
    duplicates = {t for t in targets if targets.count(t) > 1}
    for dup in duplicates:
        add("BLOCKER", "GATE_MAPPING_DUPLICATE", f"plan.transform.{dup}", f"目标字段 {dup} 被映射多次")

    # G-004 类型兼容
    for mapping in mappings:
        if _type_family(mapping["source_type"]) != _type_family(mapping["target_type"]):
            add(
                "WARN",
                "GATE_TYPE_MISMATCH",
                f"plan.transform.{mapping['target']}",
                f"{mapping['source_type']} → {mapping['target_type']} 类型族不一致，执行期可能拒绝",
            )

    # G-005 敏感字段脱敏
    for mapping in mappings:
        if mapping.get("mask_policy"):
            continue
        column = mapping["target"].lower()
        if any(token in column for token in ("phone", "email", "id_card", "identity", "password", "secret")):
            add(
                "BLOCKER",
                "GATE_SENSITIVE_UNMASKED",
                f"plan.transform.{mapping['target']}",
                f"字段 {mapping['target']} 疑似敏感但未声明脱敏策略",
            )

    # G-006 预算契约
    supervision = plan.get("supervision_contract") or {}
    for key in ("max_read_rows", "max_write_bytes", "max_duration_ms", "max_reject_rate"):
        if not supervision.get(key):
            add("BLOCKER", "GATE_BUDGET_MISSING", f"plan.supervision_contract.{key}", f"缺少运行预算 {key}")
    if supervision.get("max_reject_rate", 0) > 0.5:
        add("WARN", "GATE_REJECT_RATE_TOO_HIGH", "plan.supervision_contract.max_reject_rate", "拒绝率上限超过 50%，质量契约形同虚设")

    # G-007 调度表达式
    cron = ((plan.get("schedule") or {}).get("cron_expr") or "").split()
    if len(cron) != 5:
        add("BLOCKER", "GATE_CRON_INVALID", "plan.schedule.cron_expr", "调度表达式必须是 5 段 cron")

    return findings


class PipeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def freeze(self, ctx: RequestContext, candidate_id: uuid.UUID) -> dict:
        candidate = await self.session.get(GenCandidate, candidate_id)
        if candidate is None or candidate.project_id != ctx.project_id:
            raise NotFound("GEN_CANDIDATE_NOT_FOUND", "候选方案不存在")

        plan = candidate.payload["plan"]
        hocon = candidate.payload["hocon"]
        findings = run_gate(plan, hocon)
        blockers = [f for f in findings if f["severity"] == "BLOCKER"]

        studio_session = await self.session.get(StudioSession, candidate.session_id)
        pipeline = (
            await self.session.execute(
                select(PipePipeline).where(
                    PipePipeline.project_id == ctx.project_id,
                    PipePipeline.name == f"{studio_session.source_object}→{studio_session.target_object}",
                )
            )
        ).scalar_one_or_none()
        if pipeline is None:
            pipeline = PipePipeline(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                name=f"{studio_session.source_object}→{studio_session.target_object}",
                description=studio_session.requirement,
                status="DRAFT",
            )
            self.session.add(pipeline)
            await self.session.flush()

        if blockers:
            gate_run = PipeGateRun(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                pipeline_version_id=uuid.uuid4(),  # 未冻结，仅记录本次失败的门禁
                gate_version=GATE_VERSION,
                status="BLOCKED",
                checked_at=datetime.now(UTC),
                finding_count=len(findings),
            )
            self.session.add(gate_run)
            await self.session.flush()
            for finding in findings:
                self.session.add(
                    PipeGateFinding(
                        tenant_id=ctx.tenant_id,
                        project_id=ctx.project_id,
                        gate_run_id=gate_run.id,
                        **finding,
                    )
                )
            await self.session.commit()
            raise AppError(
                "PIPE_GATE_BLOCKED",
                f"门禁未通过，存在 {len(blockers)} 项阻断问题",
                422,
                {"findings": findings, "gate_run_id": str(gate_run.id)},
            )

        version_no = (
            await self.session.execute(
                select(PipeVersion.version_no)
                .where(PipeVersion.pipeline_id == pipeline.id)
                .order_by(PipeVersion.version_no.desc())
                .limit(1)
            )
        ).scalar_one_or_none() or 0
        version_no += 1

        components = {
            "ETL_PLAN": plan,
            "SEATUNNEL_HOCON": {"text": hocon},
            "FIELD_MAPPING": {"mappings": plan["transform"]["mappings"]},
            "QUALITY_CONTRACT": plan["quality_contract"],
            "SUPERVISION_CONTRACT": plan["supervision_contract"],
            "SCHEDULE_SNAPSHOT": plan["schedule"],
            "DAG": plan["dag"],
        }
        component_hashes = {key: sha256_hex(value) for key, value in components.items()}
        version_sha = sha256_hex({"components": component_hashes, "source": candidate.artifact_sha256})

        version = PipeVersion(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            pipeline_id=pipeline.id,
            version_no=version_no,
            sha256=version_sha,
            source_candidate_id=candidate.id,
            frozen_at=datetime.now(UTC),
            frozen_by_user_id=ctx.user_id,
            status="FROZEN",
            summary={
                "mapping_count": len(plan["transform"]["mappings"]),
                "warning_count": len([f for f in findings if f["severity"] == "WARN"]),
                "target": plan["target"]["object"],
                "primary_key": plan["target"]["primary_key"],
            },
        )
        self.session.add(version)
        await self.session.flush()

        for component_type, content in components.items():
            self.session.add(
                PipeVersionComponent(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    pipeline_version_id=version.id,
                    component_type=component_type,
                    content=content,
                    content_sha256=component_hashes[component_type],
                )
            )

        gate_run = PipeGateRun(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            pipeline_version_id=version.id,
            gate_version=GATE_VERSION,
            status="PASSED",
            checked_at=datetime.now(UTC),
            finding_count=len(findings),
        )
        self.session.add(gate_run)
        await self.session.flush()
        for finding in findings:
            self.session.add(
                PipeGateFinding(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    gate_run_id=gate_run.id,
                    **finding,
                )
            )

        schedule = plan["schedule"]
        existing_schedule = (
            await self.session.execute(select(PipeSchedule).where(PipeSchedule.pipeline_id == pipeline.id))
        ).scalar_one_or_none()
        schedule_sha = sha256_hex(schedule)
        if existing_schedule is None:
            self.session.add(
                PipeSchedule(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    pipeline_id=pipeline.id,
                    cron_expr=schedule["cron_expr"],
                    timezone=schedule["timezone"],
                    enabled=True,
                    snapshot_sha256=schedule_sha,
                )
            )
        else:
            existing_schedule.cron_expr = schedule["cron_expr"]
            existing_schedule.snapshot_sha256 = schedule_sha

        pipeline.active_version_id = version.id
        pipeline.status = "ACTIVE"
        candidate.status = "FROZEN"
        await self.session.commit()

        return {
            "version_id": str(version.id),
            "pipeline_id": str(pipeline.id),
            "version_no": version_no,
            "sha256": version_sha,
            "gate": {"status": "PASSED", "findings": findings},
            "components": component_hashes,
        }

    async def list_pipelines(self, ctx: RequestContext) -> list[dict]:
        rows = (
            await self.session.execute(
                select(PipePipeline).where(PipePipeline.project_id == ctx.project_id).order_by(PipePipeline.created_at.desc())
            )
        ).scalars()
        out = []
        for pipeline in rows:
            versions = (
                await self.session.execute(
                    select(PipeVersion)
                    .where(PipeVersion.pipeline_id == pipeline.id)
                    .order_by(PipeVersion.version_no.desc())
                )
            ).scalars().all()
            out.append(
                {
                    "id": str(pipeline.id),
                    "name": pipeline.name,
                    "status": pipeline.status,
                    "active_version_id": str(pipeline.active_version_id) if pipeline.active_version_id else None,
                    "version_count": len(versions),
                    "latest": (
                        {
                            "id": str(versions[0].id),
                            "version_no": versions[0].version_no,
                            "sha256": versions[0].sha256,
                            "frozen_at": versions[0].frozen_at.isoformat() if versions[0].frozen_at else None,
                        }
                        if versions
                        else None
                    ),
                }
            )
        return out

    async def get_version(self, ctx: RequestContext, version_id: uuid.UUID) -> dict:
        version = await self.session.get(PipeVersion, version_id)
        if version is None or version.project_id != ctx.project_id:
            raise NotFound("PIPE_VERSION_NOT_FOUND", "版本不存在")
        components = (
            await self.session.execute(
                select(PipeVersionComponent).where(PipeVersionComponent.pipeline_version_id == version.id)
            )
        ).scalars()
        gate = (
            await self.session.execute(
                select(PipeGateRun)
                .where(PipeGateRun.pipeline_version_id == version.id)
                .order_by(PipeGateRun.checked_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        findings = (
            await self.session.execute(
                select(PipeGateFinding).where(PipeGateFinding.gate_run_id == gate.id)
            )
        ).scalars() if gate else []

        return {
            "id": str(version.id),
            "pipeline_id": str(version.pipeline_id),
            "version_no": version.version_no,
            "sha256": version.sha256,
            "status": version.status,
            "frozen_at": version.frozen_at.isoformat() if version.frozen_at else None,
            "summary": version.summary,
            "components": [
                {"type": c.component_type, "sha256": c.content_sha256, "content": c.content}
                for c in components
            ],
            "gate": (
                {
                    "status": gate.status,
                    "gate_version": gate.gate_version,
                    "findings": [
                        {"severity": f.severity, "code": f.code, "path": f.path, "message": f.message}
                        for f in findings
                    ],
                }
                if gate
                else None
            ),
        }

    async def diff(self, ctx: RequestContext, left_id: uuid.UUID, right_id: uuid.UUID) -> dict:
        left = await self.get_version(ctx, left_id)
        right = await self.get_version(ctx, right_id)
        left_map = {c["type"]: c["content"] for c in left["components"]}
        right_map = {c["type"]: c["content"] for c in right["components"]}
        changes = []
        for component in sorted(set(left_map) | set(right_map)):
            before = canonical_json(left_map.get(component))
            after = canonical_json(right_map.get(component))
            if before != after:
                changes.append(
                    {
                        "component": component,
                        "left_sha256": sha256_hex(before),
                        "right_sha256": sha256_hex(after),
                        "left": left_map.get(component),
                        "right": right_map.get(component),
                    }
                )
        return {"left": left["id"], "right": right["id"], "changes": changes}
