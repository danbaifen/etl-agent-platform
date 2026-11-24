from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import as_utc, now as clock_now
from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.errors import AppError, Conflict, Forbidden, NotFound, Unauthorized
from app.core.logging import get_logger, new_trace_id
from app.core.security import (
    generate_session_token,
    hash_password,
    hash_token,
    session_expiry,
    subject_hash,
    verify_password,
)
from app.modules.iam import errors as e
from app.modules.iam.models import IamAuthSession, IamMember, IamMemberRole, IamProject, IamUserCredential
from app.modules.iam.repository import (
    MemberRepository,
    MemberRoleRepository,
    ProjectRepository,
    RoleRepository,
    SessionRepository,
    TenantRepository,
    UserRepository,
)
from app.modules.iam.roles import (
    ROLE_PROJECT_ADMIN,
    approval_slots_for,
    capabilities_for,
    duty_conflict,
    duty_conflict_reason,
    is_known_role,
)
from app.modules.iam.schemas import (
    AssignRoleRequest,
    CreateProjectRequest,
    InviteMemberRequest,
    LoginRequest,
    LoginResponse,
    MemberResponse,
    ProjectResponse,
    RoleBrief,
    SessionResponse,
    UpdateProjectRequest,
)

log = get_logger("iam")

UTC = timezone.utc


