from __future__ import annotations

import asyncio
import re
import sqlite3
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.crypto import sha256_hex
from app.core.errors import AppError, NotFound
from app.modules.asset.models import AssetConnection
from app.modules.meta.models import (
    MetaColumn,
    MetaColumnStat,
    MetaObject,
    MetaProbeRun,
    MetaProfile,
    MetaSample,
)

UTC = timezone.utc
SAMPLE_ROWS = 5

# 字段名 → 敏感级别 / 脱敏策略。命中即视为敏感，样本只存脱敏值。
SENSITIVE_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"(^|_)(phone|mobile|tel)$"), "HIGH", "PHONE"),
    (re.compile(r"(^|_)email$"), "MEDIUM", "EMAIL"),
    (re.compile(r"(^|_)(id_card|idcard|identity_no)$"), "HIGH", "ID_CARD"),
    (re.compile(r"(^|_)(name|customer_name|user_name)$"), "MEDIUM", "NAME"),
    (re.compile(r"(^|_)(address|addr)$"), "MEDIUM", "ADDRESS"),
    (re.compile(r"(^|_)(password|passwd|secret|token)$"), "CRITICAL", "SECRET"),
)


def classify(column_name: str) -> tuple[str, str | None]:
    lowered = column_name.lower()
    for pattern, level, policy in SENSITIVE_RULES:
        if pattern.search(lowered):
            return level, policy
    return "NONE", None


def mask(value: object, policy: str | None) -> str:
    if value is None:
        return "<NULL>"
    text = str(value)
    if policy is None:
        return text if len(text) <= 64 else text[:61] + "..."
    if policy == "PHONE":
        return text[:3] + "****" + text[-4:] if len(text) >= 8 else "***"
    if policy == "EMAIL":
        local, _, domain = text.partition("@")
        return (local[:1] + "***@" + domain) if domain else "***"
    if policy == "ID_CARD":
        return text[:4] + "**********" + text[-4:] if len(text) >= 12 else "***"
    if policy == "NAME":
        return text[:1] + "**"
    if policy == "ADDRESS":
        return text[:6] + "***"
    return "***"  # SECRET 一类不保留任何字符


