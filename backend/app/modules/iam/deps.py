from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.db import get_session
from app.core.errors import Forbidden, Unauthorized
from app.modules.iam import errors as e
from app.modules.iam.service import AuthService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _token_from(request: Request) -> str | None:
    token = request.cookies.get("etl_session")
    if token:
        return token
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def get_context(request: Request, session: SessionDep) -> RequestContext:
    token = _token_from(request)
    if not token:
        raise Unauthorized(e.AUTH_UNAUTHENTICATED, "未登录或会话已失效")

    auth = AuthService(session)
    ctx, row = await auth.resolve_context(token)

    trace_id = getattr(request.state, "trace_id", ctx.trace_id)
    ctx = replace(ctx, trace_id=trace_id)
    request.state.ctx = ctx
    request.state.session_row = row
    return ctx


CtxDep = Annotated[RequestContext, Depends(get_context)]


def require_capability(capability: str):
    async def _dep(ctx: CtxDep) -> RequestContext:
        if not ctx.has(capability):
            raise Forbidden("AUTH_FORBIDDEN", f"缺少权限：{capability}")
        return ctx

    return _dep