def _now() -> datetime:
    return clock_now()


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.sessions = SessionRepository(session)
        self.projects = ProjectRepository(session)
        self.members = MemberRepository(session)
        self.roles = MemberRoleRepository(session)
        self.role_defs = RoleRepository(session)
        self.tenants = TenantRepository(session)

    async def login(self, req: LoginRequest, ip: str) -> LoginResponse:
        settings = get_settings()
        log.debug("auth.login.start", provider=req.provider, subject_hash=subject_hash(req.external_subject), ip=ip)

        if req.provider == "OIDC" and not settings.auth_provider_oidc_enabled:
            raise AppError(e.AUTH_PROVIDER_DISABLED, "该登录方式未开放", 400)
        if req.provider == "LOCAL" and not settings.auth_provider_local_enabled:
            raise AppError(e.AUTH_PROVIDER_DISABLED, "该登录方式未开放", 400)

        user = await self.users.get_by_subject(req.external_subject)
        if user is None:
            log.warn("auth.login.denied", code=e.AUTH_INVALID_CREDENTIALS, ip=ip)
            raise e.invalid_credentials()

        if user.status != "ACTIVE":
            raise e.user_disabled()

        cred = await self.users.get_credential(user.id)
        now = _now()
        locked_until = as_utc(cred.locked_until) if cred is not None else None
        if cred is not None and locked_until and locked_until > now:
            raise e.account_locked(cred.locked_until.isoformat())

        if cred is None or not verify_password(req.credential, cred.password_hash):
            if cred is not None:
                cred.failed_attempts += 1
                if cred.failed_attempts >= settings.auth_max_failed_attempts:
                    cred.locked_until = now + timedelta(minutes=settings.auth_lock_minutes)
                    cred.failed_attempts = 0
                    await self.session.commit()
                    log.warn("auth.login.locked", subject_hash=subject_hash(req.external_subject))
                    raise e.account_locked(cred.locked_until.isoformat())
                await self.session.commit()
            log.warn("auth.login.denied", code=e.AUTH_INVALID_CREDENTIALS, ip=ip)
            raise e.invalid_credentials()

        cred.failed_attempts = 0
        cred.locked_until = None

        token = generate_session_token()
        row = IamAuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            issued_at=now,
            expires_at=session_expiry(settings.session_ttl_hours),
        )
        await self.sessions.insert(row)
        await self.users.touch_last_login(user.id, now)
        await self.session.commit()

        projects = await self.projects.list_by_member(user.id, limit=50)
        if row.current_project_id is None and projects:
            await self.sessions.set_project(row, projects[0].id)
            await self.session.commit()

        log.info("auth.login.success", user_id=str(user.id), session_id=str(row.id), project_count=len(projects))

        return LoginResponse(
            session_token=token,
            expires_at=row.expires_at,
            user={"id": user.id, "display_name": user.display_name, "status": user.status},
            projects=[self._brief(p) for p in projects],
        )

    @staticmethod
    def _brief(p) -> dict:
        return {"id": p.id, "code": p.code, "name": p.name, "status": p.status}

    async def logout(self, session_id: uuid.UUID) -> None:
        row = await self.session.get(IamAuthSession, session_id)
        if row is None:
            return
        await self.sessions.revoke(row, _now())
        await self.session.commit()
        log.info("auth.logout", user_id=str(row.user_id), session_id=str(session_id))

    async def resolve_context(self, token: str) -> tuple[RequestContext, IamAuthSession]:
        row = await self.sessions.get_by_token_hash(hash_token(token))
        if row is None:
            raise Unauthorized(e.AUTH_UNAUTHENTICATED, "未登录或会话已失效")
        if row.revoked_at is not None:
            raise Unauthorized(e.AUTH_SESSION_REVOKED, "会话已注销")
        if as_utc(row.expires_at) <= _now():
            raise Unauthorized(e.AUTH_SESSION_EXPIRED, "会话已过期")

        user = await self.users.get(row.user_id)
        if user is None or user.status != "ACTIVE":
            raise Unauthorized(e.AUTH_USER_DISABLED, "账号已停用")

        roles: list[str] = []
        tenant_id: uuid.UUID | None = None
        project_id = row.current_project_id

        if project_id is not None:
            project = await self.projects.get(project_id)
            if project is not None:
                tenant_id = project.tenant_id
                member = await self.members.get_by_project_user(project_id, user.id)
                if member is not None and member.status == "ACTIVE":
                    roles = await self._role_codes(member.id)

        if tenant_id is None:
            projects = await self.projects.list_by_member(user.id, limit=1)
            tenant_id = projects[0].tenant_id if projects else None

        ctx = RequestContext(
            trace_id=new_trace_id(),
            user_id=user.id,
            display_name=user.display_name,
            tenant_id=tenant_id or uuid.UUID(int=0),
            project_id=project_id,
            roles=tuple(roles),
            approval_slots=approval_slots_for(roles),
            capabilities=capabilities_for(roles),
        )
        return ctx, row

    async def _role_codes(self, member_id: uuid.UUID) -> list[str]:
        assignments = await self.roles.list_active_by_member(member_id)
        codes: list[str] = []
        for a in assignments:
            role = await self.role_defs.get_by_id(a.role_id)
            if role is not None:
                codes.append(role.code)
        return codes

    async def build_session_response(self, ctx: RequestContext) -> SessionResponse:
        user = await self.users.get(ctx.user_id)
        tenant = await self.tenants.get(ctx.tenant_id) if ctx.tenant_id else None
        project = await self.projects.get(ctx.project_id) if ctx.project_id else None

        if user is None or tenant is None:
            raise Unauthorized(e.AUTH_UNAUTHENTICATED, "上下文不完整，请重新登录")

        return SessionResponse(
            user={"id": user.id, "display_name": user.display_name, "status": user.status},
            tenant={"id": tenant.id, "code": tenant.code, "name": tenant.name},
            project=self._brief(project) if project else None,
            roles=list(ctx.roles),
            approval_slots=list(ctx.approval_slots),
            capabilities=sorted(ctx.capabilities),
        )

    async def switch_project(self, ctx: RequestContext, session_row: IamAuthSession, project_id: uuid.UUID) -> None:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFound(e.IAM_PROJECT_NOT_FOUND, "项目不存在")
        member = await self.members.get_by_project_user(project_id, ctx.user_id)
        if member is None or member.status != "ACTIVE":
            raise e.not_member()
        await self.sessions.set_project(session_row, project_id)
        await self.session.commit()
        log.info("auth.project.switch", user_id=str(ctx.user_id), to=str(project_id))


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.members = MemberRepository(session)
        self.roles = MemberRoleRepository(session)
        self.role_defs = RoleRepository(session)

    async def create(self, ctx: RequestContext, req: CreateProjectRequest) -> ProjectResponse:
        log.debug("project.create.start", tenant_id=str(ctx.tenant_id), code=req.code)

        existing = await self.projects.get_by_code(ctx.tenant_id, req.code)
        if existing is not None:
            raise Conflict(e.IAM_PROJECT_CODE_CONFLICT, "项目编码在该租户内已存在", {"field": "code"})

        project = IamProject(tenant_id=ctx.tenant_id, code=req.code, name=req.name, status="ACTIVE")
        await self.projects.insert(project)

        member = IamMember(tenant_id=ctx.tenant_id, project_id=project.id, user_id=ctx.user_id, status="ACTIVE")
        await self.members.insert(member)

        admin_role = await self.role_defs.get_by_code(ROLE_PROJECT_ADMIN)
        if admin_role is not None:
            await self.roles.insert(
                IamMemberRole(
                    tenant_id=ctx.tenant_id,
                    project_id=project.id,
                    member_id=member.id,
                    role_id=admin_role.id,
                    assigned_by_user_id=ctx.user_id,
                )
            )

        await self.session.commit()
        log.info("project.create.success", project_id=str(project.id), code=project.code)
        return ProjectResponse.model_validate(project)

    async def list(self, ctx: RequestContext, cursor: int, limit: int) -> list[ProjectResponse]:
        rows = await self.projects.list_by_member(ctx.user_id, cursor=cursor, limit=limit)
        return [ProjectResponse.model_validate(r) for r in rows]

    async def get(self, ctx: RequestContext, project_id: uuid.UUID) -> ProjectResponse:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFound(e.IAM_PROJECT_NOT_FOUND, "项目不存在")
        member = await self.members.get_by_project_user(project_id, ctx.user_id)
        if member is None or member.status != "ACTIVE":
            raise e.not_member()
        return ProjectResponse.model_validate(project)

    async def update(self, ctx: RequestContext, project_id: uuid.UUID, req: UpdateProjectRequest) -> ProjectResponse:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFound(e.IAM_PROJECT_NOT_FOUND, "项目不存在")
        if project.tenant_id != ctx.tenant_id:
            raise e.not_member()
        if project.status == "ARCHIVED" and req.status in {"ACTIVE", "SUSPENDED"}:
            raise AppError("IAM_PROJECT_ARCHIVED_FINAL", "已归档项目不可恢复", 409)
        if req.name is not None:
            project.name = req.name
        if req.status is not None:
            project.status = req.status
        await self.session.commit()
        log.info("project.update", project_id=str(project.id), fields=list(req.model_dump(exclude_none=True)))
        return ProjectResponse.model_validate(project)


