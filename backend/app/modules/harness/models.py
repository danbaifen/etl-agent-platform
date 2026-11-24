from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.orm import Scoped, fk


class HarnessToolIntent(Scoped):
    __tablename__ = "harness_tool_intent"

    actor_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="PROD")
    resource_scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parameter_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class HarnessPdpDecision(Scoped):
    __tablename__ = "harness_pdp_decision"
    __table_args__ = (
        CheckConstraint("risk_level IN ('P0','P1','P2','P3')", name="ck_harness_pdp_risk"),
    )

    tool_intent_id: Mapped[uuid.UUID] = fk("harness_tool_intent.id")
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="policy-1")
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False)
    approval_requirements: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    matched_rules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class HarnessPreparation(Scoped):
    __tablename__ = "harness_preparation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING_APPROVAL','APPROVED','REJECTED','COMMITTED','EXPIRED')",
            name="ck_harness_prep_status",
        ),
        CheckConstraint("risk_level IN ('P0','P1','P2','P3')", name="ck_harness_prep_risk"),
    )

    pipeline_version_id: Mapped[uuid.UUID] = fk("pipe_version.id")
    pdp_decision_id: Mapped[uuid.UUID] = fk("harness_pdp_decision.id")
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(8), nullable=False)
    data_classification: Mapped[str] = mapped_column(String(24), nullable=False, default="INTERNAL")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING_APPROVAL")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)


class HarnessPreparationResource(Scoped):
    __tablename__ = "harness_preparation_resource"

    preparation_id: Mapped[uuid.UUID] = fk("harness_preparation.id")
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    access_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="READ")


class HarnessBudgetContract(Scoped):
    __tablename__ = "harness_budget_contract"

    preparation_id: Mapped[uuid.UUID] = fk("harness_preparation.id")
    max_read_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1_000_000)
    max_write_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=512 * 1024 * 1024)
    max_duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1_800_000)
    max_amplification: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    max_reject_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.20)


class HarnessRollbackPlan(Scoped):
    __tablename__ = "harness_rollback_plan"

    preparation_id: Mapped[uuid.UUID] = fk("harness_preparation.id")
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="SHADOW_ONLY")
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class HarnessApprovalSlot(Scoped):
    __tablename__ = "harness_approval_slot"
    __table_args__ = (
        UniqueConstraint("preparation_id", "slot_code", name="uq_harness_slot_code"),
        CheckConstraint("slot_code IN ('DATA','SECURITY')", name="ck_harness_slot_code"),
        CheckConstraint("status IN ('PENDING','APPROVED','REJECTED')", name="ck_harness_slot_status"),
    )

    preparation_id: Mapped[uuid.UUID] = fk("harness_preparation.id")
    slot_code: Mapped[str] = mapped_column(String(16), nullable=False)
    assignee_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")


class HarnessApprovalDecision(Scoped):
    __tablename__ = "harness_approval_decision"
    __table_args__ = (
        CheckConstraint("decision IN ('APPROVE','REJECT')", name="ck_harness_decision"),
    )

    approval_slot_id: Mapped[uuid.UUID] = fk("harness_approval_slot.id")
    preparation_id: Mapped[uuid.UUID] = fk("harness_preparation.id")
    approver_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    preparation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HarnessCommit(Scoped):
    __tablename__ = "harness_commit"

    preparation_id: Mapped[uuid.UUID] = fk("harness_preparation.id")
    operator_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    approved_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    commit_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HarnessCapability(Scoped):
    __tablename__ = "harness_capability"
    __table_args__ = (UniqueConstraint("jti", name="uq_harness_capability_jti"),)

    commit_id: Mapped[uuid.UUID] = fk("harness_commit.id")
    jti: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(128), nullable=False)


class HarnessCapabilityConsumption(Scoped):
    __tablename__ = "harness_capability_consumption"
    __table_args__ = (
        UniqueConstraint("capability_id", name="uq_harness_consumption_once"),
    )

    capability_id: Mapped[uuid.UUID] = fk("harness_capability.id")
    consumer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HarnessOutboxEvent(Scoped):
    __tablename__ = "harness_outbox_event"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','DISPATCHED','FAILED')", name="ck_harness_outbox_status"
        ),
    )

    aggregate_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class HarnessSigningKey(Base):
    __tablename__ = "harness_signing_key"

    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="Ed25519")
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    private_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HarnessEvidenceRecord(Base):
    __tablename__ = "harness_evidence_record"
    __table_args__ = (
        UniqueConstraint("chain_id", "sequence_no", name="uq_harness_evidence_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chain_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(128), nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
