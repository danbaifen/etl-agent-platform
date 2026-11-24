from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Request, Response

from app.core.config import get_settings
from app.core.errors import Unauthorized, envelope
from app.core.idempotency import ensure_idempotency
from app.modules.iam import errors as e
from app.modules.iam.deps import CtxDep, SessionDep
from app.modules.iam.schemas import (
    AssignRoleRequest,
    CreateProjectRequest,
    InviteMemberRequest,
    LoginRequest,
    MemberPage,
    ProjectPage,
    SwitchProjectRequest,
    UpdateMemberRequest,
    UpdateProjectRequest,
)
from app.modules.iam.service import AuthService, MemberService, ProjectService

auth_router = APIRouter(prefix="/auth", tags=["auth"])
projects_router = APIRouter(prefix="/projects", tags=["projects"])


@auth_router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response, session: SessionDep) -> dict:
    service = AuthService(session)
    ip = request.client.host if request.client else "-"
    result = await service.login(payload, ip)

    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=result.session_token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )
    return envelope("OK", "success", result.model_dump(mode="json"), getattr(request.state, "trace_id", None))


@auth_router.post("/logout", status_code=204)
async def logout(request: Request, session: SessionDep, ctx: CtxDep) -> Response:
    row = getattr(request.state, "session_row", None)
    if row is not None:
        await AuthService(session).logout(row.id)
    out = Response(status_code=204)
    out.delete_cookie(get_settings().session_cookie_name, path="/")
    return out


@auth_router.get("/session")
async def get_session_info(ctx: CtxDep, session: SessionDep) -> dict:
    data = await AuthService(session).build_session_response(ctx)
    return envelope("OK", "success", data.model_dump(mode="json"), ctx.trace_id)


@auth_router.post("/session/project")
async def switch_project(payload: SwitchProjectRequest, request: Request, ctx: CtxDep, session: SessionDep) -> dict:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise Unauthorized(e.AUTH_UNAUTHENTICATED, "未登录或会话已失效")

    service = AuthService(session)
    row = request.state.session_row
    await service.switch_project(ctx, row, payload.project_id)

    updated_ctx, _ = await service.resolve_context(token)
    data = await service.build_session_response(updated_ctx)
    return envelope("OK", "success", data.model_dump(mode="json"), updated_ctx.trace_id)


@projects_router.get("")
async def list_projects(ctx: CtxDep, session: SessionDep, limit: int = 20, cursor: str | None = None) -> dict:
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    items = await ProjectService(session).list(ctx, offset, limit)
    next_cursor = str(offset + limit) if len(items) == limit else None
    page = ProjectPage(items=items, next_cursor=next_cursor)
    return envelope("OK", "success", page.model_dump(mode="json"), ctx.trace_id)


@projects_router.post("", status_code=201)
async def create_project(
    payload: CreateProjectRequest,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("iam:project:write")
    await ensure_idempotency(idempotency_key, f"project.create:{ctx.user_id}", payload.model_dump())
    data = await ProjectService(session).create(ctx, payload)
    return envelope("OK", "success", data.model_dump(mode="json"), ctx.trace_id)


@projects_router.get("/{project_id}")
async def get_project(project_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    data = await ProjectService(session).get(ctx, project_id)
    return envelope("OK", "success", data.model_dump(mode="json"), ctx.trace_id)


@projects_router.patch("/{project_id}")
async def update_project(
    project_id: uuid.UUID,
    payload: UpdateProjectRequest,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("iam:project:write")
    await ensure_idempotency(idempotency_key, f"project.update:{project_id}", payload.model_dump())
    data = await ProjectService(session).update(ctx, project_id, payload)
    return envelope("OK", "success", data.model_dump(mode="json"), ctx.trace_id)


@projects_router.get("/{project_id}/members")
async def list_members(
    project_id: uuid.UUID,
    ctx: CtxDep,
    session: SessionDep,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    ctx.require("iam:member:read")
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    items = await MemberService(session).list(ctx, project_id, offset, limit)
    next_cursor = str(offset + limit) if len(items) == limit else None
    page = MemberPage(items=items, next_cursor=next_cursor)
    return envelope("OK", "success", page.model_dump(mode="json"), ctx.trace_id)


@projects_router.post("/{project_id}/members", status_code=201)
async def invite_member(
    project_id: uuid.UUID,
    payload: InviteMemberRequest,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("iam:member:write")
    await ensure_idempotency(idempotency_key, f"member.invite:{project_id}", payload.model_dump())
    data = await MemberService(session).invite(ctx, project_id, payload)
    return envelope("OK", "success", data.model_dump(mode="json"), ctx.trace_id)


@projects_router.patch("/{project_id}/members/{member_id}")
async def update_member(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: UpdateMemberRequest,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("iam:member:write")
    await ensure_idempotency(idempotency_key, f"member.update:{member_id}", payload.model_dump())
    data = await MemberService(session).update_status(ctx, project_id, member_id, payload.status)
    return envelope("OK", "success", data.model_dump(mode="json"), ctx.trace_id)


@projects_router.post("/{project_id}/members/{member_id}/roles")
async def assign_role(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: AssignRoleRequest,
    ctx: CtxDep,
    session: SessionDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx.require("iam:role:assign")
    await ensure_idempotency(idempotency_key, f"role.assign:{member_id}", payload.model_dump())
    data = await MemberService(session).assign_role(ctx, project_id, member_id, payload)
    return envelope("OK", "success", data.model_dump(mode="json"), ctx.trace_id)


@projects_router.delete("/{project_id}/members/{member_id}/roles/{assignment_id}")
async def revoke_role(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    assignment_id: uuid.UUID,
    ctx: CtxDep,
    session: SessionDep,
) -> dict:
    ctx.require("iam:role:assign")
    data = await MemberService(session).revoke_role(ctx, project_id, member_id, assignment_id)
    return envelope("OK", "success", data.model_dump(mode="json"), ctx.trace_id)


@projects_router.get("/{project_id}/roles")
async def list_roles(project_id: uuid.UUID, ctx: CtxDep, session: SessionDep) -> dict:
    ctx.require("iam:member:read")
    roles = await MemberService(session).list_roles()
    return envelope("OK", "success", [r.model_dump(mode="json") for r in roles], ctx.trace_id)
