from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.core.db import get_session_factory
from app.core.security import hash_password
from app.modules.iam.models import (
    IamMember,
    IamMemberRole,
    IamProject,
    IamRole,
    IamTenant,
    IamUser,
    IamUserCredential,
)
from app.modules.iam.roles import ROLES

SEED_ROLES = [
    (code, d.name, d.is_business_approval_role) for code, d in ROLES.items()
]


async def seed(tenant_code: str, project_code: str, subject: str, role_code: str, password: str, display: str) -> None:
    async with get_session_factory()() as s:
        tenant = (await s.execute(select(IamTenant).where(IamTenant.code == tenant_code))).scalar_one_or_none()
        if tenant is None:
            tenant = IamTenant(code=tenant_code, name=f"{tenant_code} 租户", status="ACTIVE")
            s.add(tenant)
            await s.flush()

        for code, name, is_biz in SEED_ROLES:
            exists = (await s.execute(select(IamRole).where(IamRole.code == code))).scalar_one_or_none()
            if exists is None:
                s.add(IamRole(code=code, name=name, scope="PROJECT", is_business_approval_role=is_biz))
        await s.flush()

        project = (
            await s.execute(
                select(IamProject).where(IamProject.tenant_id == tenant.id, IamProject.code == project_code)
            )
        ).scalar_one_or_none()
        if project is None:
            project = IamProject(tenant_id=tenant.id, code=project_code, name=f"{project_code} 项目", status="ACTIVE")
            s.add(project)
            await s.flush()

        user = (await s.execute(select(IamUser).where(IamUser.external_subject == subject))).scalar_one_or_none()
        if user is None:
            user = IamUser(external_subject=subject, display_name=display, status="ACTIVE")
            s.add(user)
            await s.flush()
            s.add(IamUserCredential(user_id=user.id, password_hash=hash_password(password), failed_attempts=0))
        await s.flush()

        member = (
            await s.execute(
                select(IamMember).where(IamMember.project_id == project.id, IamMember.user_id == user.id)
            )
        ).scalar_one_or_none()
        if member is None:
            member = IamMember(tenant_id=tenant.id, project_id=project.id, user_id=user.id, status="ACTIVE")
            s.add(member)
            await s.flush()

        role = (await s.execute(select(IamRole).where(IamRole.code == role_code))).scalar_one_or_none()
        if role is None:
            raise SystemExit(f"未知角色：{role_code}")

        granted = (
            await s.execute(
                select(IamMemberRole).where(
                    IamMemberRole.member_id == member.id,
                    IamMemberRole.role_id == role.id,
                    IamMemberRole.valid_to.is_(None),
                )
            )
        ).scalar_one_or_none()
        if granted is None:
            s.add(
                IamMemberRole(
                    tenant_id=tenant.id,
                    project_id=project.id,
                    member_id=member.id,
                    role_id=role.id,
                    assigned_by_user_id=user.id,
                )
            )

        await s.commit()
        print(f"seed ok: tenant={tenant_code} project={project_code} user={subject} role={role_code}")


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化租户、项目、用户与角色")
    parser.add_argument("--tenant", default="acme")
    parser.add_argument("--project", default="crm-sync")
    parser.add_argument("--user", default="local:zhanglan")
    parser.add_argument("--role", default="PROJECT_ADMIN")
    parser.add_argument("--password", default="CorrectHorseBattery")
    parser.add_argument("--display", default="张岚")
    args = parser.parse_args()

    asyncio.run(seed(args.tenant, args.project, args.user, args.role, args.password, args.display))


if __name__ == "__main__":
    main()
