from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Scoped, fk


class StudioSession(Scoped):
    __tablename__ = "studio_session"
    __table_args__ = (
        CheckConstraint("status IN ('OPEN','CLARIFYING','GENERATED','CLOSED')", name="ck_studio_session_status"),
    )

    maker_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_connection_id: Mapped[uuid.UUID] = fk("asset_connection.id")
    target_connection_id: Mapped[uuid.UUID] = fk("asset_connection.id")
    source_object: Mapped[str] = mapped_column(String(256), nullable=False)
    target_object: Mapped[str] = mapped_column(String(256), nullable=False)
    requirement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    flow_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class StudioMessage(Scoped):
    __tablename__ = "studio_message"

    session_id: Mapped[uuid.UUID] = fk("studio_session.id")
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class FlowRun(Scoped):
    __tablename__ = "flow_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING','INTERRUPTED','SUCCEEDED','FAILED')", name="ck_flow_run_status"
        ),
    )

    session_id: Mapped[uuid.UUID] = fk("studio_session.id")
    graph_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="RUNNING")
    current_node: Mapped[str] = mapped_column(String(64), nullable=False, default="intent")


class FlowCheckpoint(Scoped):
    __tablename__ = "flow_checkpoint"

    flow_run_id: Mapped[uuid.UUID] = fk("flow_run.id")
    checkpoint_no: Mapped[int] = mapped_column(Integer, nullable=False)
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    state_safe_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    state_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StudioInterrupt(Scoped):
    __tablename__ = "studio_interrupt"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','ANSWERED','EXPIRED')", name="ck_studio_interrupt_status"),
    )

    flow_run_id: Mapped[uuid.UUID] = fk("flow_run.id")
    question_key: Mapped[str] = mapped_column(String(64), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    ui_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    answer_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")


class GenCandidate(Scoped):
    __tablename__ = "gen_candidate"

    flow_run_id: Mapped[uuid.UUID] = fk("flow_run.id")
    session_id: Mapped[uuid.UUID] = fk("studio_session.id")
    candidate_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="GENERATED")
    repair_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
