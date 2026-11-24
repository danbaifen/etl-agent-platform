"""演示环境种子：建两个 SQLite 数据仓库、登记连接、邀请四个角色、建 Benchmark 套件。

跑法：
    python -m app.scripts.seed_demo --data-dir ./var/demo

数据面是真实可读写的 SQLite 文件，执行阶段真的会往影子表里写行、真的做表改名 Swap，
因此「读取行数 / 写入字节 / 拒绝率」都是实测值，不是编出来的。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3

from sqlalchemy import select

from app import models_registry  # noqa: F401
from app.core.context import RequestContext
from app.core.db import get_session_factory
from app.core.security import hash_password
from app.modules.asset.models import AssetConnection, AssetSecretRef
from app.modules.bench.models import BenchSuite
from app.modules.bench.service import BenchService
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

SOURCE_ROWS = [
    # 一行正常、一行主键为空、一行金额是脏字符串、其余正常
    (1001, "张岚", "13800001111", "zhanglan@example.com", "2026-11-01", 1280.50, "PAID"),
    (1002, "李维", "13900002222", "liwei@example.com", "2026-11-02", 640.00, "PAID"),
    (None, "脏数据", "13700003333", "bad@example.com", "2026-11-03", 99.00, "NEW"),
    (1004, "王策", "13600004444", "wangce@example.com", "2026-11-04", "abc", "PAID"),
    (1005, "陈默", "13500005555", "chenmo@example.com", "2026-11-05", 320.75, "REFUND"),
    (1006, "周昕", "13400006666", "zhouxin@example.com", "2026-11-06", 88.00, "PAID"),
    (1007, "孙迪", "13300007777", "sundi@example.com", "2026-11-07", 1520.00, "PAID"),
    (1008, "何静", "13200008888", "hejing@example.com", "2026-11-08", 210.30, "NEW"),
    (1009, "刘阳", "13100009999", "liuyang@example.com", "2026-11-09", 980.00, "PAID"),
    (1010, "赵敏", "13000001010", "zhaomin@example.com", "2026-11-10", 45.60, "NEW"),
    (1011, "钱峰", "18900001111", "qianfeng@example.com", "2026-11-11", 760.20, "PAID"),
    (1012, "吴楠", "18800001212", "wunan@example.com", "2026-11-12", 1320.00, "REFUND"),
]


def build_warehouse(data_dir: str) -> tuple[str, str]:
    os.makedirs(data_dir, exist_ok=True)
    source_path = os.path.join(data_dir, "source.db")
    target_path = os.path.join(data_dir, "target.db")

    conn = sqlite3.connect(source_path)
    conn.execute("DROP TABLE IF EXISTS crm_customer")
    conn.execute(
        """
        CREATE TABLE crm_customer (
            customer_id INTEGER,
            customer_name TEXT,
            phone TEXT,
            email TEXT,
            signup_date TEXT,
            amount REAL,
            status TEXT
        )
        """
    )
    conn.executemany("INSERT INTO crm_customer VALUES (?, ?, ?, ?, ?, ?, ?)", SOURCE_ROWS)
    conn.execute("DROP TABLE IF EXISTS log_event")
    conn.execute(
        """
        CREATE TABLE log_event (
            event_id INTEGER,
            user_id INTEGER,
            page TEXT,
            duration_ms REAL,
            event_time TEXT
        )
        """
    )
    # 日志表故意做成高脏数据率：源端格式突发变更导致多行无法解析
    conn.executemany(
        "INSERT INTO log_event VALUES (?, ?, ?, ?, ?)",
        [
            (1, 1001, "/order/list", 320.5, "2026-11-20 10:00:01"),
            (2, 1002, "/order/detail", 128.0, "2026-11-20 10:00:03"),
            (3, 1003, "/cart", "unknown", "2026-11-20 10:00:05"),
            (4, 1004, "/pay", "N/A", "2026-11-20 10:00:07"),
            (None, 1005, "/pay", 88.0, "2026-11-20 10:00:09"),
            (6, None, "/order/list", 44.0, "2026-11-20 10:00:11"),
            (7, 1007, "/cart", "timeout", "2026-11-20 10:00:13"),
            (8, 1008, "/pay", 512.25, "2026-11-20 10:00:15"),
            (None, None, "/error", "-", "2026-11-20 10:00:17"),
            (10, 1010, "/order/list", 76.5, "2026-11-20 10:00:19"),
        ],
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(target_path)
    conn.execute("DROP TABLE IF EXISTS ads_customer")
    conn.execute(
        """
        CREATE TABLE ads_customer (
            customer_id INTEGER,
            customer_name TEXT,
            phone TEXT,
            email TEXT,
            signup_date TEXT,
            amount REAL,
            status TEXT
        )
        """
    )
    conn.execute("DROP TABLE IF EXISTS ads_log")
    conn.execute(
        """
        CREATE TABLE ads_log (
            event_id INTEGER,
            user_id INTEGER,
            page TEXT,
            duration_ms REAL,
            event_time TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return source_path, target_path


async def seed(data_dir: str, password: str) -> None:
    source_path, target_path = build_warehouse(data_dir)

    async with get_session_factory()() as session:
        tenant = (await session.execute(select(IamTenant).where(IamTenant.code == "acme"))).scalar_one_or_none()
        if tenant is None:
            tenant = IamTenant(code="acme", name="Acme 数据平台", status="ACTIVE")
            session.add(tenant)
            await session.flush()

        for code, definition in ROLES.items():
            exists = (await session.execute(select(IamRole).where(IamRole.code == code))).scalar_one_or_none()
            if exists is None:
                session.add(
                    IamRole(
                        code=code,
                        name=definition.name,
                        scope="PROJECT",
                        is_business_approval_role=definition.is_business_approval_role,
                    )
                )
        await session.flush()
        roles = {r.code: r for r in (await session.execute(select(IamRole))).scalars().all()}

        project = (
            await session.execute(
                select(IamProject).where(IamProject.tenant_id == tenant.id, IamProject.code == "crm-sync")
            )
        ).scalar_one_or_none()
        if project is None:
            project = IamProject(
                tenant_id=tenant.id, code="crm-sync", name="CRM 订单宽表同步", status="ACTIVE"
            )
            session.add(project)
            await session.flush()

        accounts = [
            ("local:zhanglan", "张岚", "MAKER"),
            ("local:liwei", "李维", "CHECKER_DATA"),
            ("local:wangce", "王策", "CHECKER_SECURITY"),
            ("local:chenmo", "陈默", "OPERATOR"),
            ("local:zhouxin", "周昕", "AUDITOR"),
        ]
        users: dict[str, IamUser] = {}
        for subject, display, role_code in accounts:
            user = (
                await session.execute(select(IamUser).where(IamUser.external_subject == subject))
            ).scalar_one_or_none()
            if user is None:
                user = IamUser(
                    external_subject=subject,
                    display_name=display,
                    email_masked=subject.split(":")[-1][:2] + "***@example.com",
                    status="ACTIVE",
                )
                session.add(user)
                await session.flush()
                session.add(
                    IamUserCredential(user_id=user.id, password_hash=hash_password(password), failed_attempts=0)
                )
            users[subject] = user

            member = (
                await session.execute(
                    select(IamMember).where(
                        IamMember.project_id == project.id, IamMember.user_id == user.id
                    )
                )
            ).scalar_one_or_none()
            if member is None:
                member = IamMember(
                    tenant_id=tenant.id, project_id=project.id, user_id=user.id, status="ACTIVE"
                )
                session.add(member)
                await session.flush()
            granted = (
                await session.execute(
                    select(IamMemberRole).where(
                        IamMemberRole.member_id == member.id,
                        IamMemberRole.role_id == roles[role_code].id,
                        IamMemberRole.valid_to.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if granted is None:
                session.add(
                    IamMemberRole(
                        tenant_id=tenant.id,
                        project_id=project.id,
                        member_id=member.id,
                        role_id=roles[role_code].id,
                        assigned_by_user_id=user.id,
                    )
                )
        await session.flush()

        maker = users["local:zhanglan"]
        ctx = RequestContext(
            trace_id="seed",
            user_id=maker.id,
            display_name=maker.display_name,
            tenant_id=tenant.id,
            project_id=project.id,
        )

        secret = (
            await session.execute(select(AssetSecretRef).where(AssetSecretRef.project_id == project.id))
        ).scalars().first()
        if secret is None:
            secret = AssetSecretRef(
                tenant_id=tenant.id,
                project_id=project.id,
                name="crm-prod-secret",
                provider="VAULT",
                vault_path=f"kv/etl/{project.id}/crm-prod",
                vault_version=1,
                status="ACTIVE",
            )
            session.add(secret)
            await session.flush()

        connections = [
            ("CRM 生产库", "SQLITE", "PROD", source_path, secret.id),
            ("Doris 生产仓", "SQLITE", "PROD", target_path, secret.id),
            ("本地开发库", "SQLITE", "DEV", source_path, None),
        ]
        for name, ctype, env, path, secret_id in connections:
            exists = (
                await session.execute(
                    select(AssetConnection).where(
                        AssetConnection.project_id == project.id, AssetConnection.name == name
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(
                    AssetConnection(
                        tenant_id=tenant.id,
                        project_id=project.id,
                        name=name,
                        connection_type=ctype,
                        environment=env,
                        safe_config={"database_path": path.replace("\\", "/"), "dialect_note": "SQLite 演示仓库"},
                        secret_ref_id=secret_id,
                        status="ACTIVE",
                        created_by_user_id=maker.id,
                    )
                )

        has_suite = (
            await session.execute(select(BenchSuite).where(BenchSuite.project_id == project.id))
        ).scalars().first()
        await session.commit()

        if has_suite is None:
            async with get_session_factory()() as fresh:
                await BenchService(fresh).seed_default_suite(ctx)

        print("seed_demo ok")
        print(f"  source db : {source_path}")
        print(f"  target db : {target_path}")
        print(f"  project   : {project.code} ({project.id})")
        print(f"  accounts  : {', '.join(a[0] for a in accounts)} / 密码 {password}")


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化演示环境")
    parser.add_argument("--data-dir", default="./var/demo")
    parser.add_argument("--password", default="DemoPass!2026")
    args = parser.parse_args()
    asyncio.run(seed(args.data_dir, args.password))


if __name__ == "__main__":
    main()
