from __future__ import annotations

import uuid

from fastapi import APIRouter, Header

from app.core.errors import envelope
from app.core.idempotency import ensure_idempotency
from app.modules.iam.deps import CtxDep, SessionDep
from app.modules.studio.service import StudioService

router = APIRouter(tags=["studio"])


@router.get("/studio/sessions")
async def list_sessions(ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("studio:session:read")
    return envelope("OK", "success", await StudioService(session).list_sessions(ctx), ctx.trace_id)


@router.post("/studio/sessions", status_code=201)
async def create_session(
    payload: dict,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("studio:session:write")
    await ensure_idempotency(idempotency_key, f"studio.session.create:{ctx.project_id}", payload)
    data = await StudioService(session).create_session(ctx, payload)
    return envelope("OK", "success", data, ctx.trace_id)


@router.get("/studio/sessions/{session_id}")
async def get_session(session_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("studio:session:read")
    return envelope("OK", "success", await StudioService(session).get_session(ctx, session_id), ctx.trace_id)


@router.post("/studio/interrupts/{interrupt_id}/answer")
async def answer_interrupt(
    interrupt_id: uuid.UUID,
    payload: dict,
    ctx: CtxDep,
    session: SessionDep,
) -> dict:
    ctx.require("studio:session:write")
    data = await StudioService(session).answer_interrupt(ctx, interrupt_id, payload)
    return envelope("OK", "success", data, ctx.trace_id)
