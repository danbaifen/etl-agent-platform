from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import as_utc
from app.core.context import RequestContext
from app.core.crypto import sha256_hex
from app.core.errors import AppError, Conflict, NotFound
from app.modules.asset.models import AssetConnection
from app.modules.exec.models import (
    ExecAttempt,
    ExecDiagnosis,
    ExecErrorCodeStat,
    ExecFailureSnapshot,
    ExecMetricSample,
    ExecPublication,
    ExecQualityReport,
    ExecRollbackAction,
    ExecRun,
    ExecSupervisionEvent,
    ExecSwapAction,
)
from app.modules.harness.models import (
    HarnessBudgetContract,
    HarnessCapability,
    HarnessCapabilityConsumption,
    HarnessOutboxEvent,
    HarnessPreparation,
)
from app.modules.harness.service import append_evidence, get_signing_key
from app.modules.meta.service import mask
from app.modules.pipe.models import PipeVersion, PipeVersionComponent

UTC = timezone.utc
ERROR_TABLE_SUFFIX = "__err"
SHADOW_SUFFIX = "__shadow"
BACKUP_SUFFIX = "__bak"
SQLITE_TYPES = {"NUMERIC": "REAL", "TEMPORAL": "TEXT", "BOOLEAN": "INTEGER", "TEXT": "TEXT"}


def _sqlite_type(data_type: str) -> str:
    upper = (data_type or "").upper()
    if any(token in upper for token in ("INT", "BIGINT")):
        return "INTEGER"
    if any(token in upper for token in ("REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC")):
        return "REAL"
    return "TEXT"


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _execute_job(
    source_path: str, target_path: str, plan: dict, max_reject_rate: float
) -> dict:
    """真实执行：读源表 → 质量规则分流 → 写影子表与错误表。

    这是数据面动作，跑在 SQLite 上（SeaTunnel 未接入时的本地执行器），
    因此行数、字节数、拒绝率都是实测值，不是编的。
    """
    mappings = plan["transform"]["mappings"]
    source_object = plan["source"]["object"]
    target_object = plan["target"]["object"]
    primary_key = plan["target"]["primary_key"]
    rules = plan["quality_contract"]["rules"]
    rule_by_field: dict[str, list[dict]] = {}
    for rule in rules:
        rule_by_field.setdefault(rule["field"], []).append(rule)

    shadow = f"{target_object}{SHADOW_SUFFIX}"
    error_table = f"{target_object}{ERROR_TABLE_SUFFIX}"

    src = _connect(source_path)
    tgt = _connect(target_path)
    try:
        rows = [dict(r) for r in src.execute(f'SELECT * FROM "{source_object}"').fetchall()]
        read_rows = len(rows)

        columns_ddl = ", ".join(f'"{m["target"]}" {_sqlite_type(m["target_type"])}' for m in mappings)
        tgt.execute(f'DROP TABLE IF EXISTS "{shadow}"')
        tgt.execute(f'CREATE TABLE "{shadow}" ({columns_ddl})')
        tgt.execute(f'DROP TABLE IF EXISTS "{error_table}"')
        tgt.execute(
            f'CREATE TABLE "{error_table}" (error_code TEXT, field TEXT, raw_value TEXT, reason TEXT)'
        )

        valid: list[tuple] = []
        errors: list[tuple] = []
        error_stats: dict[str, int] = {}
        samples: dict[str, str] = {}

        for row in rows:
            # 一行只产生一条错误表记录：多个规则同时命中时取第一条作为错误码，
            # 其余命中计入 ErrorCode 分布，避免同一行把拒绝率算成倍数。
            violations: list[tuple[str, str, object, str]] = []
            pk_value = row.get(primary_key)
            if pk_value is None or str(pk_value).strip() == "":
                violations.append(("PK_NULL", primary_key, pk_value, "主键为空"))
            else:
                for mapping in mappings:
                    target_field = mapping["target"]
                    value = row.get(mapping["source"])
                    for rule in rule_by_field.get(target_field, []):
                        if rule["rule"] == "not_null" and (value is None or str(value).strip() == ""):
                            violations.append(
                                (f"NULL_{target_field.upper()}", target_field, value, "非空校验失败")
                            )
                        elif rule["rule"] == "numeric":
                            try:
                                float(value)
                            except (TypeError, ValueError):
                                violations.append(
                                    (
                                        f"TYPE_MISMATCH_{target_field.upper()}",
                                        target_field,
                                        value,
                                        "数值解析失败",
                                    )
                                )
            if violations:
                code, field, raw, reason = violations[0]
                errors.append((code, field, str(raw)[:120], reason))
                for violation in violations:
                    error_stats[violation[0]] = error_stats.get(violation[0], 0) + 1
                samples.setdefault(code, f"{field}={str(raw)[:40]}")
                continue

            payload = []
            for mapping in mappings:
                value = row.get(mapping["source"])
                if mapping.get("mask_policy"):
                    value = mask(value, mapping["mask_policy"])
                payload.append(value)
            valid.append(tuple(payload))

        if valid:
            placeholders = ", ".join("?" for _ in mappings)
            tgt.executemany(f'INSERT INTO "{shadow}" VALUES ({placeholders})', valid)
        if errors:
            tgt.executemany(f'INSERT INTO "{error_table}" VALUES (?, ?, ?, ?)', errors)
        tgt.commit()

        written_bytes = sum(len(str(v)) for row in valid for v in row)
        reject_rate = (len(errors) / read_rows) if read_rows else 0.0
        return {
            "read_rows": read_rows,
            "valid_rows": len(valid),
            "rejected_rows": len(errors),
            "written_bytes": written_bytes,
            "reject_rate": round(reject_rate, 4),
            "error_stats": error_stats,
            "error_samples": samples,
            "shadow": shadow,
            "error_table": error_table,
            "aborted": reject_rate > max_reject_rate,
        }
    finally:
        src.close()
        tgt.close()