class MemberService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.members = MemberRepository(session)
        self.role_assign = MemberRoleRepository(session)
        self.roles = RoleRepository(session)
        self.users = UserRepository(session)
        self.projects = ProjectRepository(session)

    async def _ensure_project(self, ctx: RequestContext, project_id: uuid.UUID) -> IamProject:
        if ctx.project_id is not None and ctx.project_id != project_id:
            raise AppError(e.IAM_SCOPE_MISMATCH, "项目与会话不一致", 409)
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFound(e.IAM_PROJECT_NOT_FOUND, "项目不存在")
        if project.tenant_id != ctx.tenant_id:
            raise e.not_member()
        return project

    async def list(self, ctx: RequestContext, project_id: uuid.UUID, cursor: int, limit: int) -> list[MemberResponse]:
        await self._ensure_project(ctx, project_id)
        rows = await self.members.list_by_project(project_id, cursor=cursor, limit=limit)
        return [await self._to_response(m) for m in rows]

    async def _to_response(self, member: IamMember) -> MemberResponse:
        user = await self.users.get(member.user_id)
        assignments = await self.role_assign.list_active_by_member(member.id)
        role_briefs: list[RoleBrief] = []
        for a in assignments:
            role = await self.roles.get_by_id(a.role_id)
            if role is not None:
                role_briefs.append(
                    RoleBrief(code=role.code, name=role.name, is_business_approval_role=role.is_business_approval_role)
                )
        return MemberResponse(
            id=member.id,
            user_id=member.user_id,
            display_name=user.display_name if user else "-",
            email_masked=user.email_masked if user else None,
            roles=role_briefs,
            status=member.status,
            last_login_at=user.last_login_at if user else None,
        )

    async def invite(self, ctx: RequestContext, project_id: uuid.UUID, req: InviteMemberRequest) -> MemberResponse:
        await self._ensure_project(ctx, project_id)

        # 先校验角色组合，再落库：避免成员已创建但角色被拒的半成品状态
        requested: list[str] = []
        for code in req.role_codes:
            if not is_known_role(code):
                raise e.role_unknown(code)
            conflict = duty_conflict(requested, code)
            if conflict is not None:
                raise e.duty_conflict(conflict[0], conflict[1], duty_conflict_reason(*conflict))
            requested.append(code)

        user = await self.users.get_by_subject(req.external_subject)
        if user is None:
            raise NotFound(e.IAM_USER_NOT_FOUND, "该账号尚未加入平台")

        existing = await self.members.get_by_project_user(project_id, user.id)
        if existing is not None and existing.status == "ACTIVE":
            raise Conflict(e.IAM_MEMBER_EXISTS, "该成员已在项目中")

        if existing is not None:
            existing.status = "ACTIVE"
            member = existing
        else:
            member = await self.members.insert(
                IamMember(tenant_id=ctx.tenant_id, project_id=project_id, user_id=user.id, status="ACTIVE")
            )

        for code in req.role_codes:
            if not is_known_role(code):
                raise e.role_unknown(code)
            role = await self.roles.get_by_code(code)
            if role is None:
                raise e.role_unknown(code)
            await self.role_assign.insert(
                IamMemberRole(
                    tenant_id=ctx.tenant_id,
                    project_id=project_id,
                    member_id=member.id,
                    role_id=role.id,
                    assigned_by_user_id=ctx.user_id,
                )
            )

        await self.session.commit()
        log.info("member.invite.success", project_id=str(project_id), member_id=str(member.id), user_id=str(user.id))
        return await self._to_response(member)

    async def update_status(self, ctx: RequestContext, project_id: uuid.UUID, member_id: uuid.UUID, status: str) -> MemberResponse:
        await self._ensure_project(ctx, project_id)
        member = await self.members.get(member_id)
        if member is None or member.project_id != project_id:
            raise e.member_not_found()

        previous = member.status
        member.status = status
        if status == "REMOVED":
            await self.role_assign.expire_all_of_member(member.id, _now())
        await self.session.commit()
        log.info("member.status.change", member_id=str(member_id), previous=previous, current=status)
        return await self._to_response(member)

    async def assign_role(self, ctx: RequestContext, project_id: uuid.UUID, member_id: uuid.UUID, req: AssignRoleRequest) -> MemberResponse:
        await self._ensure_project(ctx, project_id)

        if not is_known_role(req.role_code):
            raise e.role_unknown(req.role_code)

        member = await self.members.get(member_id)
        if member is None or member.project_id != project_id:
            raise e.member_not_found()
        if member.status != "ACTIVE":
            raise e.member_inactive()

        role = await self.roles.get_by_code(req.role_code)
        if role is None:
            raise e.role_unknown(req.role_code)

        active = await self.role_assign.get_active(member_id, role.id)
        if active is not None:
            raise e.already_assigned()

        held = await self._active_role_codes(member_id)
        conflict = duty_conflict(held, req.role_code)
        if conflict is not None:
            raise e.duty_conflict(conflict[0], conflict[1], duty_conflict_reason(*conflict))

        assignment = IamMemberRole(
            tenant_id=ctx.tenant_id,
            project_id=project_id,
            member_id=member_id,
            role_id=role.id,
            valid_from=req.valid_from or _now(),
            assigned_by_user_id=ctx.user_id,
        )
        await self.role_assign.insert(assignment)
        await self.session.commit()

        log.info(
            "member.role.assign.success",
            member_id=str(member_id),
            role_code=req.role_code,
            assignment_id=str(assignment.id),
        )

        codes = [r.code for r in (await self._to_response(member)).roles]
        if "MAKER" in codes and ({"CHECKER_DATA", "CHECKER_SECURITY"} & set(codes)):
            log.warn("member.role.separation_notice", member_id=str(member_id), roles=codes)

        return await self._to_response(member)

    async def _active_role_codes(self, member_id: uuid.UUID) -> list[str]:
        assignments = await self.role_assign.list_active_by_member(member_id)
        codes: list[str] = []
        for a in assignments:
            role = await self.roles.get_by_id(a.role_id)
            if role is not None:
                codes.append(role.code)
        return codes

    async def revoke_role(self, ctx: RequestContext, project_id: uuid.UUID, member_id: uuid.UUID, assignment_id: uuid.UUID) -> MemberResponse:
        await self._ensure_project(ctx, project_id)
        assignment = await self.role_assign.get(assignment_id)
        if assignment is None or assignment.member_id != member_id or assignment.project_id != project_id:
            raise NotFound(e.IAM_ASSIGNMENT_NOT_FOUND, "角色分配记录不存在")
        await self.role_assign.expire(assignment, _now())
        await self.session.commit()
        log.info("member.role.revoke", member_id=str(member_id), assignment_id=str(assignment_id))
        member = await self.members.get(member_id)
        return await self._to_response(member)

    async def list_roles(self) -> list[RoleBrief]:
        rows = await self.roles.list_all()
        return [
            RoleBrief(code=r.code, name=r.name, is_business_approval_role=r.is_business_approval_role)
            for r in rows
        ]
