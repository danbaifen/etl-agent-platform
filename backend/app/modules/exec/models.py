from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Scoped, fk


class ExecRun(Scoped):
    __tablename__ = "exec_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','ABORTED','ROLLED_BACK','CANCELLED')",
            name="ck_exec_run_status",
        ),
    )

    commit_id: Mapped[uuid.UUID] = fk("harness_commit.id")
    pipeline_version_id: Mapped[uuid.UUID] = fk("pipe_version.id")
    preparation_id: Mapped[uuid.UUID] = fk("harness_preparation.id")
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    written_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    written_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reject_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    throughput: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    abort_reason: Mapped[str | None] = mapped_column(Text)


class ExecAttempt(Scoped):
    __tablename__ = "exec_attempt"

    execution_run_id: Mapped[uuid.UUID] = fk("exec_run.id")
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    worker_id: Mapped[str] = mapped_column(String(64), nullable=False, default="local-worker")
    seatunnel_job_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecMetricSample(Scoped):
    __tablename__ = "exec_metric_sample"

    execution_run_id: Mapped[uuid.UUID] = fk("exec_run.id")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    write_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    throughput: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    amplification: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    reject_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class ExecSupervisionEvent(Scoped):
    __tablename__ = "exec_supervision_event"

    execution_run_id: Mapped[uuid.UUID] = fk("exec_run.id")
    metric_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actual_value: Mapped[float] = mapped_column(Float, nullable=False)
    budget_value: Mapped[float] = mapped_column(Float, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecFailureSnapshot(Scoped):
    __tablename__ = "exec_failure_snapshot"

    execution_run_id: Mapped[uuid.UUID] = fk("exec_run.id")
    attempt_id: Mapped[uuid.UUID | None] = fk("exec_attempt.id", nullable=True)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_stack_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ExecDiagnosis(Scoped):
    __tablename__ = "exec_diagnosis"

    execution_run_id: Mapped[uuid.UUID] = fk("exec_run.id")
    failure_snapshot_id: Mapped[uuid.UUID] = fk("exec_failure_snapshot.id")
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ExecQualityReport(Scoped):
    __tablename__ = "exec_quality_report"

    execution_run_id: Mapped[uuid.UUID] = fk("exec_run.id")
    rule_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    valid_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rejected_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reject_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    supervision_decision: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    swapped: Mapped[bool] = mapped_column(default=False, nullable=False)


class ExecErrorCodeStat(Scoped):
    __tablename__ = "exec_error_code_stat"

    quality_report_id: Mapped[uuid.UUID] = fk("exec_quality_report.id")
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_summary: Mapped[str] = mapped_column(String(256), nullable=False, default="")


class ExecPublication(Scoped):
    __tablename__ = "exec_publication"

    execution_run_id: Mapped[uuid.UUID] = fk("exec_run.id")
    target_resource: Mapped[str] = mapped_column(String(256), nullable=False)
    shadow_resource: Mapped[str] = mapped_column(String(256), nullable=False)
    formal_resource: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")


class ExecSwapAction(Scoped):
    __tablename__ = "exec_swap_action"

    publication_id: Mapped[uuid.UUID] = fk("exec_publication.id")
    pre_swap_ref: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecRollbackAction(Scoped):
    __tablename__ = "exec_rollback_action"

    execution_run_id: Mapped[uuid.UUID] = fk("exec_run.id")
    operator_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="SHADOW_ONLY")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="SUCCESS")
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