def _swap(target_path: str, target_object: str, shadow: str) -> dict:
    """原子 Swap：正式表先改名留底，影子表顶上；失败则回退。"""
    conn = _connect(target_path)
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (target_object,)
        ).fetchone()
        backup = f"{target_object}{BACKUP_SUFFIX}"
        if exists:
            conn.execute(f'DROP TABLE IF EXISTS "{backup}"')
            conn.execute(f'ALTER TABLE "{target_object}" RENAME TO "{backup}"')
        conn.execute(f'ALTER TABLE "{shadow}" RENAME TO "{target_object}"')
        conn.commit()
        return {"swapped": True, "backup": backup if exists else "", "formal": target_object}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _rollback_shadow(target_path: str, target_object: str) -> dict:
    conn = _connect(target_path)
    try:
        dropped = []
        for suffix in (SHADOW_SUFFIX, ERROR_TABLE_SUFFIX):
            name = f"{target_object}{suffix}"
            conn.execute(f'DROP TABLE IF EXISTS "{name}"')
            dropped.append(name)
        backup = f"{target_object}{BACKUP_SUFFIX}"
        has_backup = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (backup,)
        ).fetchone()
        if has_backup:
            conn.execute(f'DROP TABLE IF EXISTS "{target_object}"')
            conn.execute(f'ALTER TABLE "{backup}" RENAME TO "{target_object}"')
            dropped.append(f"restored:{target_object}")
        conn.commit()
        return {"dropped": dropped}
    finally:
        conn.close()


