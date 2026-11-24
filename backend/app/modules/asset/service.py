from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import AppError, Conflict, NotFound
from app.modules.asset.models import (
    AssetConnection,
    AssetConnectionTest,
    AssetSecretRef,
    AssetSecretRotation,
)

UTC = timezone.utc


def _ping_sqlite(path: str) -> None:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        conn.execute("SELECT 1").fetchone()
    finally:
        conn.close()


class ConnectionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, ctx: RequestContext) -> list[dict]:
        rows = (
            await self.session.execute(
                select(AssetConnection)
                .where(AssetConnection.project_id == ctx.project_id)
                .order_by(AssetConnection.created_at.desc())
            )
        ).scalars()
        out = []
        for conn in rows:
            last = (
                await self.session.execute(
                    select(AssetConnectionTest)
                    .where(AssetConnectionTest.connection_id == conn.id)
                    .order_by(AssetConnectionTest.checked_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            out.append(self._brief(conn, last))
        return out

    @staticmethod
    def _brief(conn: AssetConnection, last: AssetConnectionTest | None) -> dict:
        return {
            "id": str(conn.id),
            "name": conn.name,
            "connection_type": conn.connection_type,
            "environment": conn.environment,
            "status": conn.status,
            "safe_config": conn.safe_config or {},
            "secret_ref_id": str(conn.secret_ref_id) if conn.secret_ref_id else None,
            "last_test": (
                {
                    "result": last.result,
                    "latency_ms": last.latency_ms,
                    "safe_error": last.safe_error,
                    "checked_at": last.checked_at.isoformat() if last.checked_at else None,
                }
                if last
                else None
            ),
        }

    async def create(self, ctx: RequestContext, payload: dict) -> dict:
        name = (payload.get("name") or "").strip()
        if not name:
            raise AppError("ASSET_CONNECTION_NAME_REQUIRED", "连接名称必填", 400)
        exists = (
            await self.session.execute(
                select(AssetConnection).where(
                    AssetConnection.project_id == ctx.project_id, AssetConnection.name == name
                )
            )
        ).scalar_one_or_none()
        if exists:
            raise Conflict("ASSET_CONNECTION_NAME_CONFLICT", "同名连接已存在")

        secret_ref_id = payload.get("secret_ref_id")
        if secret_ref_id:
            secret = await self.session.get(AssetSecretRef, uuid.UUID(str(secret_ref_id)))
            if secret is None or secret.project_id != ctx.project_id:
                raise NotFound("ASSET_SECRET_NOT_FOUND", "Secret 引用不存在")

        connection = AssetConnection(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            name=name,
            connection_type=payload.get("connection_type", "SQLITE"),
            environment=payload.get("environment", "DEV"),
            safe_config=payload.get("safe_config") or {},
            secret_ref_id=uuid.UUID(str(secret_ref_id)) if secret_ref_id else None,
            status="ACTIVE",
            created_by_user_id=ctx.user_id,
        )
        self.session.add(connection)
        await self.session.commit()
        return self._brief(connection, None)

    async def test(self, ctx: RequestContext, connection_id: uuid.UUID) -> dict:
        connection = await self.session.get(AssetConnection, connection_id)
        if connection is None or connection.project_id != ctx.project_id:
            raise NotFound("ASSET_CONNECTION_NOT_FOUND", "连接不存在")

        started = time.perf_counter()
        result, safe_error = "SUCCESS", None
        try:
            if connection.connection_type == "SQLITE":
                path = (connection.safe_config or {}).get("database_path", "")
                if not path:
                    raise ValueError("missing database_path")
                await asyncio.to_thread(_ping_sqlite, path)
            else:
                # 其他类型尚无驱动实现：明确返回未支持，不伪造成功
                raise NotImplementedError(connection.connection_type)
        except NotImplementedError:
            result, safe_error = "UNSUPPORTED", f"暂未支持的连接类型：{connection.connection_type}"
        except Exception as exc:
            result, safe_error = "FAILED", f"连通性失败：{type(exc).__name__}"

        latency = int((time.perf_counter() - started) * 1000)
        record = AssetConnectionTest(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            connection_id=connection.id,
            result=result,
            safe_error=safe_error,
            latency_ms=latency,
            checked_at=datetime.now(UTC),
        )
        self.session.add(record)
        connection.status = "ACTIVE" if result == "SUCCESS" else "ERROR"
        await self.session.commit()
        return {
            "result": result,
            "latency_ms": latency,
            "safe_error": safe_error,
            "checked_at": record.checked_at.isoformat(),
        }

    async def tests(self, ctx: RequestContext, connection_id: uuid.UUID) -> list[dict]:
        connection = await self.session.get(AssetConnection, connection_id)
        if connection is None or connection.project_id != ctx.project_id:
            raise NotFound("ASSET_CONNECTION_NOT_FOUND", "连接不存在")
        rows = (
            await self.session.execute(
                select(AssetConnectionTest)
                .where(AssetConnectionTest.connection_id == connection_id)
                .order_by(AssetConnectionTest.checked_at.desc())
                .limit(20)
            )
        ).scalars()
        return [
            {
                "result": r.result,
                "latency_ms": r.latency_ms,
                "safe_error": r.safe_error,
                "checked_at": r.checked_at.isoformat() if r.checked_at else None,
            }
            for r in rows
        ]

    async def create_secret(self, ctx: RequestContext, payload: dict) -> dict:
        secret = AssetSecretRef(
            tenant_id=ctx.tenant_id,
            project_id=ctx.project_id,
            name=payload["name"],
            provider="VAULT",
            vault_path=payload.get("vault_path") or f"kv/etl/{ctx.project_id}/{payload['name']}",
            vault_version=1,
            status="ACTIVE",
        )
        self.session.add(secret)
        await self.session.commit()
        return {"id": str(secret.id), "name": secret.name, "vault_path": secret.vault_path,
                "vault_version": secret.vault_version, "status": secret.status}

    async def list_secrets(self, ctx: RequestContext) -> list[dict]:
        rows = (
            await self.session.execute(
                select(AssetSecretRef).where(AssetSecretRef.project_id == ctx.project_id)
            )
        ).scalars()
        return [
            {"id": str(s.id), "name": s.name, "vault_path": s.vault_path,
             "vault_version": s.vault_version, "status": s.status}
            for s in rows
        ]

    async def rotate(self, ctx: RequestContext, secret_id: uuid.UUID) -> dict:
        secret = await self.session.get(AssetSecretRef, secret_id)
        if secret is None or secret.project_id != ctx.project_id:
            raise NotFound("ASSET_SECRET_NOT_FOUND", "Secret 引用不存在")
        previous = secret.vault_version
        secret.vault_version = previous + 1
        secret.status = "ACTIVE"
        self.session.add(
            AssetSecretRotation(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                secret_ref_id=secret.id,
                from_version=previous,
                to_version=secret.vault_version,
                result="SUCCESS",
                operator_user_id=ctx.user_id,
                rotated_at=datetime.now(UTC),
            )
        )
        await self.session.commit()
        return {"id": str(secret.id), "vault_version": secret.vault_version, "previous_version": previous}
