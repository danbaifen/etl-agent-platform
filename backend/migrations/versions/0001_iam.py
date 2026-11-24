"""iam 初始表

Revision ID: 0001_iam
Revises:
Create Date: 2026-11-23

表结构与《后端SPEC.md》第 4 章逐字段一致；模型定义在 app/modules/iam/models.py，
此处直接由 metadata 建表，避免 DDL 与模型两处维护产生漂移。
"""

from __future__ import annotations

from alembic import op

from app.core.db import Base
from app import models_registry  # noqa: F401  全量模型注册

revision = "0001_iam"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
