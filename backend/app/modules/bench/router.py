from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.core.errors import envelope
from app.modules.bench.service import BenchService
from app.modules.iam.deps import CtxDep, SessionDep

router = APIRouter(tags=["benchmark"])


@router.get("/bench/suites")
async def list_suites(ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("bench:suite:read")
    return envelope("OK", "success", await BenchService(session).list_suites(ctx), ctx.trace_id)


@router.post("/bench/suites/{suite_id}/runs", status_code=201)
async def run_suite(suite_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("bench:run:trigger")
    data = await BenchService(session).run(ctx, suite_id)
    return envelope("OK", "success", data, ctx.trace_id)


@router.get("/bench/runs")
async def list_runs(ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("bench:suite:read")
    return envelope("OK", "success", await BenchService(session).list_runs(ctx), ctx.trace_id)


@router.get("/bench/runs/{run_id}")
async def get_run(run_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("bench:suite:read")
    return envelope("OK", "success", await BenchService(session).get_run(ctx, run_id), ctx.trace_id)
