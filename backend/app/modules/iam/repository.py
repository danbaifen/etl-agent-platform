from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.models import (
    IamAuthSession,
    IamMember,
    IamMemberRole,
    IamProject,
    IamRole,
    IamTenant,
    IamUser,
    IamUserCredential,
)


class TenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: uuid.UUID) -> IamTenant | None:
        return await self.session.get(IamTenant, tenant_id)

    async def get_by_code(self, code: str) -> IamTenant | None:
        return (await self.session.execute(select(IamTenant).where(IamTenant.code == code))).scalar_one_or_none()


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID) -> IamUser | None:
        return await self.session.get(IamUser, user_id)

    async def get_by_subject(self, subject: str) -> IamUser | None:
        stmt = select(IamUser).where(IamUser.external_subject == subject)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def touch_last_login(self, user_id: uuid.UUID, at: datetime) -> None:
        await self.session.execute(update(IamUser).where(IamUser.id == user_id).values(last_login_at=at))

    async def get_credential(self, user_id: uuid.UUID) -> IamUserCredential | None:
        return await self.session.get(IamUserCredential, user_id)

    async def save_credential(self, cred: IamUserCredential) -> None:
        self.session.add(cred)


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, project_id: uuid.UUID) -> IamProject | None:
        return await self.session.get(IamProject, project_id)

    async def get_by_code(self, tenant_id: uuid.UUID, code: str) -> IamProject | None:
        stmt = select(IamProject).where(IamProject.tenant_id == tenant_id, IamProject.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_member(
        self, user_id: uuid.UUID, cursor: int = 0, limit: int = 20
    ) -> list[IamProject]:
        stmt = (
            select(IamProject)
            .join(IamMember, IamMember.project_id == IamProject.id)
            .where(IamMember.user_id == user_id, IamMember.status == "ACTIVE")
            .order_by(IamProject.created_at.asc())
            .offset(cursor)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def insert(self, project: IamProject) -> IamProject:
        self.session.add(project)
        await self.session.flush()
        return project


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, role_id: uuid.UUID) -> IamRole | None:
        return await self.session.get(IamRole, role_id)

    async def get_by_code(self, code: str) -> IamRole | None:
        return (await self.session.execute(select(IamRole).where(IamRole.code == code))).scalar_one_or_none()

    async def list_all(self) -> list[IamRole]:
        return list((await self.session.execute(select(IamRole).order_by(IamRole.code))).scalars())


class MemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, member_id: uuid.UUID) -> IamMember | None:
        return await self.session.get(IamMember, member_id)

    async def get_by_project_user(self, project_id: uuid.UUID, user_id: uuid.UUID) -> IamMember | None:
        stmt = select(IamMember).where(IamMember.project_id == project_id, IamMember.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_project(
        self, project_id: uuid.UUID, cursor: int = 0, limit: int = 20, include_removed: bool = False
    ) -> list[IamMember]:
        stmt = select(IamMember).where(IamMember.project_id == project_id)
        if not include_removed:
            stmt = stmt.where(IamMember.status == "ACTIVE")
        stmt = stmt.order_by(IamMember.created_at.asc()).offset(cursor).limit(limit)
        return list((await self.session.execute(stmt)).scalars())

    async def count_by_project(self, project_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(IamMember).where(
            IamMember.project_id == project_id, IamMember.status == "ACTIVE"
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def insert(self, member: IamMember) -> IamMember:
        self.session.add(member)
        await self.session.flush()
        return member

    async def set_status(self, member: IamMember, status: str) -> None:
        member.status = status


class MemberRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active_by_member(self, member_id: uuid.UUID) -> list[IamMemberRole]:
        stmt = select(IamMemberRole).where(
            IamMemberRole.member_id == member_id, IamMemberRole.valid_to.is_(None)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_active(self, member_id: uuid.UUID, role_id: uuid.UUID) -> IamMemberRole | None:
        stmt = select(IamMemberRole).where(
            IamMemberRole.member_id == member_id,
            IamMemberRole.role_id == role_id,
            IamMemberRole.valid_to.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get(self, assignment_id: uuid.UUID) -> IamMemberRole | None:
        return await self.session.get(IamMemberRole, assignment_id)

    async def insert(self, assignment: IamMemberRole) -> IamMemberRole:
        self.session.add(assignment)
        await self.session.flush()
        return assignment

    async def expire(self, assignment: IamMemberRole, at: datetime) -> None:
        assignment.valid_to = at

    async def expire_all_of_member(self, member_id: uuid.UUID, at: datetime) -> None:
        await self.session.execute(
            update(IamMemberRole)
            .where(IamMemberRole.member_id == member_id, IamMemberRole.valid_to.is_(None))
            .values(valid_to=at)
        )


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_token_hash(self, token_hash: str) -> IamAuthSession | None:
        stmt = select(IamAuthSession).where(IamAuthSession.token_hash == token_hash)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def insert(self, session_row: IamAuthSession) -> IamAuthSession:
        self.session.add(session_row)
        await self.session.flush()
        return session_row

    async def revoke(self, session_row: IamAuthSession, at: datetime) -> None:
        session_row.revoked_at = at

    async def set_project(self, session_row: IamAuthSession, project_id: uuid.UUID) -> None:
        session_row.current_project_id = project_id
