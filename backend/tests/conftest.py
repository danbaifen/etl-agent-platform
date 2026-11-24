"""验收测试公共夹具。

每个用例独立建库：`seeded` 是函数级夹具，跑在临时 SQLite 文件上。
方言差异（UUID 类型、部分唯一索引）已在模型层用通用类型 + sqlite_where 抹平，
因此同一份约束语义在 SQLite 与 PostgreSQL 上都成立。
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator, Callable

import pytest

_TMP = tempfile.mkdtemp(prefix="etl-acceptance-")
_DB_PATH = os.path.join(_TMP, "acceptance.db")

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_DB_PATH}")
os.environ.setdefault("IDEMPOTENCY_BACKEND", "memory")
os.environ.setdefault("LOG_FORMAT", "console")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core import idempotency  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import (  # noqa: E402
    Base,
    configure_database,
    dispose_database,
    get_engine,
    get_session_factory,
)
from app.core.security import hash_password  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.iam import models as m  # noqa: E402
from app.modules.iam.roles import ROLES  # noqa: E402
from tests.helpers import ACCOUNTS, DISPLAY_NAMES, PASSWORD  # noqa: E402


@pytest.fixture(scope="session")
def app():
    get_settings.cache_clear()
    idempotency.reset_store()
    return create_app()


@pytest.fixture
async def seeded(app) -> AsyncIterator[dict]:
    configure_database(os.environ["DATABASE_URL"])
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    factory = get_session_factory()
    async with factory() as session:
        tenant = m.IamTenant(code="acme", name="Acme 数据平台", status="ACTIVE")
        session.add(tenant)
        await session.flush()

        role_rows: dict[str, m.IamRole] = {}
        for code, definition in ROLES.items():
            row = m.IamRole(
                code=code,
                name=definition.name,
                scope="PROJECT",
                is_business_approval_role=definition.is_business_approval_role,
            )
            session.add(row)
            role_rows[code] = row
        await session.flush()

        users: dict[str, m.IamUser] = {}
        for key, subject in ACCOUNTS.items():
            user = m.IamUser(
                external_subject=subject,
                display_name=DISPLAY_NAMES[key],
                email_masked=subject.split("@")[0][:2] + "***@example.com",
                status="ACTIVE",
            )
            session.add(user)
            await session.flush()
            session.add(
                m.IamUserCredential(
                    user_id=user.id, password_hash=hash_password(PASSWORD), failed_attempts=0
                )
            )
            users[key] = user

        project = m.IamProject(tenant_id=tenant.id, code="etl-demo", name="订单宽表集成", status="ACTIVE")
        session.add(project)
        await session.flush()

        admin_member = m.IamMember(
            tenant_id=tenant.id,
            project_id=project.id,
            user_id=users["admin"].id,
            status="ACTIVE",
        )
        session.add(admin_member)
        await session.flush()
        session.add(
            m.IamMemberRole(
                tenant_id=tenant.id,
                project_id=project.id,
                member_id=admin_member.id,
                role_id=role_rows["PROJECT_ADMIN"].id,
                assigned_by_user_id=users["admin"].id,
            )
        )
        await session.commit()

        data = {
            "tenant_id": tenant.id,
            "project_id": project.id,
            "project_code": project.code,
            "roles": role_rows,
            "users": users,
            "admin_member_id": admin_member.id,
        }

    yield data

    await dispose_database()


@pytest.fixture
async def make_client(app) -> AsyncIterator[Callable[[], AsyncClient]]:
    """工厂：每次调用返回独立 cookie 的客户端，用于模拟多个登录主体。"""
    created: list[AsyncClient] = []

    def _make() -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        created.append(c)
        return c

    yield _make

    for c in created:
        await c.aclose()


@pytest.fixture
async def client(make_client) -> AsyncClient:
    return make_client()


@pytest.fixture
async def as_admin(client, seeded) -> AsyncClient:
    from tests.helpers import login

    await login(client, "admin")
    return client
