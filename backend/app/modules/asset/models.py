from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Scoped, fk


class AssetSecretRef(Scoped):
    __tablename__ = "asset_secret_ref"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_asset_secret_name"),
        CheckConstraint("status IN ('ACTIVE','ROTATING','EXPIRED')", name="ck_asset_secret_status"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="VAULT")
    vault_path: Mapped[str] = mapped_column(String(256), nullable=False)
    vault_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")


class AssetConnection(Scoped):
    __tablename__ = "asset_connection"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_asset_conn_name"),
        CheckConstraint(
            "connection_type IN ('SQLITE','MYSQL','POSTGRESQL','ORACLE','DORIS','CLICKHOUSE','CSV','EXCEL','JSON','PARQUET','S3','REST_API')",
            name="ck_asset_conn_type",
        ),
        CheckConstraint("environment IN ('DEV','STAGING','PROD')", name="ck_asset_conn_env"),
        CheckConstraint("status IN ('ACTIVE','DISABLED','ERROR')", name="ck_asset_conn_status"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_type: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="DEV")
    # 只存非敏感配置；口令/密钥一律走 secret_ref
    safe_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    secret_ref_id: Mapped[uuid.UUID | None] = fk("asset_secret_ref.id", nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)


class AssetConnectionTest(Scoped):
    __tablename__ = "asset_connection_test"

    connection_id: Mapped[uuid.UUID] = fk("asset_connection.id")
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    safe_error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssetSecretRotation(Scoped):
    __tablename__ = "asset_secret_rotation"

    secret_ref_id: Mapped[uuid.UUID] = fk("asset_secret_ref.id")
    from_version: Mapped[int] = mapped_column(Integer, nullable=False)
    to_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    operator_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    rotated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
