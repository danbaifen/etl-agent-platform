from __future__ import annotations

import uuid

from fastapi import APIRouter, Header

from app.core.errors import AppError, envelope
from app.core.idempotency import ensure_idempotency
from app.modules.iam.deps import CtxDep, SessionDep
from app.modules.pipe.service import PipeService

router = APIRouter(tags=["pipeline"])


@router.get("/pipelines")
async def list_pipelines(ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("pipe:version:read")
    return envelope("OK", "success", await PipeService(session).list_pipelines(ctx), ctx.trace_id)


@router.post("/candidates/{candidate_id}/freeze")
async def freeze_candidate(
    candidate_id: uuid.UUID,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("pipe:version:freeze")
    await ensure_idempotency(idempotency_key, f"pipe.freeze:{candidate_id}", {"candidate": str(candidate_id)})
    data = await PipeService(session).freeze(ctx, candidate_id)
    return envelope("OK", "success", data, ctx.trace_id)


@router.get("/versions/{version_id}")
async def get_version(version_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("pipe:version:read")
    return envelope("OK", "success", await PipeService(session).get_version(ctx, version_id), ctx.trace_id)


@router.get("/versions/{left_id}/diff/{right_id}")
async def diff_versions(left_id: uuid.UUID, right_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("pipe:version:read")
    data = await PipeService(session).diff(ctx, left_id, right_id)
    return envelope("OK", "success", data, ctx.trace_id)
