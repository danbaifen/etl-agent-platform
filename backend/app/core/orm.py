from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def fk(target: str, nullable: bool = False, index: bool = True):
    return mapped_column(
        Uuid(as_uuid=True), ForeignKey(target), nullable=nullable, index=index
    )


class Scoped(Base):
    """带租户/项目隔离键的业务表基类。

    tenant_id 与 project_id 由服务层从 RequestContext 注入，绝不接受请求体传入。
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = created_at()
