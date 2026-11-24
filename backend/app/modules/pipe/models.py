from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Scoped, fk


class PipePipeline(Scoped):
    __tablename__ = "pipe_pipeline"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_pipe_pipeline_name"),
        CheckConstraint("status IN ('DRAFT','ACTIVE','ARCHIVED')", name="ck_pipe_pipeline_status"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")


class PipeVersion(Scoped):
    __tablename__ = "pipe_version"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "version_no", name="uq_pipe_version_no"),
        CheckConstraint("status IN ('FROZEN','PUBLISHED','SUPERSEDED')", name="ck_pipe_version_status"),
    )

    pipeline_id: Mapped[uuid.UUID] = fk("pipe_pipeline.id")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_candidate_id: Mapped[uuid.UUID] = fk("gen_candidate.id")
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frozen_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="FROZEN")
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class PipeVersionComponent(Scoped):
    __tablename__ = "pipe_version_component"
    __table_args__ = (
        UniqueConstraint("pipeline_version_id", "component_type", name="uq_pipe_component_type"),
    )

    pipeline_version_id: Mapped[uuid.UUID] = fk("pipe_version.id")
    component_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class PipeGateRun(Scoped):
    __tablename__ = "pipe_gate_run"
    __table_args__ = (
        CheckConstraint("status IN ('PASSED','BLOCKED')", name="ck_pipe_gate_status"),
    )

    pipeline_version_id: Mapped[uuid.UUID] = fk("pipe_version.id")
    gate_version: Mapped[str] = mapped_column(String(16), nullable=False, default="gate-1")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PipeGateFinding(Scoped):
    __tablename__ = "pipe_gate_finding"

    gate_run_id: Mapped[uuid.UUID] = fk("pipe_gate_run.id")
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False)


class PipeSchedule(Scoped):
    __tablename__ = "pipe_schedule"

    pipeline_id: Mapped[uuid.UUID] = fk("pipe_pipeline.id")
    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False, default="0 2 * * *")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