def _probe_sqlite(path: str, with_samples: bool) -> list[dict]:
    """只读方式探测 SQLite 数据源：表、字段、行数、空值率、近似基数、样本。"""
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        cur = conn.cursor()
        tables = [
            row[0]
            for row in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        result: list[dict] = []
        for table in tables:
            columns = []
            info = cur.execute(f'PRAGMA table_info("{table}")').fetchall()
            total = cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for cid, name, ctype, notnull, default, pk in info:
                null_count = cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{name}" IS NULL').fetchone()[0]
                distinct = cur.execute(f'SELECT COUNT(DISTINCT "{name}") FROM "{table}"').fetchone()[0]
                samples: list[str] = []
                if with_samples and total:
                    rows = cur.execute(f'SELECT "{name}" FROM "{table}" LIMIT {SAMPLE_ROWS}').fetchall()
                    samples = [r[0] for r in rows]
                columns.append(
                    {
                        "ordinal": cid + 1,
                        "column_name": name,
                        "data_type": (ctype or "TEXT").upper(),
                        "nullable": not bool(notnull),
                        "primary_key": bool(pk),
                        "row_count": total,
                        "null_ratio": round(null_count / total, 4) if total else 0.0,
                        "distinct_estimate": int(distinct),
                        "samples": samples,
                    }
                )
            result.append({"object_name": table, "object_type": "TABLE", "row_count": total, "columns": columns})
        return result
    finally:
        conn.close()


class ProbeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _connection(self, ctx: RequestContext, connection_id: uuid.UUID) -> AssetConnection:
        conn = await self.session.get(AssetConnection, connection_id)
        if conn is None or conn.project_id != ctx.project_id:
            raise NotFound("ASSET_CONNECTION_NOT_FOUND", "连接不存在")
        return conn

    async def run(self, ctx: RequestContext, connection_id: uuid.UUID, options: dict | None = None) -> MetaProfile:
        connection = await self._connection(ctx, connection_id)
        if connection.connection_type != "SQLITE":
            raise AppError(
                "META_PROBE_UNSUPPORTED",
                f"当前实现仅支持 SQLITE 类型的只读探查，收到 {connection.connection_type}",
                422,
            )
        path = (connection.safe_config or {}).get("database_path", "")
        if not path:
            raise AppError("META_PROBE_CONFIG_INVALID", "连接缺少 database_path 配置", 422)

        run = MetaProbeRun(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            connection_id=connection.id,
            probe_options=options or {"sample": True},
            status="RUNNING",
            created_by_user_id=ctx.user_id,
        )
        self.session.add(run)
        await self.session.flush()

        try:
            objects = await asyncio.to_thread(_probe_sqlite, path, True)
        except Exception as exc:  # 只读探测失败不抛给前端堆栈
            run.status = "FAILED"
            run.safe_error = f"探测失败：{type(exc).__name__}"
            run.ended_at = datetime.now(UTC)
            await self.session.commit()
            raise AppError("META_PROBE_FAILED", "元数据探查失败，请检查连接配置", 422) from exc

        version_no = (
            await self.session.execute(
                select(func.coalesce(func.max(MetaProfile.version_no), 0)).where(
                    MetaProfile.connection_id == connection.id
                )
            )
        ).scalar_one() + 1

        structural = [
            {
                "object": o["object_name"],
                "columns": [
                    {
                        "name": c["column_name"],
                        "type": c["data_type"],
                        "nullable": c["nullable"],
                        "pk": c["primary_key"],
                        "sensitivity": classify(c["column_name"])[0],
                    }
                    for c in o["columns"]
                ],
            }
            for o in objects
        ]

        profile = MetaProfile(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            connection_id=connection.id,
            probe_run_id=run.id,
            version_no=version_no,
            profile_sha256=sha256_hex(structural),
            object_count=len(objects),
            frozen=True,
        )
        self.session.add(profile)
        await self.session.flush()

        for obj in objects:
            row = MetaObject(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                profile_id=profile.id,
                namespace="main",
                object_name=obj["object_name"],
                object_type=obj["object_type"],
                row_estimate=obj["row_count"],
            )
            self.session.add(row)
            await self.session.flush()
            for col in obj["columns"]:
                level, policy = classify(col["column_name"])
                column = MetaColumn(
                    tenant_id=ctx.tenant_id,
                    project_id=ctx.project_id,
                    object_id=row.id,
                    ordinal=col["ordinal"],
                    column_name=col["column_name"],
                    data_type=col["data_type"],
                    nullable=col["nullable"],
                    primary_key=col["primary_key"],
                    sensitivity=level,
                    mask_policy=policy,
                )
                self.session.add(column)
                await self.session.flush()
                self.session.add(
                    MetaColumnStat(
                        tenant_id=ctx.tenant_id,
                        project_id=ctx.project_id,
                        column_id=column.id,
                        stat_method="EXACT",
                        null_ratio=col["null_ratio"],
                        distinct_estimate=col["distinct_estimate"],
                        payload={"row_count": col["row_count"]},
                    )
                )
                for raw in col["samples"]:
                    masked = mask(raw, policy)
                    self.session.add(
                        MetaSample(
                            tenant_id=ctx.tenant_id,
                            project_id=ctx.project_id,
                            column_id=column.id,
                            masked_value=masked,
                            mask_policy=policy or "NONE",
                            sample_digest=sha256_hex(masked),
                        )
                    )

        run.status = "SUCCEEDED"
        run.ended_at = datetime.now(UTC)
        await self.session.commit()
        return profile

    async def list_profiles(self, ctx: RequestContext, connection_id: uuid.UUID) -> list[MetaProfile]:
        await self._connection(ctx, connection_id)
        rows = await self.session.execute(
            select(MetaProfile)
            .where(MetaProfile.connection_id == connection_id)
            .order_by(MetaProfile.version_no.desc())
        )
        return list(rows.scalars())

    async def get_profile(self, ctx: RequestContext, profile_id: uuid.UUID) -> dict:
        profile = await self.session.get(MetaProfile, profile_id)
        if profile is None or profile.project_id != ctx.project_id:
            raise NotFound("META_PROFILE_NOT_FOUND", "元数据快照不存在")

        objects = (
            await self.session.execute(
                select(MetaObject).where(MetaObject.profile_id == profile.id).order_by(MetaObject.object_name)
            )
        ).scalars()
        tree = []
        for obj in objects:
            columns = (
                await self.session.execute(
                    select(MetaColumn).where(MetaColumn.object_id == obj.id).order_by(MetaColumn.ordinal)
                )
            ).scalars()
            column_payload = []
            for col in columns:
                stat = (
                    await self.session.execute(
                        select(MetaColumnStat).where(MetaColumnStat.column_id == col.id).limit(1)
                    )
                ).scalar_one_or_none()
                samples = (
                    await self.session.execute(
                        select(MetaSample).where(MetaSample.column_id == col.id).limit(SAMPLE_ROWS)
                    )
                ).scalars()
                column_payload.append(
                    {
                        "id": str(col.id),
                        "ordinal": col.ordinal,
                        "name": col.column_name,
                        "data_type": col.data_type,
                        "nullable": col.nullable,
                        "primary_key": col.primary_key,
                        "sensitivity": col.sensitivity,
                        "mask_policy": col.mask_policy,
                        "null_ratio": stat.null_ratio if stat else None,
                        "distinct_estimate": stat.distinct_estimate if stat else None,
                        "samples": [s.masked_value for s in samples],
                    }
                )
            tree.append(
                {
                    "id": str(obj.id),
                    "name": obj.object_name,
                    "type": obj.object_type,
                    "row_estimate": obj.row_estimate,
                    "columns": column_payload,
                }
            )

        return {
            "id": str(profile.id),
            "connection_id": str(profile.connection_id),
            "version_no": profile.version_no,
            "profile_sha256": profile.profile_sha256,
            "object_count": profile.object_count,
            "created_at": profile.created_at.isoformat() if profile.created_at else None,
            "objects": tree,
        }

    async def latest_profile(self, ctx: RequestContext, connection_id: uuid.UUID) -> dict | None:
        profiles = await self.list_profiles(ctx, connection_id)
        if not profiles:
            return None
        return await self.get_profile(ctx, profiles[0].id)


async def ensure_profile(session: AsyncSession, ctx: RequestContext, connection_id: uuid.UUID) -> MetaProfile:
    """生成链路用：取最新快照，没有就现场跑一次探查。"""
    service = ProbeService(session)
    profiles = await service.list_profiles(ctx, connection_id)
    if profiles:
        return profiles[0]
    return await service.run(ctx, connection_id)
