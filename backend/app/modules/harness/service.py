from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import as_utc
from app.core.context import RequestContext
from app.core.crypto import canonical_json, generate_keypair, sha256_hex, sign as crypto_sign, verify as crypto_verify
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.modules.asset.models import AssetConnection
from app.modules.exec.models import ExecRun
from app.modules.harness.models import (
    HarnessApprovalDecision,
    HarnessApprovalSlot,
    HarnessBudgetContract,
    HarnessCapability,
    HarnessCapabilityConsumption,
    HarnessCommit,
    HarnessEvidenceRecord,
    HarnessOutboxEvent,
    HarnessPdpDecision,
    HarnessPreparation,
    HarnessPreparationResource,
    HarnessRollbackPlan,
    HarnessSigningKey,
    HarnessToolIntent,
)
from app.modules.iam import models as iam
from app.modules.pipe.models import PipeVersion, PipeVersionComponent
from app.modules.pipe.service import PipeService

UTC = timezone.utc
CAPABILITY_TTL_SECONDS = 300
TOOL_NAME = "seatunnel.submit"

RISK_ORDER = {"NONE": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def risk_of(environment: str, classification: str, unmasked_high: bool) -> tuple[str, list[str]]:
    """风险评级纯函数：PDP 与 Benchmark 共用同一套口径，避免两处漂移。"""
    if environment == "PROD" and classification == "CRITICAL":
        return "P0", ["R-PROD-CRITICAL", "R-WRITE-PROD"]
    if unmasked_high:
        return "P0", ["R-SENSITIVE-UNMASKED"]
    if environment == "PROD" or classification == "HIGH":
        return "P1", ["R-WRITE-PROD" if environment == "PROD" else "R-SENSITIVE-HIGH"]
    if environment == "STAGING" or classification == "MEDIUM":
        return "P2", ["R-NON-PROD-WRITE"]
    return "P3", ["R-DEV-LOW-RISK"]


async def get_signing_key(session: AsyncSession) -> HarnessSigningKey:
    key = (
        await session.execute(
            select(HarnessSigningKey).where(HarnessSigningKey.status == "ACTIVE").limit(1)
        )
    ).scalar_one_or_none()
    if key is not None:
        return key
    private_pem, public_pem = generate_keypair()
    key = HarnessSigningKey(
        key_id=f"key-{uuid.uuid4().hex[:8]}",
        algorithm="Ed25519",
        public_key=public_pem,
        # 演示环境落库以便重启后可验证；生产必须由 KMS/HSM 托管，库里只留公钥
        private_key=private_pem,
        status="ACTIVE",
        created_at=datetime.now(UTC),
    )
    session.add(key)
    await session.flush()
    return key


async def append_evidence(
    session: AsyncSession,
    ctx: RequestContext,
    event_type: str,
    artifact_sha256: str,
    payload: dict,
    chain_id: str | None = None,
) -> HarnessEvidenceRecord:
    chain = chain_id or f"project:{ctx.project_id}"
    last = (
        await session.execute(
            select(HarnessEvidenceRecord)
            .where(HarnessEvidenceRecord.chain_id == chain)
            .order_by(HarnessEvidenceRecord.sequence_no.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    prev_hash = last.record_hash if last else ""
    sequence = (last.sequence_no + 1) if last else 1

    key = await get_signing_key(session)
    body = {
        "chain_id": chain,
        "sequence_no": sequence,
        "actor": str(ctx.user_id),
        "event_type": event_type,
        "artifact_sha256": artifact_sha256,
        "payload": payload,
        "prev_hash": prev_hash,
    }
    record_hash = sha256_hex(body)
    record = HarnessEvidenceRecord(
        id=uuid.uuid4(),
        chain_id=chain,
        sequence_no=sequence,
        tenant_id=ctx.tenant_id,
        project_id=ctx.project_id,
        actor=str(ctx.user_id),
        event_type=event_type,
        artifact_sha256=artifact_sha256,
        payload=payload,
        prev_hash=prev_hash,
        record_hash=record_hash,
        signature=crypto_sign(key.private_key, record_hash),
        key_id=key.key_id,
        created_at=datetime.now(UTC),
    )
    session.add(record)
    await session.flush()
    return record


class HarnessService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- 风险决策 ----------
    async def _pdp(
        self, ctx: RequestContext, version: PipeVersion, plan: dict, environment: str
    ) -> tuple[HarnessPdpDecision, HarnessToolIntent]:
        mappings = plan["transform"]["mappings"]
        sensitivities = [m.get("sensitivity", "NONE") for m in mappings]
        classification = max(sensitivities, key=lambda s: RISK_ORDER.get(s, 0)) if sensitivities else "NONE"
        unmasked_high = [
            m for m in mappings if RISK_ORDER.get(m.get("sensitivity", "NONE"), 0) >= 2 and not m.get("mask_policy")
        ]

        risk, rules = risk_of(environment, classification, bool(unmasked_high))

        slots = {"DATA": risk in ("P0", "P1", "P2"), "SECURITY": risk in ("P0", "P1")}
        requirements = {
            "slots": [code for code, needed in slots.items() if needed],
            "four_eyes": risk in ("P0", "P1"),
            "description": {
                "P0": "最高风险：敏感数据进入生产，需业务与安全双审批",
                "P1": "高风险：生产写入或高敏数据，需业务与安全双审批",
                "P2": "中风险：非生产写入或中敏数据，需业务审批",
                "P3": "低风险：开发环境低敏数据，免审批",
            }[risk],
        }

        intent = HarnessToolIntent(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            actor_user_id=ctx.user_id,
            tool_name=TOOL_NAME,
            environment=environment,
            resource_scope={
                "source": plan["source"]["object"],
                "target": plan["target"]["object"],
                "artifact_sha256": version.sha256,
            },
            parameter_sha256=sha256_hex(plan),
        )
        self.session.add(intent)
        await self.session.flush()

        decision_body = {
            "tool_intent_id": str(intent.id),
            "risk_level": risk,
            "classification": classification,
            "approval_requirements": requirements,
            "rules": rules,
        }
        decision = HarnessPdpDecision(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            tool_intent_id=intent.id,
            policy_version="policy-1",
            risk_level=risk,
            approval_requirements=requirements,
            matched_rules=rules,
            reason=requirements["description"],
            decision_sha256=sha256_hex(decision_body),
        )
        self.session.add(decision)
        await self.session.flush()
        return decision, intent

    # ---------- Prepare ----------
    async def prepare(self, ctx: RequestContext, version_id: uuid.UUID) -> dict:
        version = await self.session.get(PipeVersion, version_id)
        if version is None or version.project_id != ctx.project_id:
            raise NotFound("PIPE_VERSION_NOT_FOUND", "版本不存在")

        components = {
            c.component_type: c.content
            for c in (
                await self.session.execute(
                    select(PipeVersionComponent).where(PipeVersionComponent.pipeline_version_id == version.id)
                )
            ).scalars()
        }
        plan = components["ETL_PLAN"]

        target_conn = await self.session.get(
            AssetConnection, uuid.UUID(str(plan["target"]["connection_id"]))
        )
        source_conn = await self.session.get(
            AssetConnection, uuid.UUID(str(plan["source"]["connection_id"]))
        )
        if target_conn is None or source_conn is None:
            raise AppError("HARNESS_CONNECTION_MISSING", "源端或目标端连接已不存在", 422)

        existing = (
            await self.session.execute(
                select(HarnessPreparation)
                .where(
                    HarnessPreparation.pipeline_version_id == version.id,
                    HarnessPreparation.status.in_(["PENDING_APPROVAL", "APPROVED", "COMMITTED"]),
                )
                .order_by(HarnessPreparation.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return await self._preparation_view(ctx, existing)

        decision, intent = await self._pdp(ctx, version, plan, target_conn.environment)

        input_fingerprint = sha256_hex(
            {
                "version_sha256": version.sha256,
                "source_conn": str(source_conn.id),
                "target_conn": str(target_conn.id),
                "source_env": source_conn.environment,
                "target_env": target_conn.environment,
            }
        )

        resources = [
            {"resource_type": "TABLE", "resource_ref": f"{source_conn.name}:{plan['source']['object']}", "access_mode": "READ"},
            {"resource_type": "TABLE", "resource_ref": f"{target_conn.name}:{plan['target']['object']}", "access_mode": "WRITE"},
            {"resource_type": "SHADOW_TABLE", "resource_ref": f"{target_conn.name}:{plan['target']['object']}__shadow", "access_mode": "WRITE"},
            {"resource_type": "ERROR_TABLE", "resource_ref": f"{target_conn.name}:{plan['target']['object']}__err", "access_mode": "WRITE"},
            {"resource_type": "SECRET", "resource_ref": str(target_conn.secret_ref_id or "none"), "access_mode": "USE"},
        ]
        supervision = plan["supervision_contract"]
        rollback_steps = [
            "删除影子表与错误表中的本次写入",
            "恢复 Swap 前正式表快照（若已 Swap）",
            "终止 SeaTunnel 作业并释放资源",
            "写入回滚证据并标记执行记录",
        ]

        approvers = await self._eligible_approvers(ctx, decision.approval_requirements["slots"])
        snapshot = {
            "pipeline_version_id": str(version.id),
            "version_sha256": version.sha256,
            "input_fingerprint": input_fingerprint,
            "risk_level": decision.risk_level,
            "approval_requirements": decision.approval_requirements,
            "resources": resources,
            "budget": supervision,
            "rollback_plan": rollback_steps,
            "approvers": approvers,
            "environment": target_conn.environment,
        }
        snapshot_sha = sha256_hex(snapshot)

        preparation = HarnessPreparation(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            pipeline_version_id=version.id,
            pdp_decision_id=decision.id,
            input_fingerprint=input_fingerprint,
            snapshot_sha256=snapshot_sha,
            snapshot=snapshot,
            risk_level=decision.risk_level,
            data_classification=max(
                (m.get("sensitivity", "NONE") for m in plan["transform"]["mappings"]),
                key=lambda s: RISK_ORDER.get(s, 0),
                default="NONE",
            ),
            status="PENDING_APPROVAL" if decision.approval_requirements["slots"] else "APPROVED",
            created_by_user_id=ctx.user_id,
        )
        self.session.add(preparation)
        await self.session.flush()

        for resource in resources:
            self.session.add(
                HarnessPreparationResource(
                    tenant_id=ctx.tenant_id, project_id=ctx.project_id, preparation_id=preparation.id, **resource
                )
            )
        self.session.add(
            HarnessBudgetContract(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                preparation_id=preparation.id,
                max_read_rows=supervision["max_read_rows"],
                max_write_bytes=supervision["max_write_bytes"],
                max_duration_ms=supervision["max_duration_ms"],
                max_amplification=supervision.get("max_amplification", 2.0),
                max_reject_rate=supervision["max_reject_rate"],
            )
        )
        self.session.add(
            HarnessRollbackPlan(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                preparation_id=preparation.id,
                scope="SHADOW_ONLY",
                steps=rollback_steps,
                plan_sha256=sha256_hex(rollback_steps),
            )
        )

        for slot_code in decision.approval_requirements["slots"]:
            candidates = approvers[slot_code]
            if not candidates:
                raise AppError(
                    "HARNESS_APPROVER_MISSING",
                    f"缺少 {slot_code} 审批人：请先为该槽位配置独立审批角色，或降低风险等级",
                    409,
                    {"slot": slot_code},
                )
            self.session.add(
                HarnessApprovalSlot(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    preparation_id=preparation.id,
                    slot_code=slot_code,
                    assignee_user_id=uuid.UUID(candidates[0]["user_id"]),
                    status="PENDING",
                )
            )

        await append_evidence(
            self.session,
            ctx,
            "PREPARATION_FROZEN",
            snapshot_sha,
            {"preparation_id": str(preparation.id), "risk_level": decision.risk_level},
        )
        await self.session.commit()
        return await self._preparation_view(ctx, preparation)

    async def _eligible_approvers(self, ctx: RequestContext, slots: list[str]) -> dict:
        role_map = {"DATA": "CHECKER_DATA", "SECURITY": "CHECKER_SECURITY"}
        result: dict[str, list[dict]] = {"DATA": [], "SECURITY": []}
        for slot in slots:
            role_code = role_map[slot]
            rows = (
                await self.session.execute(
                    select(iam.IamUser.id, iam.IamUser.display_name)
                    .join(iam.IamMember, iam.IamMember.user_id == iam.IamUser.id)
                    .join(iam.IamMemberRole, iam.IamMemberRole.member_id == iam.IamMember.id)
                    .join(iam.IamRole, iam.IamRole.id == iam.IamMemberRole.role_id)
                    .where(
                        iam.IamMember.project_id == ctx.project_id,
                        iam.IamMember.status == "ACTIVE",
                        iam.IamMemberRole.valid_to.is_(None),
                        iam.IamRole.code == role_code,
                        iam.IamUser.id != ctx.user_id,
                    )
                )
            ).all()
            result[slot] = [{"user_id": str(r[0]), "display_name": r[1]} for r in rows]
        return result

    async def _preparation_view(self, ctx: RequestContext, preparation: HarnessPreparation) -> dict:
        slots = (
            await self.session.execute(
                select(HarnessApprovalSlot).where(HarnessApprovalSlot.preparation_id == preparation.id)
            )
        ).scalars().all()
        decisions = (
            await self.session.execute(
                select(HarnessApprovalDecision).where(
                    HarnessApprovalDecision.preparation_id == preparation.id
                )
            )
        ).scalars().all()
        budget = (
            await self.session.execute(
                select(HarnessBudgetContract).where(HarnessBudgetContract.preparation_id == preparation.id)
            )
        ).scalar_one_or_none()
        rollback = (
            await self.session.execute(
                select(HarnessRollbackPlan).where(HarnessRollbackPlan.preparation_id == preparation.id)
            )
        ).scalar_one_or_none()
        resources = (
            await self.session.execute(
                select(HarnessPreparationResource).where(
                    HarnessPreparationResource.preparation_id == preparation.id
                )
            )
        ).scalars().all()

        users = {
            str(u.id): u.display_name
            for u in (await self.session.execute(select(iam.IamUser))).scalars().all()
        }
        return {
            "id": str(preparation.id),
            "pipeline_version_id": str(preparation.pipeline_version_id),
            "status": preparation.status,
            "risk_level": preparation.risk_level,
            "data_classification": preparation.data_classification,
            "input_fingerprint": preparation.input_fingerprint,
            "snapshot_sha256": preparation.snapshot_sha256,
            "snapshot": preparation.snapshot,
            "resources": [
                {"type": r.resource_type, "ref": r.resource_ref, "access": r.access_mode} for r in resources
            ],
            "budget": (
                {
                    "max_read_rows": budget.max_read_rows,
                    "max_write_bytes": budget.max_write_bytes,
                    "max_duration_ms": budget.max_duration_ms,
                    "max_amplification": budget.max_amplification,
                    "max_reject_rate": budget.max_reject_rate,
                }
                if budget
                else None
            ),
            "rollback_plan": ({"scope": rollback.scope, "steps": rollback.steps} if rollback else None),
            "slots": [
                {
                    "id": str(s.id),
                    "slot_code": s.slot_code,
                    "assignee_user_id": str(s.assignee_user_id),
                    "assignee_name": users.get(str(s.assignee_user_id), "-"),
                    "status": s.status,
                }
                for s in slots
            ],
            "decisions": [
                {
                    "slot_id": str(d.approval_slot_id),
                    "approver_user_id": str(d.approver_user_id),
                    "approver_name": users.get(str(d.approver_user_id), "-"),
                    "decision": d.decision,
                    "comment": d.comment,
                    "signature": d.signature[:16] + "…",
                    "decided_at": d.decided_at.isoformat(),
                }
                for d in decisions
            ],
        }

    async def get_preparation(self, ctx: RequestContext, preparation_id: uuid.UUID) -> dict:
        preparation = await self.session.get(HarnessPreparation, preparation_id)
        if preparation is None or preparation.project_id != ctx.project_id:
            raise NotFound("HARNESS_PREPARATION_NOT_FOUND", "准备单不存在")
        return await self._preparation_view(ctx, preparation)

    async def list_preparations(self, ctx: RequestContext, status: str | None = None) -> list[dict]:
        stmt = select(HarnessPreparation).where(HarnessPreparation.project_id == ctx.project_id)
        if status:
            stmt = stmt.where(HarnessPreparation.status == status)
        rows = (await self.session.execute(stmt.order_by(HarnessPreparation.created_at.desc()).limit(50))).scalars()
        return [await self._preparation_view(ctx, p) for p in rows]

    # ---------- Approve ----------
    async def approve(
        self, ctx: RequestContext, preparation_id: uuid.UUID, slot_code: str, decision: str, comment: str
    ) -> dict:
        preparation = await self.session.get(HarnessPreparation, preparation_id)
        if preparation is None or preparation.project_id != ctx.project_id:
            raise NotFound("HARNESS_PREPARATION_NOT_FOUND", "准备单不存在")
        if preparation.status not in ("PENDING_APPROVAL",):
            raise Conflict("HARNESS_PREPARATION_NOT_PENDING", f"准备单当前状态为 {preparation.status}，不可审批")

        # 四眼原则：申请人不得自批
        if preparation.created_by_user_id == ctx.user_id:
            raise Forbidden("HARNESS_SELF_APPROVAL_FORBIDDEN", "申请人不得审批自己提交的准备单")

        slot = (
            await self.session.execute(
                select(HarnessApprovalSlot).where(
                    HarnessApprovalSlot.preparation_id == preparation.id,
                    HarnessApprovalSlot.slot_code == slot_code,
                )
            )
        ).scalar_one_or_none()
        if slot is None:
            raise NotFound("HARNESS_SLOT_NOT_FOUND", f"准备单没有 {slot_code} 审批槽")
        if slot.assignee_user_id != ctx.user_id:
            raise Forbidden("HARNESS_NOT_ASSIGNEE", "你不是该审批槽的指定审批人")
        if slot.status != "PENDING":
            raise Conflict("HARNESS_SLOT_DECIDED", "该审批槽已作出决定")

        key = await get_signing_key(self.session)
        decision_row = HarnessApprovalDecision(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            approval_slot_id=slot.id,
            preparation_id=preparation.id,
            approver_user_id=ctx.user_id,
            decision="APPROVE" if decision.upper() == "APPROVE" else "REJECT",
            comment=comment or "",
            preparation_sha256=preparation.snapshot_sha256,
            signature=crypto_sign(key.private_key, f"{preparation.snapshot_sha256}:{ctx.user_id}:{decision}"),
            decided_at=datetime.now(UTC),
        )
        self.session.add(decision_row)
        slot.status = "APPROVED" if decision.upper() == "APPROVE" else "REJECTED"

        slots = (
            await self.session.execute(
                select(HarnessApprovalSlot).where(HarnessApprovalSlot.preparation_id == preparation.id)
            )
        ).scalars().all()
        if any(s.status == "REJECTED" for s in slots):
            preparation.status = "REJECTED"
        elif all(s.status == "APPROVED" for s in slots):
            preparation.status = "APPROVED"

        await append_evidence(
            self.session,
            ctx,
            "APPROVAL_DECISION",
            preparation.snapshot_sha256,
            {"preparation_id": str(preparation.id), "slot": slot_code, "decision": decision_row.decision},
        )
        await self.session.commit()
        return await self._preparation_view(ctx, preparation)

    # ---------- Commit ----------
    async def commit(self, ctx: RequestContext, preparation_id: uuid.UUID) -> dict:
        preparation = await self.session.get(HarnessPreparation, preparation_id)
        if preparation is None or preparation.project_id != ctx.project_id:
            raise NotFound("HARNESS_PREPARATION_NOT_FOUND", "准备单不存在")
        if preparation.status != "APPROVED":
            raise Conflict("HARNESS_NOT_APPROVED", f"准备单状态为 {preparation.status}，不能 Commit")

        # Commit 前重新校验冻结事实，防止审批后被替换
        version = await self.session.get(PipeVersion, preparation.pipeline_version_id)
        if version.sha256 != preparation.snapshot["version_sha256"]:
            raise Conflict("HARNESS_FINGERPRINT_CHANGED", "制品指纹与准备单不一致，请重新 Prepare")

        existing_commit = (
            await self.session.execute(
                select(HarnessCommit).where(HarnessCommit.preparation_id == preparation.id)
            )
        ).scalar_one_or_none()
        if existing_commit is not None:
            raise Conflict("HARNESS_ALREADY_COMMITTED", "该准备单已 Commit")

        key = await get_signing_key(self.session)
        commit_sha = sha256_hex(
            {
                "preparation": preparation.snapshot_sha256,
                "version": version.sha256,
                "operator": str(ctx.user_id),
            }
        )
        commit = HarnessCommit(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            preparation_id=preparation.id,
            operator_user_id=ctx.user_id,
            approved_snapshot_sha256=preparation.snapshot_sha256,
            commit_sha256=commit_sha,
            committed_at=datetime.now(UTC),
        )
        self.session.add(commit)
        await self.session.flush()

        now = datetime.now(UTC)
        jti = uuid.uuid4().hex
        claims = {
            "jti": jti,
            "tool": TOOL_NAME,
            "sub": str(ctx.user_id),
            "env": preparation.snapshot["environment"],
            "artifact": version.sha256,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=CAPABILITY_TTL_SECONDS)).timestamp()),
        }
        token_body = canonical_json(claims)
        token = f"{token_body}|{crypto_sign(key.private_key, token_body)}"

        capability = HarnessCapability(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            commit_id=commit.id,
            jti=jti,
            tool_name=TOOL_NAME,
            subject_id=ctx.user_id,
            environment=preparation.snapshot["environment"],
            artifact_sha256=version.sha256,
            issued_at=now,
            expires_at=now + timedelta(seconds=CAPABILITY_TTL_SECONDS),
            token_sha256=sha256_hex(token),
            signature=crypto_sign(key.private_key, jti),
        )
        self.session.add(capability)
        await self.session.flush()

        run = ExecRun(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            commit_id=commit.id,
            pipeline_version_id=version.id,
            preparation_id=preparation.id,
            artifact_sha256=version.sha256,
            task_id=f"task-{uuid.uuid4().hex[:12]}",
            status="PENDING",
        )
        self.session.add(run)
        await self.session.flush()  # 先落库拿到 exec_run.id，Outbox 载荷要用

        outbox = HarnessOutboxEvent(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            aggregate_id=run.id,
            event_type="EXECUTION_REQUESTED",
            payload={"exec_run_id": str(run.id), "capability_jti": jti},
            payload_sha256=sha256_hex({"exec_run_id": str(run.id), "capability_jti": jti}),
            status="PENDING",
        )
        self.session.add(outbox)
        preparation.status = "COMMITTED"

        await append_evidence(
            self.session,
            ctx,
            "COMMIT",
            commit_sha,
            {"preparation_id": str(preparation.id), "capability_jti": jti},
        )
        await self.session.commit()

        return {
            "commit_id": str(commit.id),
            "commit_sha256": commit_sha,
            "capability": {
                "jti": jti,
                "token": token,
                "expires_at": capability.expires_at.isoformat(),
                "tool_name": TOOL_NAME,
                "artifact_sha256": version.sha256,
            },
            "exec_run_id": str(run.id),
            "outbox_event_id": str(outbox.id),
        }

    # ---------- Replay Guard ----------
    async def verify_and_consume(self, ctx: RequestContext, token: str, consumer_id: str) -> HarnessCapability:
        body, _, signature = token.partition("|")
        key = await get_signing_key(self.session)
        if not crypto_verify(key.public_key, body, signature):
            raise Forbidden("HARNESS_CAPABILITY_BAD_SIGNATURE", "Capability 签名校验失败")

        token_sha = sha256_hex(token)
        capability = (
            await self.session.execute(
                select(HarnessCapability).where(HarnessCapability.token_sha256 == token_sha)
            )
        ).scalar_one_or_none()
        if capability is None:
            raise Forbidden("HARNESS_CAPABILITY_UNKNOWN", "Capability 不存在")
        if as_utc(capability.expires_at) <= datetime.now(UTC):
            raise Forbidden("HARNESS_CAPABILITY_EXPIRED", "Capability 已过期")
        if capability.environment and capability.project_id != ctx.project_id:
            raise Forbidden("HARNESS_CAPABILITY_WRONG_SCOPE", "Capability 与当前项目不匹配")

        consumed = (
            await self.session.execute(
                select(HarnessCapabilityConsumption).where(
                    HarnessCapabilityConsumption.capability_id == capability.id
                )
            )
        ).scalar_one_or_none()
        if consumed is not None:
            raise Conflict("HARNESS_REPLAY_DETECTED", "该 Capability 已被消费，拒绝重放")

        self.session.add(
            HarnessCapabilityConsumption(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                capability_id=capability.id,
                consumer_id=consumer_id,
                request_sha256=sha256_hex(body),
                consumed_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        return capability

    # ---------- 证据链 ----------
    async def verify_chain(self, ctx: RequestContext) -> dict:
        chain_id = f"project:{ctx.project_id}"
        records = (
            await self.session.execute(
                select(HarnessEvidenceRecord)
                .where(HarnessEvidenceRecord.chain_id == chain_id)
                .order_by(HarnessEvidenceRecord.sequence_no)
            )
        ).scalars().all()
        key = await get_signing_key(self.session)
        problems = []
        prev = ""
        for record in records:
            body = {
                "chain_id": record.chain_id,
                "sequence_no": record.sequence_no,
                "actor": record.actor,
                "event_type": record.event_type,
                "artifact_sha256": record.artifact_sha256,
                "payload": record.payload,
                "prev_hash": record.prev_hash,
            }
            if sha256_hex(body) != record.record_hash:
                problems.append({"sequence_no": record.sequence_no, "issue": "HASH_MISMATCH"})
            if record.prev_hash != prev:
                problems.append({"sequence_no": record.sequence_no, "issue": "CHAIN_BROKEN"})
            if not crypto_verify(key.public_key, record.record_hash, record.signature):
                problems.append({"sequence_no": record.sequence_no, "issue": "BAD_SIGNATURE"})
            prev = record.record_hash
        return {
            "chain_id": chain_id,
            "length": len(records),
            "intact": not problems,
            "problems": problems,
            "records": [
                {
                    "sequence_no": r.sequence_no,
                    "event_type": r.event_type,
                    "artifact_sha256": r.artifact_sha256,
                    "actor": r.actor,
                    "prev_hash": r.prev_hash,
                    "record_hash": r.record_hash,
                    "signature": r.signature[:24] + "…",
                    "created_at": r.created_at.isoformat(),
                    "payload": r.payload,
                }
                for r in records
            ],
        }

    async def verify_version(self, ctx: RequestContext, version_id: uuid.UUID) -> dict:
        pipe = PipeService(self.session)
        detail = await pipe.get_version(ctx, version_id)
        recomputed = sha256_hex(
            {
                "components": {c["type"]: c["sha256"] for c in detail["components"]},
                "source": (
                    await self.session.get(PipeVersion, version_id)
                ).sha256,
            }
        )
        return {
            "version_id": str(version_id),
            "stored_sha256": detail["sha256"],
            "recomputed_sha256": recomputed,
            "components_intact": all(
                sha256_hex(c["content"]) == c["sha256"] for c in detail["components"]
            ),
        }
