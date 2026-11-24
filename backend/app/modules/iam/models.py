from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IamTenant(Base):
    __tablename__ = "iam_tenant"
    __table_args__ = (
        UniqueConstraint("code", name="uq_iam_tenant_code"),
        CheckConstraint("status IN ('ACTIVE','SUSPENDED')", name="ck_iam_tenant_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IamUser(Base):
    __tablename__ = "iam_user"
    __table_args__ = (
        UniqueConstraint("external_subject", name="uq_iam_user_subject"),
        CheckConstraint("status IN ('ACTIVE','DISABLED')", name="ck_iam_user_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    external_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    email_masked: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IamUserCredential(Base):
    __tablename__ = "iam_user_credential"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("iam_user.id"), primary_key=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IamProject(Base):
    __tablename__ = "iam_project"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_iam_project_code"),
        CheckConstraint(
            "status IN ('ACTIVE','SUSPENDED','ARCHIVED')", name="ck_iam_project_status"
        ),
        Index("ix_iam_project_list", "tenant_id", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("iam_tenant.id"))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IamRole(Base):
    __tablename__ = "iam_role"
    __table_args__ = (UniqueConstraint("code", name="uq_iam_role_code"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="PROJECT")
    is_business_approval_role: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class IamMember(Base):
    __tablename__ = "iam_member"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_iam_member"),
        CheckConstraint("status IN ('ACTIVE','REMOVED')", name="ck_iam_member_status"),
        Index("ix_iam_member_list", "project_id", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("iam_project.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("iam_user.id"))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IamMemberRole(Base):
    __tablename__ = "iam_member_role"
    __table_args__ = (
        Index(
            "uq_iam_member_active_role",
            "member_id",
            "role_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    member_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("iam_member.id"))
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("iam_role.id"))
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _created()


class IamAuthSession(Base):
    __tablename__ = "iam_auth_session"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_iam_auth_session_token"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("iam_user.id"))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
