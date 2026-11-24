from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.core.errors import AppError, envelope
from app.modules.exec.service import ExecService
from app.modules.iam.deps import CtxDep, SessionDep

router = APIRouter(tags=["execution"])


@router.get("/runs")
async def list_runs(ctx: CtxDep, session: SessionDep) -> dict:
    return envelope("OK", "success", await ExecService(session).list_runs(ctx), ctx.trace_id)


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    return envelope("OK", "success", await ExecService(session).get(ctx, run_id), ctx.trace_id)


@router.post("/runs/{run_id}/start")
async def start_run(run_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("exec:run:control")
    data = await ExecService(session).start(ctx, run_id)
    return envelope("OK", "success", data, ctx.trace_id)


@router.post("/runs/{run_id}/rollback")
async def rollback_run(run_id: uuid.UUID, payload: dict | None, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("exec:run:control")
    reason = (payload or {}).get("reason") or "操作员触发受管回滚"
    data = await ExecService(session).rollback(ctx, run_id, reason)
    return envelope("OK", "success", data, ctx.trace_id)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("exec:run:control")
    run = await ExecService(session)._run(ctx, run_id)
    if run.status not in ("PENDING", "RUNNING"):
        raise AppError("EXEC_RUN_NOT_CANCELLABLE", f"状态 {run.status} 不可取消", 409)
    run.status = "CANCELLED"
    await session.commit()
    return envelope("OK", "success", {"run_id": str(run.id), "status": run.status}, ctx.trace_id)
