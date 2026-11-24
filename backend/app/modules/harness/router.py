from __future__ import annotations

import uuid

from fastapi import APIRouter, Header

from app.core.errors import envelope
from app.core.idempotency import ensure_idempotency
from app.modules.harness.service import HarnessService
from app.modules.iam.deps import CtxDep, SessionDep

router = APIRouter(tags=["harness"])


@router.post("/versions/{version_id}/prepare", status_code=201)
async def prepare(
    version_id: uuid.UUID,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("harness:prepare")
    await ensure_idempotency(idempotency_key, f"harness.prepare:{version_id}", {"version": str(version_id)})
    data = await HarnessService(session).prepare(ctx, version_id)
    return envelope("OK", "success", data, ctx.trace_id)


@router.get("/preparations")
async def list_preparations(ctx: CtxDep, session: SessionDep, status: str | None = None) -> dict:
    data = await HarnessService(session).list_preparations(ctx, status)
    return envelope("OK", "success", data, ctx.trace_id)


@router.get("/preparations/{preparation_id}")
async def get_preparation(preparation_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    data = await HarnessService(session).get_preparation(ctx, preparation_id)
    return envelope("OK", "success", data, ctx.trace_id)


@router.post("/preparations/{preparation_id}/approve")
async def approve(
    preparation_id: uuid.UUID,
    payload: dict,
    ctx: CtxDep,
    session: SessionDep,
) -> dict:
    slot_code = (payload.get("slot_code") or "").upper()
    if slot_code not in ("DATA", "SECURITY"):
        raise ValueError("slot_code 必须是 DATA 或 SECURITY")
    data = await HarnessService(session).approve(
        ctx, preparation_id, slot_code, payload.get("decision", "APPROVE"), payload.get("comment", "")
    )
    return envelope("OK", "success", data, ctx.trace_id)


@router.post("/preparations/{preparation_id}/commit", status_code=201)
async def commit(
    preparation_id: uuid.UUID,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("harness:commit")
    await ensure_idempotency(
        idempotency_key, f"harness.commit:{preparation_id}", {"preparation": str(preparation_id)}
    )
    data = await HarnessService(session).commit(ctx, preparation_id)
    return envelope("OK", "success", data, ctx.trace_id)


@router.get("/evidence")
async def evidence(ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("evidence:ledger:read")
    data = await HarnessService(session).verify_chain(ctx)
    return envelope("OK", "success", data, ctx.trace_id)


@router.get("/versions/{version_id}/verify")
async def verify_version(version_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    data = await HarnessService(session).verify_version(ctx, version_id)
    return envelope("OK", "success", data, ctx.trace_id)