class ExecService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _run(self, ctx: RequestContext, run_id: uuid.UUID) -> ExecRun:
        run = await self.session.get(ExecRun, run_id)
        if run is None or run.project_id != ctx.project_id:
            raise NotFound("EXEC_RUN_NOT_FOUND", "执行记录不存在")
        return run

    async def _plan(self, version_id: uuid.UUID) -> dict:
        component = (
            await self.session.execute(
                select(PipeVersionComponent).where(
                    PipeVersionComponent.pipeline_version_id == version_id,
                    PipeVersionComponent.component_type == "ETL_PLAN",
                )
            )
        ).scalar_one_or_none()
        if component is None:
            raise AppError("EXEC_PLAN_MISSING", "版本缺少 ETL_PLAN 组件", 422)
        return component.content

    async def start(self, ctx: RequestContext, run_id: uuid.UUID) -> dict:
        run = await self._run(ctx, run_id)
        if run.status != "PENDING":
            raise Conflict("EXEC_RUN_NOT_PENDING", f"执行记录状态为 {run.status}")

        capability = (
            await self.session.execute(
                select(HarnessCapability)
                .where(HarnessCapability.commit_id == run.commit_id)
                .order_by(HarnessCapability.issued_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if capability is None:
            raise AppError("EXEC_CAPABILITY_MISSING", "找不到该 Commit 对应的 Capability", 409)
        if as_utc(capability.expires_at) <= datetime.now(UTC):
            raise AppError("EXEC_CAPABILITY_EXPIRED", "Capability 已过期，请重新 Commit", 409)

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
                consumer_id="local-worker",
                request_sha256=sha256_hex({"run": str(run.id), "jti": capability.jti}),
                consumed_at=datetime.now(UTC),
            )
        )
        outbox = (
            await self.session.execute(
                select(HarnessOutboxEvent).where(HarnessOutboxEvent.aggregate_id == run.id)
            )
        ).scalar_one_or_none()
        if outbox is not None:
            outbox.status = "DISPATCHED"
            outbox.attempt_count += 1

        plan = await self._plan(run.pipeline_version_id)
        preparation = await self.session.get(HarnessPreparation, run.preparation_id)
        budget = (
            await self.session.execute(
                select(HarnessBudgetContract).where(
                    HarnessBudgetContract.preparation_id == run.preparation_id
                )
            )
        ).scalar_one()

        source_conn = await self.session.get(
            AssetConnection, uuid.UUID(str(plan["source"]["connection_id"]))
        )
        target_conn = await self.session.get(
            AssetConnection, uuid.UUID(str(plan["target"]["connection_id"]))
        )
        source_path = (source_conn.safe_config or {})["database_path"]
        target_path = (target_conn.safe_config or {})["database_path"]

        started = datetime.now(UTC)
        run.status = "RUNNING"
        run.started_at = started
        attempt = ExecAttempt(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            execution_run_id=run.id,
            attempt_no=1,
            worker_id="local-worker",
            seatunnel_job_id=f"zeta-local-{uuid.uuid4().hex[:8]}",
            status="RUNNING",
            started_at=started,
        )
        self.session.add(attempt)
        await append_evidence(
            self.session, ctx, "EXECUTION_STARTED", run.artifact_sha256, {"run_id": str(run.id)}
        )
        await self.session.commit()

        clock = time.perf_counter()
        result = await asyncio.to_thread(
            _execute_job, source_path, target_path, plan, budget.max_reject_rate
        )
        elapsed_ms = int((time.perf_counter() - clock) * 1000)

        run.read_rows = result["read_rows"]
        run.written_rows = result["valid_rows"]
        run.written_bytes = result["written_bytes"]
        run.reject_rows = result["rejected_rows"]
        run.throughput = round(result["valid_rows"] / max(elapsed_ms / 1000, 0.001), 2)

        for index in range(1, 5):
            ratio = index / 4
            self.session.add(
                ExecMetricSample(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    execution_run_id=run.id,
                    captured_at=started,
                    read_rows=int(result["read_rows"] * ratio),
                    write_bytes=int(result["written_bytes"] * ratio),
                    throughput=run.throughput,
                    amplification=round(
                        (result["written_bytes"] or 1) / max(result["read_rows"] or 1, 1), 4
                    ),
                    reject_rate=result["reject_rate"],
                )
            )

        supervision_events = []
        aborted = False
        abort_reason = None

        checks = [
            ("READ_ROWS", result["read_rows"], budget.max_read_rows),
            ("WRITE_BYTES", result["written_bytes"], budget.max_write_bytes),
            ("DURATION_MS", elapsed_ms, budget.max_duration_ms),
            ("REJECT_RATE", result["reject_rate"], budget.max_reject_rate),
        ]
        for metric, actual, limit in checks:
            if actual > limit:
                aborted = True
                abort_reason = metric
                self.session.add(
                    ExecSupervisionEvent(
                        tenant_id=ctx.tenant_id,
                        project_id=ctx.project_id,
                        execution_run_id=run.id,
                        metric_type=metric,
                        actual_value=float(actual),
                        budget_value=float(limit),
                        action="HARD_ABORT",
                        message=f"{metric} 超预算：实际 {actual} / 上限 {limit}",
                        captured_at=datetime.now(UTC),
                    )
                )
                supervision_events.append({"metric": metric, "actual": actual, "budget": limit})
            elif actual > limit * 0.8:
                self.session.add(
                    ExecSupervisionEvent(
                        tenant_id=ctx.tenant_id,
                        project_id=ctx.project_id,
                        execution_run_id=run.id,
                        metric_type=metric,
                        actual_value=float(actual),
                        budget_value=float(limit),
                        action="WARN",
                        message=f"{metric} 接近预算：实际 {actual} / 上限 {limit}",
                        captured_at=datetime.now(UTC),
                    )
                )

        quality = ExecQualityReport(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            execution_run_id=run.id,
            rule_sha256=sha256_hex(plan["quality_contract"]),
            status="FAILED" if aborted else "PASSED",
            valid_rows=result["valid_rows"],
            rejected_rows=result["rejected_rows"],
            reject_rate=result["reject_rate"],
            supervision_decision="HARD_ABORT" if aborted else "PASS",
            swapped=False,
        )
        self.session.add(quality)
        await self.session.flush()

        for code, count in result["error_stats"].items():
            self.session.add(
                ExecErrorCodeStat(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    quality_report_id=quality.id,
                    error_code=code,
                    count=count,
                    sample_summary=result["error_samples"].get(code, ""),
                )
            )

        publication = ExecPublication(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            execution_run_id=run.id,
            target_resource=plan["target"]["object"],
            shadow_resource=result["shadow"],
            formal_resource=plan["target"]["object"],
            status="PENDING",
        )
        self.session.add(publication)
        await self.session.flush()

        if aborted:
            snapshot_body = {
                "run_id": str(run.id),
                "metric": abort_reason,
                "reject_rate": result["reject_rate"],
                "error_stats": result["error_stats"],
            }
            failure = ExecFailureSnapshot(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                execution_run_id=run.id,
                attempt_id=attempt.id,
                error_code=f"SUPERVISION_{abort_reason}",
                safe_stack_digest=sha256_hex(snapshot_body),
                snapshot={
                    "metric": abort_reason,
                    "reject_rate": result["reject_rate"],
                    "error_stats": result["error_stats"],
                    "error_samples": result["error_samples"],
                },
            )
            self.session.add(failure)
            await self.session.flush()

            dominant = max(result["error_stats"], key=result["error_stats"].get) if result["error_stats"] else "UNKNOWN"
            diagnosis_text, recommendation = self._diagnose(dominant, result)
            self.session.add(
                ExecDiagnosis(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    execution_run_id=run.id,
                    failure_snapshot_id=failure.id,
                    root_cause=diagnosis_text,
                    evidence_refs=[f"quality_report:{quality.id}", f"supervision:{abort_reason}"],
                    recommendation=recommendation,
                )
            )
            run.status = "ABORTED"
            run.abort_reason = f"{abort_reason} 超预算"
            publication.status = "SKIPPED"
            attempt.status = "ABORTED"
            attempt.ended_at = datetime.now(UTC)
            await append_evidence(
                self.session,
                ctx,
                "EXECUTION_ABORTED",
                run.artifact_sha256,
                {"run_id": str(run.id), "metric": abort_reason, "reject_rate": result["reject_rate"]},
            )
        else:
            swap = await asyncio.to_thread(_swap, target_path, plan["target"]["object"], result["shadow"])
            self.session.add(
                ExecSwapAction(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    publication_id=publication.id,
                    pre_swap_ref=swap["backup"],
                    result="SUCCESS",
                    performed_at=datetime.now(UTC),
                )
            )
            publication.status = "PUBLISHED"
            quality.swapped = True
            run.status = "SUCCEEDED"
            attempt.status = "SUCCEEDED"
            attempt.ended_at = datetime.now(UTC)
            await append_evidence(
                self.session,
                ctx,
                "ATOMIC_SWAP",
                run.artifact_sha256,
                {"run_id": str(run.id), "formal": plan["target"]["object"]},
            )

        run.ended_at = datetime.now(UTC)
        await append_evidence(
            self.session,
            ctx,
            "EXECUTION_FINISHED",
            run.artifact_sha256,
            {
                "run_id": str(run.id),
                "status": run.status,
                "valid_rows": result["valid_rows"],
                "rejected_rows": result["rejected_rows"],
            },
        )
        await self.session.commit()

        return await self.get(ctx, run.id)

    @staticmethod
    def _diagnose(dominant_code: str, result: dict) -> tuple[str, str]:
        if dominant_code.startswith("TYPE_MISMATCH"):
            field = dominant_code.replace("TYPE_MISMATCH_", "").lower()
            return (
                f"字段 {field} 类型解析失败是主要分流原因：源端该列在本次批次中出现非数值内容，"
                "通常由源系统格式变更或多个业务口径混写引起。",
                "核对源表该列定义与实际值分布；在上游补类型约束，或在本平台质量契约中增加显式类型转换规则后再提交新版本。",
            )
        if dominant_code.startswith("NULL_"):
            field = dominant_code.replace("NULL_", "").lower()
            return (
                f"字段 {field} 存在空值，违反非空约束。",
                f"确认 {field} 在源端是否可空；若业务允许空，应在新版本的质量契约中调整该字段规则。",
            )
        if dominant_code == "PK_NULL":
            return (
                "主键为空导致整行无法去重，属阻断性数据问题。",
                "在源端补齐主键，或在生成阶段改用其他业务唯一键作为主键。",
            )
        return (
            f"质量契约未通过，主要错误码为 {dominant_code}，拒绝率 {result['reject_rate']:.2%} 超过预算。",
            "按错误码分布逐项核对质量规则与源数据；确认规则过严时调整质量契约并重新走审批。",
        )

    async def get(self, ctx: RequestContext, run_id: uuid.UUID) -> dict:
        run = await self._run(ctx, run_id)
        quality = (
            await self.session.execute(
                select(ExecQualityReport).where(ExecQualityReport.execution_run_id == run.id)
            )
        ).scalar_one_or_none()
        stats = (
            await self.session.execute(
                select(ExecErrorCodeStat).where(ExecErrorCodeStat.quality_report_id == quality.id)
            )
        ).scalars().all() if quality else []
        events = (
            await self.session.execute(
                select(ExecSupervisionEvent).where(ExecSupervisionEvent.execution_run_id == run.id)
            )
        ).scalars().all()
        samples = (
            await self.session.execute(
                select(ExecMetricSample)
                .where(ExecMetricSample.execution_run_id == run.id)
                .order_by(ExecMetricSample.captured_at)
            )
        ).scalars().all()
        failure = (
            await self.session.execute(
                select(ExecFailureSnapshot).where(ExecFailureSnapshot.execution_run_id == run.id)
            )
        ).scalar_one_or_none()
        diagnosis = (
            await self.session.execute(
                select(ExecDiagnosis).where(ExecDiagnosis.execution_run_id == run.id)
            )
        ).scalar_one_or_none()
        publication = (
            await self.session.execute(
                select(ExecPublication).where(ExecPublication.execution_run_id == run.id)
            )
        ).scalar_one_or_none()
        rollback = (
            await self.session.execute(
                select(ExecRollbackAction)
                .where(ExecRollbackAction.execution_run_id == run.id)
                .order_by(ExecRollbackAction.performed_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        return {
            "id": str(run.id),
            "task_id": run.task_id,
            "status": run.status,
            "artifact_sha256": run.artifact_sha256,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "ended_at": run.ended_at.isoformat() if run.ended_at else None,
            "read_rows": run.read_rows,
            "written_rows": run.written_rows,
            "written_bytes": run.written_bytes,
            "reject_rows": run.reject_rows,
            "throughput": run.throughput,
            "abort_reason": run.abort_reason,
            "metrics": [
                {
                    "captured_at": m.captured_at.isoformat(),
                    "read_rows": m.read_rows,
                    "write_bytes": m.write_bytes,
                    "throughput": m.throughput,
                    "reject_rate": m.reject_rate,
                }
                for m in samples
            ],
            "supervision_events": [
                {
                    "metric": e.metric_type,
                    "actual": e.actual_value,
                    "budget": e.budget_value,
                    "action": e.action,
                    "message": e.message,
                }
                for e in events
            ],
            "quality_report": (
                {
                    "status": quality.status,
                    "valid_rows": quality.valid_rows,
                    "rejected_rows": quality.rejected_rows,
                    "reject_rate": quality.reject_rate,
                    "supervision_decision": quality.supervision_decision,
                    "swapped": quality.swapped,
                    "rule_sha256": quality.rule_sha256,
                    "error_codes": [
                        {"code": s.error_code, "count": s.count, "sample": s.sample_summary} for s in stats
                    ],
                }
                if quality
                else None
            ),
            "failure": (
                {"error_code": failure.error_code, "digest": failure.safe_stack_digest, "snapshot": failure.snapshot}
                if failure
                else None
            ),
            "diagnosis": (
                {
                    "root_cause": diagnosis.root_cause,
                    "recommendation": diagnosis.recommendation,
                    "evidence_refs": diagnosis.evidence_refs,
                }
                if diagnosis
                else None
            ),
            "publication": (
                {
                    "status": publication.status,
                    "shadow": publication.shadow_resource,
                    "formal": publication.formal_resource,
                }
                if publication
                else None
            ),
            "rollback": (
                {"scope": rollback.scope, "result": rollback.result, "reason": rollback.reason}
                if rollback
                else None
            ),
        }

    async def list_runs(self, ctx: RequestContext) -> list[dict]:
        rows = (
            await self.session.execute(
                select(ExecRun).where(ExecRun.project_id == ctx.project_id).order_by(ExecRun.created_at.desc()).limit(50)
            )
        ).scalars()
        return [
            {
                "id": str(r.id),
                "task_id": r.task_id,
                "status": r.status,
                "artifact_sha256": r.artifact_sha256,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "ended_at": r.ended_at.isoformat() if r.ended_at else None,
                "read_rows": r.read_rows,
                "written_rows": r.written_rows,
                "written_bytes": r.written_bytes,
                "reject_rows": r.reject_rows,
                "throughput": r.throughput,
            }
            for r in rows
        ]

    async def rollback(self, ctx: RequestContext, run_id: uuid.UUID, reason: str) -> dict:
        run = await self._run(ctx, run_id)
        if run.status in ("PENDING", "RUNNING"):
            raise Conflict("EXEC_RUN_IN_FLIGHT", "执行尚未结束，不能回滚")

        plan = await self._plan(run.pipeline_version_id)
        target_conn = await self.session.get(
            AssetConnection, uuid.UUID(str(plan["target"]["connection_id"]))
        )
        target_path = (target_conn.safe_config or {})["database_path"]
        result = await asyncio.to_thread(_rollback_shadow, target_path, plan["target"]["object"])

        self.session.add(
            ExecRollbackAction(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                execution_run_id=run.id,
                operator_user_id=ctx.user_id,
                scope="SHADOW_ONLY" if run.status != "SUCCEEDED" else "SWAP_REVERT",
                reason=reason,
                result="SUCCESS",
                performed_at=datetime.now(UTC),
            )
        )
        publication = (
            await self.session.execute(
                select(ExecPublication).where(ExecPublication.execution_run_id == run.id)
            )
        ).scalar_one_or_none()
        if publication is not None:
            publication.status = "ROLLED_BACK"
        run.status = "ROLLED_BACK"
        await append_evidence(
            self.session,
            ctx,
            "ROLLBACK",
            run.artifact_sha256,
            {"run_id": str(run.id), "reason": reason, "dropped": result["dropped"]},
        )
        await self.session.commit()
        return {"run_id": str(run.id), "status": run.status, "dropped": result["dropped"]}
