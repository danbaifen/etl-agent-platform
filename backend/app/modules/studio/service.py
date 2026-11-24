from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.crypto import sha256_hex
from app.core.errors import AppError, Conflict, NotFound
from app.modules.asset.models import AssetConnection
from app.modules.meta.service import ProbeService
from app.modules.studio.models import (
    FlowCheckpoint,
    FlowRun,
    GenCandidate,
    StudioInterrupt,
    StudioMessage,
    StudioSession,
)

UTC = timezone.utc

WRITE_MODES = ("APPEND", "UPSERT", "OVERWRITE")

# 需要向用户澄清的参数。命中不足即中断，恢复后从 Checkpoint 继续。
CLARIFY_QUESTIONS = {
    "primary_key": {
        "text": "目标表以哪个字段作为主键去重？未指定时重复数据会整行插入。",
        "field": "primary_key",
        "type": "string",
    },
    "write_mode": {
        "text": "增量写入模式选哪种？（APPEND 追加 / UPSERT 按主键更新 / OVERWRITE 覆盖）",
        "field": "write_mode",
        "type": "enum",
        "options": list(WRITE_MODES),
    },
}


def _detect(requirement: str) -> dict:
    text = requirement.lower()
    params: dict = {}
    reserved = {"upsert", "append", "overwrite", "主键", "同步"}
    for pattern in (
        r"主键\s*(?:是|为|：|:)?\s*([a-z_][a-z0-9_]{2,})",
        r"(?:按|以|用)\s*([a-z_][a-z0-9_]{2,})\s*(?:作为)?\s*主键",
    ):
        match = re.search(pattern, requirement, re.I)
        if match and match.group(1).lower() not in reserved:
            params["primary_key"] = match.group(1).lower()
            break
    if "upsert" in text or "更新" in requirement or "覆盖写" in requirement:
        params["write_mode"] = "UPSERT"
    elif "追加" in requirement or "append" in text:
        params["write_mode"] = "APPEND"
    elif "覆盖" in requirement or "overwrite" in text:
        params["write_mode"] = "OVERWRITE"
    cron = re.search(r"每天\s*(\d{1,2})[:：](\d{2})", requirement)
    if cron:
        params["cron_expr"] = f"{int(cron.group(2))} {int(cron.group(1))} * * *"
    return params


def render_hocon(plan: dict) -> str:
    src = plan["source"]
    tgt = plan["target"]
    mappings = "\n    ".join(f"{m['source']} = {m['target']}" for m in plan["transform"]["mappings"])
    return (
        "env {\n"
        "  parallelism = 4\n"
        '  job.mode = "BATCH"\n'
        "}\n\n"
        "source {\n"
        "  Jdbc {\n"
        f'    url = "{src.get("dsn", "")}"\n'
        f'    query = "SELECT * FROM {src["object"]}"\n'
        "  }\n"
        "}\n\n"
        "transform {\n"
        "  Sql {\n"
        f'    query = "SELECT {", ".join(m["source"] for m in plan["transform"]["mappings"])} FROM {src["object"]}"\n'
        "  }\n"
        "}\n\n"
        "sink {\n"
        "  Jdbc {\n"
        f'    url = "{tgt.get("dsn", "")}"\n'
        f'    table = "{tgt["object"]}"\n'
        f'    primary_keys = ["{tgt["primary_key"]}"]\n'
        f'    save_mode = "{tgt["write_mode"].lower()}"\n'
        "  }\n"
        "}\n\n"
        "field_mapping {\n"
        f"    {mappings}\n"
        "}\n"
    )


