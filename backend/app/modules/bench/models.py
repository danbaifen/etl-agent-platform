from __future__ import annotations

import uuid

from sqlalchemy import JSON, CheckConstraint, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Scoped, fk


class BenchSuite(Scoped):
    __tablename__ = "bench_suite"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_bench_suite_name"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    level: Mapped[str] = mapped_column(String(8), nullable=False, default="L0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class BenchCase(Scoped):
    __tablename__ = "bench_case"
    __table_args__ = (UniqueConstraint("suite_id", "case_code", name="uq_bench_case_code"),)

    suite_id: Mapped[uuid.UUID] = fk("bench_suite.id")
    case_code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")


class BenchCaseVersion(Scoped):
    __tablename__ = "bench_case_version"
    __table_args__ = (UniqueConstraint("case_id", "version_no", name="uq_bench_case_version"),)

    case_id: Mapped[uuid.UUID] = fk("bench_case.id")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected_result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class BenchRun(Scoped):
    __tablename__ = "bench_run"
    __table_args__ = (
        CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED')", name="ck_bench_run_status"),
    )

    suite_id: Mapped[uuid.UUID] = fk("bench_suite.id")
    provider_snapshot: Mapped[str] = mapped_column(String(64), nullable=False, default="rule-based")
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="policy-1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p0_p1_interception_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    triggered_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)


class BenchCaseResult(Scoped):
    __tablename__ = "bench_case_result"

    bench_run_id: Mapped[uuid.UUID] = fk("bench_run.id")
    case_version_id: Mapped[uuid.UUID] = fk("bench_case_version.id")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_risk: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    actual_risk: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    result_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
