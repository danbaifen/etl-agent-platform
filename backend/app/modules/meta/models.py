from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Scoped, fk


class MetaProbeRun(Scoped):
    __tablename__ = "meta_probe_run"
    __table_args__ = (
        CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED')", name="ck_meta_probe_status"),
    )

    connection_id: Mapped[uuid.UUID] = fk("asset_connection.id")
    probe_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_error: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)


class MetaProfile(Scoped):
    __tablename__ = "meta_profile"
    __table_args__ = (
        UniqueConstraint("connection_id", "version_no", name="uq_meta_profile_version"),
    )

    connection_id: Mapped[uuid.UUID] = fk("asset_connection.id")
    probe_run_id: Mapped[uuid.UUID] = fk("meta_probe_run.id")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frozen: Mapped[bool] = mapped_column(default=True, nullable=False)


class MetaObject(Scoped):
    __tablename__ = "meta_object"

    profile_id: Mapped[uuid.UUID] = fk("meta_profile.id")
    namespace: Mapped[str] = mapped_column(String(128), nullable=False, default="main")
    object_name: Mapped[str] = mapped_column(String(256), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False, default="TABLE")
    row_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MetaColumn(Scoped):
    __tablename__ = "meta_column"

    object_id: Mapped[uuid.UUID] = fk("meta_object.id")
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    column_name: Mapped[str] = mapped_column(String(128), nullable=False)
    data_type: Mapped[str] = mapped_column(String(64), nullable=False)
    nullable: Mapped[bool] = mapped_column(default=True, nullable=False)
    primary_key: Mapped[bool] = mapped_column(default=False, nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(24), nullable=False, default="NONE")
    mask_policy: Mapped[str | None] = mapped_column(String(32), nullable=True)


class MetaColumnStat(Scoped):
    __tablename__ = "meta_column_stat"

    column_id: Mapped[uuid.UUID] = fk("meta_column.id")
    stat_method: Mapped[str] = mapped_column(String(32), nullable=False, default="APPROX")
    null_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    distinct_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class MetaSample(Scoped):
    __tablename__ = "meta_sample"

    column_id: Mapped[uuid.UUID] = fk("meta_column.id")
    masked_value: Mapped[str] = mapped_column(String(256), nullable=False)
    mask_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_digest: Mapped[str] = mapped_column(String(64), nullable=False)
