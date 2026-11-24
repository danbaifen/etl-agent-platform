from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Request

from app.core.errors import envelope
from app.core.idempotency import ensure_idempotency
from app.modules.asset.service import ConnectionService
from app.modules.iam.deps import CtxDep, SessionDep

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("")
async def list_connections(ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("asset:connection:read")
    data = await ConnectionService(session).list(ctx)
    return envelope("OK", "success", data, ctx.trace_id)


@router.post("", status_code=201)
async def create_connection(
    payload: dict,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("asset:connection:write")
    await ensure_idempotency(idempotency_key, f"asset.connection.create:{ctx.project_id}", payload)
    data = await ConnectionService(session).create(ctx, payload)
    return envelope("OK", "success", data, ctx.trace_id)


@router.post("/{connection_id}/test")
async def test_connection(
    connection_id: uuid.UUID,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default="auto", alias="Idempotency-Key"),
) -> dict:
    ctx.require("asset:connection:test")
    data = await ConnectionService(session).test(ctx, connection_id)
    return envelope("OK", "success", data, ctx.trace_id)


@router.get("/{connection_id}/tests")
async def list_tests(connection_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("asset:connection:read")
    data = await ConnectionService(session).tests(ctx, connection_id)
    return envelope("OK", "success", data, ctx.trace_id)


secrets_router = APIRouter(prefix="/secrets", tags=["secrets"])


@secrets_router.get("")
async def list_secrets(ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("asset:connection:read")
    data = await ConnectionService(session).list_secrets(ctx)
    return envelope("OK", "success", data, ctx.trace_id)


@secrets_router.post("", status_code=201)
async def create_secret(
    payload: dict,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("asset:connection:write")
    await ensure_idempotency(idempotency_key, f"asset.secret.create:{ctx.project_id}", payload)
    data = await ConnectionService(session).create_secret(ctx, payload)
    return envelope("OK", "success", data, ctx.trace_id)


@secrets_router.post("/{secret_id}/rotate")
async def rotate_secret(
    secret_id: uuid.UUID,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default="auto", alias="Idempotency-Key"),
) -> dict:
    ctx.require("asset:secret:rotate")
    data = await ConnectionService(session).rotate(ctx, secret_id)
    return envelope("OK", "success", data, ctx.trace_id)
