from __future__ import annotations

import uuid

from fastapi import APIRouter, Header

from app.core.errors import envelope
from app.core.idempotency import ensure_idempotency
from app.modules.iam.deps import CtxDep, SessionDep
from app.modules.meta.service import ProbeService

router = APIRouter(tags=["metadata"])


@router.post("/connections/{connection_id}/probe", status_code=202)
async def run_probe(
    connection_id: uuid.UUID,
    ctx: CtxDep,
    session: SessionDep,
    payload: dict | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("meta:probe:run")
    await ensure_idempotency(idempotency_key, f"meta.probe:{connection_id}", payload or {})
    profile = await ProbeService(session).run(ctx, connection_id, payload)
    return envelope(
        "OK",
        "success",
        {"profile_id": str(profile.id), "version_no": profile.version_no, "sha256": profile.profile_sha256},
        ctx.trace_id,
    )


@router.get("/connections/{connection_id}/profiles")
async def list_profiles(connection_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("meta:probe:read")
    rows = await ProbeService(session).list_profiles(ctx, connection_id)
    return envelope(
        "OK",
        "success",
        [
            {
                "id": str(p.id),
                "version_no": p.version_no,
                "profile_sha256": p.profile_sha256,
                "object_count": p.object_count,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in rows
        ],
        ctx.trace_id,
    )


@router.get("/connections/{connection_id}/profile")
async def latest_profile(connection_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("meta:probe:read")
    data = await ProbeService(session).latest_profile(ctx, connection_id)
    return envelope("OK", "success", data, ctx.trace_id)


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("meta:probe:read")
    data = await ProbeService(session).get_profile(ctx, profile_id)
    return envelope("OK", "success", data, ctx.trace_id)