class StudioService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _connection(self, ctx: RequestContext, connection_id: uuid.UUID) -> AssetConnection:
        conn = await self.session.get(AssetConnection, connection_id)
        if conn is None or conn.project_id != ctx.project_id:
            raise NotFound("ASSET_CONNECTION_NOT_FOUND", "连接不存在")
        return conn

    async def create_session(self, ctx: RequestContext, payload: dict) -> dict:
        source_id = uuid.UUID(str(payload["source_connection_id"]))
        target_id = uuid.UUID(str(payload["target_connection_id"]))
        requirement = (payload.get("requirement") or "").strip()
        if len(requirement) < 8:
            raise AppError("STUDIO_REQUIREMENT_TOO_SHORT", "需求描述过短，至少 8 个字", 400)

        await self._connection(ctx, source_id)
        await self._connection(ctx, target_id)

        studio_session = StudioSession(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            maker_user_id=ctx.user_id,
            source_connection_id=source_id,
            target_connection_id=target_id,
            source_object=payload.get("source_object", "crm_customer"),
            target_object=payload.get("target_object", "ads_customer"),
            requirement=requirement,
            status="OPEN",
        )
        self.session.add(studio_session)
        await self.session.flush()

        flow = FlowRun(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            session_id=studio_session.id,
            status="RUNNING",
            current_node="intent",
        )
        self.session.add(flow)
        await self.session.flush()
        studio_session.flow_run_id = flow.id

        self.session.add(
            StudioMessage(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                session_id=studio_session.id,
                role="USER",
                content_redacted=requirement,
                content_digest=sha256_hex(requirement),
            )
        )
        await self._checkpoint(ctx, flow, "intent", {"requirement": requirement, "params": _detect(requirement)})

        result = await self._advance(ctx, studio_session, flow, _detect(requirement))
        await self.session.commit()
        return result

    async def _checkpoint(self, ctx: RequestContext, flow: FlowRun, node: str, state: dict) -> None:
        count = len(
            (
                await self.session.execute(
                    select(FlowCheckpoint).where(FlowCheckpoint.flow_run_id == flow.id)
                )
            ).scalars().all()
        )
        self.session.add(
            FlowCheckpoint(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                flow_run_id=flow.id,
                checkpoint_no=count + 1,
                node_key=node,
                state_safe_json=state,
                state_sha256=sha256_hex(state),
            )
        )
        flow.current_node = node

    async def _advance(
        self, ctx: RequestContext, studio_session: StudioSession, flow: FlowRun, params: dict
    ) -> dict:
        missing = [key for key in ("primary_key", "write_mode") if not params.get(key)]
        if missing:
            question_key = missing[0]
            spec = CLARIFY_QUESTIONS[question_key]
            existing = (
                await self.session.execute(
                    select(StudioInterrupt).where(
                        StudioInterrupt.flow_run_id == flow.id,
                        StudioInterrupt.question_key == question_key,
                        StudioInterrupt.status == "PENDING",
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                interrupt = StudioInterrupt(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    flow_run_id=flow.id,
                    question_key=question_key,
                    question_text=spec["text"],
                    ui_schema={"field": spec["field"], "type": spec["type"], "options": spec.get("options", [])},
                    status="PENDING",
                )
                self.session.add(interrupt)
                await self.session.flush()
                self.session.add(
                    StudioMessage(
                        tenant_id=ctx.tenant_id,
                        project_id=ctx.project_id,
                        session_id=studio_session.id,
                        role="ASSISTANT",
                        content_redacted=spec["text"],
                        content_digest=sha256_hex(spec["text"]),
                    )
                )
            flow.status = "INTERRUPTED"
            studio_session.status = "CLARIFYING"
            await self._checkpoint(ctx, flow, f"clarify:{question_key}", {**params, "missing": missing})
            return {
                "session_id": str(studio_session.id),
                "flow_status": flow.status,
                "node": flow.current_node,
                "interrupt": {
                    "id": str(interrupt.id) if existing is None else str(existing.id),
                    "question_key": question_key,
                    "question_text": spec["text"],
                    "ui_schema": {"field": spec["field"], "type": spec["type"], "options": spec.get("options", [])},
                },
                "candidate": None,
            }

        candidate = await self._generate(ctx, studio_session, flow, params)
        return {
            "session_id": str(studio_session.id),
            "flow_status": flow.status,
            "node": flow.current_node,
            "interrupt": None,
            "candidate": candidate,
        }

    async def answer_interrupt(self, ctx: RequestContext, interrupt_id: uuid.UUID, answer: dict) -> dict:
        interrupt = await self.session.get(StudioInterrupt, interrupt_id)
        if interrupt is None or interrupt.project_id != ctx.project_id:
            raise NotFound("STUDIO_INTERRUPT_NOT_FOUND", "澄清问题不存在")
        if interrupt.status != "PENDING":
            raise Conflict("STUDIO_INTERRUPT_ANSWERED", "该问题已回答")

        flow = await self.session.get(FlowRun, interrupt.flow_run_id)
        studio_session = await self.session.get(StudioSession, flow.session_id)

        interrupt.answer_payload = answer
        interrupt.status = "ANSWERED"
        self.session.add(
            StudioMessage(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                session_id=studio_session.id,
                role="USER",
                content_redacted=f"{interrupt.question_key}={answer.get(interrupt.question_key)}",
                content_digest=sha256_hex(answer),
            )
        )

        last = (
            await self.session.execute(
                select(FlowCheckpoint)
                .where(FlowCheckpoint.flow_run_id == flow.id)
                .order_by(FlowCheckpoint.checkpoint_no.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        state = dict(last.state_safe_json) if last else {}
        state.update(answer)
        await self._checkpoint(ctx, flow, f"resume:{interrupt.question_key}", state)

        flow.status = "RUNNING"
        result = await self._advance(ctx, studio_session, flow, state)
        await self.session.commit()
        return result

    async def _generate(
        self, ctx: RequestContext, studio_session: StudioSession, flow: FlowRun, params: dict
    ) -> dict:
        probe = ProbeService(self.session)
        source_profile = await probe.latest_profile(ctx, studio_session.source_connection_id)
        if source_profile is None:
            from app.modules.meta.service import ensure_profile

            profile_row = await ensure_profile(self.session, ctx, studio_session.source_connection_id)
            source_profile = await probe.get_profile(ctx, profile_row.id)
        target_profile = await probe.latest_profile(ctx, studio_session.target_connection_id)
        if target_profile is None:
            from app.modules.meta.service import ensure_profile

            profile_row = await ensure_profile(self.session, ctx, studio_session.target_connection_id)
            target_profile = await probe.get_profile(ctx, profile_row.id)

        source_obj = next(
            (o for o in source_profile["objects"] if o["name"] == studio_session.source_object), None
        )
        if source_obj is None:
            raise AppError("STUDIO_SOURCE_OBJECT_NOT_FOUND", f"源端对象 {studio_session.source_object} 不存在", 422)

        target_obj = next(
            (o for o in target_profile["objects"] if o["name"] == studio_session.target_object), None
        )
        # 目标表允许尚不存在：按源端结构推导
        target_columns = (
            {c["name"]: c for c in target_obj["columns"]}
            if target_obj
            else {c["name"]: c for c in source_obj["columns"]}
        )

        mappings = []
        for column in source_obj["columns"]:
            name = column["name"]
            if name not in target_columns:
                continue
            mappings.append(
                {
                    "source": name,
                    "target": name,
                    "source_type": column["data_type"],
                    "target_type": target_columns[name]["data_type"],
                    "sensitivity": column["sensitivity"],
                    "mask_policy": column["mask_policy"],
                }
            )
        if not mappings:
            raise AppError("STUDIO_MAPPING_EMPTY", "源端与目标端没有可映射字段", 422)

        quality_rules = [
            {
                "code": f"MASK_VIOLATION_{m['target'].upper()}",
                "field": m["target"],
                "rule": "masked_if_sensitive",
                "policy": m["mask_policy"],
            }
            for m in mappings
            if m["mask_policy"]
        ]
        quality_rules.append(
            {"code": "PK_NULL", "field": params["primary_key"], "rule": "not_null"}
        )
        # 数值列显式加类型规则：源端脏字符串在这里被分流，而不是静默写进目标表
        for mapping in mappings:
            if any(tok in (mapping["target_type"] or "").upper() for tok in
                   ("INT", "REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC")):
                quality_rules.append(
                    {
                        "code": f"TYPE_MISMATCH_{mapping['target'].upper()}",
                        "field": mapping["target"],
                        "rule": "numeric",
                    }
                )

        plan = {
            "source": {
                "connection_id": str(studio_session.source_connection_id),
                "object": studio_session.source_object,
                "dsn": "jdbc:sqlite:source.db",
            },
            "target": {
                "connection_id": str(studio_session.target_connection_id),
                "object": studio_session.target_object,
                "dsn": "jdbc:sqlite:target.db",
                "primary_key": params["primary_key"],
                "write_mode": params.get("write_mode", "UPSERT"),
            },
            "transform": {"mappings": mappings, "filters": []},
            "quality_contract": {"rules": quality_rules},
            "supervision_contract": {
                "max_read_rows": 200_000,
                "max_write_bytes": 64 * 1024 * 1024,
                "max_duration_ms": 300_000,
                "max_amplification": 2.0,
                "max_reject_rate": 0.20,
            },
            "schedule": {
                "cron_expr": params.get("cron_expr", "0 2 * * *"),
                "timezone": "Asia/Shanghai",
            },
            "dag": {
                "nodes": ["source", "transform", "quality", "sink"],
                "edges": [["source", "transform"], ["transform", "quality"], ["quality", "sink"]],
            },
        }
        hocon = render_hocon(plan)
        artifact = sha256_hex({"plan": plan, "hocon": hocon})

        candidate = GenCandidate(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            flow_run_id=flow.id,
            session_id=studio_session.id,
            candidate_no=1,
            artifact_sha256=artifact,
            payload={"plan": plan, "hocon": hocon},
            status="GENERATED",
        )
        self.session.add(candidate)
        await self.session.flush()

        await self._checkpoint(
            ctx, flow, "generate", {"artifact_sha256": artifact, "mappings": len(mappings)}
        )
        flow.status = "SUCCEEDED"
        studio_session.status = "GENERATED"

        return {
            "id": str(candidate.id),
            "artifact_sha256": artifact,
            "plan": plan,
            "hocon": hocon,
            "candidate_no": candidate.candidate_no,
        }

    async def get_session(self, ctx: RequestContext, session_id: uuid.UUID) -> dict:
        studio_session = await self.session.get(StudioSession, session_id)
        if studio_session is None or studio_session.project_id != ctx.project_id:
            raise NotFound("STUDIO_SESSION_NOT_FOUND", "会话不存在")

        messages = (
            await self.session.execute(
                select(StudioMessage)
                .where(StudioMessage.session_id == session_id)
                .order_by(StudioMessage.created_at)
            )
        ).scalars()
        flow = await self.session.get(FlowRun, studio_session.flow_run_id) if studio_session.flow_run_id else None
        candidate = (
            await self.session.execute(
                select(GenCandidate)
                .where(GenCandidate.session_id == session_id)
                .order_by(GenCandidate.candidate_no.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        interrupt = (
            await self.session.execute(
                select(StudioInterrupt)
                .where(StudioInterrupt.flow_run_id == flow.id, StudioInterrupt.status == "PENDING")
                .limit(1)
            )
        ).scalar_one_or_none() if flow else None
        checkpoints = (
            await self.session.execute(
                select(FlowCheckpoint)
                .where(FlowCheckpoint.flow_run_id == flow.id)
                .order_by(FlowCheckpoint.checkpoint_no)
            )
        ).scalars() if flow else []

        return {
            "id": str(studio_session.id),
            "status": studio_session.status,
            "requirement": studio_session.requirement,
            "source_object": studio_session.source_object,
            "target_object": studio_session.target_object,
            "flow": (
                {
                    "id": str(flow.id),
                    "status": flow.status,
                    "current_node": flow.current_node,
                    "checkpoints": [
                        {"no": c.checkpoint_no, "node": c.node_key, "sha256": c.state_sha256}
                        for c in checkpoints
                    ],
                }
                if flow
                else None
            ),
            "messages": [
                {"role": m.role, "content": m.content_redacted, "digest": m.content_digest}
                for m in messages
            ],
            "interrupt": (
                {
                    "id": str(interrupt.id),
                    "question_key": interrupt.question_key,
                    "question_text": interrupt.question_text,
                    "ui_schema": interrupt.ui_schema,
                }
                if interrupt
                else None
            ),
            "candidate": (
                {
                    "id": str(candidate.id),
                    "artifact_sha256": candidate.artifact_sha256,
                    "status": candidate.status,
                    "payload": candidate.payload,
                }
                if candidate
                else None
            ),
        }

    async def list_sessions(self, ctx: RequestContext) -> list[dict]:
        rows = (
            await self.session.execute(
                select(StudioSession)
                .where(StudioSession.project_id == ctx.project_id)
                .order_by(StudioSession.created_at.desc())
                .limit(50)
            )
        ).scalars()
        return [
            {
                "id": str(s.id),
                "status": s.status,
                "requirement": s.requirement,
                "source_object": s.source_object,
                "target_object": s.target_object,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in rows
        ]
