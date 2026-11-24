# 生产级 ETL-Agent 数据集成平台 身份与租户 后端 SPEC

## 1. 文档说明

### 1.1 文档目的

本文档是 M01 身份与租户模块的后端实现规格，编码人员可据此直接产出代码，无需再回看概要设计。内容基于《生产级 ETL-Agent 数据集成平台 概要设计》第 4 章模块划分与《ETL-Agent平台-数据实体设计》第 4.1、5.1–5.3 节编写。

本模块只解决三件事：**证明你是谁**（认证与会话）、**你在哪个项目里**（租户与项目隔离）、**你在项目里担什么角色**（成员与角色分配）。审批槽位是否满足职责分离、某次提交能否被审批，属于 M07 Harness 内核的判定范围，本模块只提供角色事实，不做业务裁决。

### 1.2 适用范围

| 范围 | 内容 |
| --- | --- |
| 后端包路径 | `apps/api/app/modules/iam/`、`apps/api/app/core/context.py` |
| 数据库表 | `iam_tenant`、`iam_user`、`iam_project`、`iam_role`、`iam_member`、`iam_member_role`、`iam_auth_session` |
| 对外接口 | `/api/v1/auth/*`、`/api/v1/projects/*` |
| 前端页面 | 登录页、成员与设置页（详见《前端SPEC.md》） |
| 不覆盖 | 角色权限矩阵的策略化（M12）、审批槽位判定（M07）、企业 SSO 对接（TBD-03 未冻结） |

### 1.3 相关文档

| 文档 | 路径 | 说明 |
| --- | --- | --- |
| 项目要求 | `1_PRD/生产级 ETL-Agent 数据集成平台-项目要求.md` | 原始需求基线，冲突时以此为准 |
| PRD | `1_PRD/ETL-Agent平台-PRD.md` | 角色定义、登录与成员管理需求 |
| 概要设计 | `3_概要设计/生产级 ETL-Agent 数据集成平台-概要设计.md` | 模块划分、接口约定、安全设计 |
| 数据实体设计 | `3_概要设计/ETL-Agent平台-数据实体设计.md` | 表结构、通用列、不可变边界 |
| 开发规范 | `4_开发规范/ETL-Agent平台-开发规范.md` | 分层、命名、错误码、日志 |
| 关联 SPEC | `5_各个模块的文档/2_凭据与连接/后端SPEC.md` | 依赖本模块输出的请求上下文 |

---

## 2. 模块概览

### 2.1 模块定位

身份与租户模块是控制面的入口守卫，所有后续模块通过它产出的 `RequestContext` 获得租户、项目、用户与角色信息。它负责认证、服务端会话、项目隔离与成员角色分配，是「谁在什么项目里、以什么身份」这一事实的唯一来源。

### 2.2 依赖关系

```
                      ┌──────────────────────────────┐
                      │  前端（登录页 / 成员设置页）    │
                      └───────────────┬──────────────┘
                                      │ /api/v1/auth, /api/v1/projects
                                      ▼
┌─────────────────────────────────────────────────────────────┐
│ M01 身份与租户                                                │
│  AuthService / ProjectService / MemberService                 │
│  产出 RequestContext(user, tenant, project, roles, caps)      │
└───────┬──────────────────┬──────────────────┬────────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
   PostgreSQL          Redis(会话黑名单)    审计（M11）
   iam_* 七张表          revoke 缓存         IAM_* 事件异步写入

下游消费方：
  M02 连接与凭据   —— 用 project_id / actor_id 做归属与责任记录
  M03–M10 全部模块 —— 用 RequestContext 做隔离与操作主体
  M07 Harness      —— 读取角色事实，判定审批槽位与职责分离
  M11 审计         —— 接收登录、成员变更、角色变更事件
```

---

## 3. 目录与文件放置

### 3.1 后端目录结构

```
apps/api/app/
├── core/
│   ├── context.py              # RequestContext 定义与获取
│   ├── security.py             # 会话令牌生成/校验、密码哈希
│   ├── errors.py               # 错误基类（被全模块复用）
│   └── idempotency.py          # Idempotency-Key 校验装饰器
└── modules/iam/
    ├── __init__.py
    ├── router.py               # /api/v1/auth/*, /api/v1/projects/*
    ├── schemas.py              # Pydantic v2 请求/响应模型
    ├── service.py              # AuthService / ProjectService / MemberService
    ├── repository.py           # 七个表的数据访问
    ├── models.py               # SQLAlchemy ORM 映射
    ├── deps.py                 # get_request_context 依赖注入
    ├── errors.py               # IAM 域错误码
    └── roles.py                # 角色基线常量与能力映射
```

### 3.2 前端目录结构

```
web/src/
├── api/iam.ts                    # 本模块接口封装
├── types/iam.ts                  # 与本文档字段一一对应的类型
├── stores/auth.ts                # 会话与能力清单
├── views/iam/LoginView.vue
├── views/iam/MemberSettingsView.vue
├── components/iam/InviteMemberDrawer.vue
├── components/iam/AssignRoleDialog.vue
├── components/iam/RoleTag.vue
└── directives/capability.ts      # v-capability
```

前端只消费本模块的路由与响应字段，具体页面结构见《前端SPEC.md》。

---

## 4. 数据库设计

### 4.1 `iam_tenant` 租户

| 字段名 | 中文名 | 类型 | 主键 | 非空 | 描述 |
| --- | --- | --- | --- | --- | --- |
| id | 租户 ID | uuid | 是 | 是 | 应用生成 UUIDv7 |
| code | 租户编码 | varchar(64) | 否 | 是 | 全局唯一，小写字母数字连字符 |
| name | 租户名称 | varchar(128) | 否 | 是 | 展示名 |
| status | 状态 | varchar(24) | 否 | 是 | ACTIVE / SUSPENDED |
| created_at | 创建时间 | timestamptz | 否 | 是 | UTC |
| updated_at | 更新时间 | timestamptz | 否 | 是 | UTC |

```sql
CREATE TABLE iam_tenant (
  id          uuid PRIMARY KEY,
  code        varchar(64) NOT NULL,
  name        varchar(128) NOT NULL,
  status      varchar(24) NOT NULL DEFAULT 'ACTIVE',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_iam_tenant_code UNIQUE (code),
  CONSTRAINT ck_iam_tenant_status CHECK (status IN ('ACTIVE','SUSPENDED')),
  CONSTRAINT ck_iam_tenant_code_format CHECK (code ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$')
);
COMMENT ON TABLE iam_tenant IS '租户边界';
COMMENT ON COLUMN iam_tenant.code IS '租户编码，全局唯一';
```

### 4.2 `iam_user` 用户

| 字段名 | 中文名 | 类型 | 主键 | 非空 | 描述 |
| --- | --- | --- | --- | --- | --- |
| id | 用户 ID | uuid | 是 | 是 | |
| external_subject | 认证主体标识 | varchar(256) | 否 | 是 | 来自认证源，全局唯一 |
| display_name | 展示名 | varchar(128) | 否 | 是 | |
| email_masked | 脱敏邮箱 | varchar(256) | 否 | 否 | 只存脱敏值，不存明文 |
| status | 状态 | varchar(24) | 否 | 是 | ACTIVE / DISABLED |
| last_login_at | 最近登录 | timestamptz | 否 | 否 | |
| created_at | 创建时间 | timestamptz | 否 | 是 | |
| updated_at | 更新时间 | timestamptz | 否 | 是 | |

```sql
CREATE TABLE iam_user (
  id                uuid PRIMARY KEY,
  external_subject  varchar(256) NOT NULL,
  display_name      varchar(128) NOT NULL,
  email_masked      varchar(256),
  status            varchar(24) NOT NULL DEFAULT 'ACTIVE',
  last_login_at     timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_iam_user_subject UNIQUE (external_subject),
  CONSTRAINT ck_iam_user_status CHECK (status IN ('ACTIVE','DISABLED'))
);
COMMENT ON TABLE iam_user IS '平台用户主体';
COMMENT ON COLUMN iam_user.external_subject IS '认证主体标识，整体唯一，如 oidc:sub 或 local:工号';
COMMENT ON COLUMN iam_user.email_masked IS '仅存脱敏值，禁止写入明文邮箱';
```

### 4.3 `iam_project` 项目

| 字段名 | 中文名 | 类型 | 主键 | 非空 | 描述 |
| --- | --- | --- | --- | --- | --- |
| id | 项目 ID | uuid | 是 | 是 | |
| tenant_id | 租户 ID | uuid | 否 | 是 | 引用 `iam_tenant.id` |
| code | 项目编码 | varchar(64) | 否 | 是 | 租户内唯一 |
| name | 项目名称 | varchar(128) | 否 | 是 | |
| status | 状态 | varchar(24) | 否 | 是 | ACTIVE / SUSPENDED / ARCHIVED |
| created_at | 创建时间 | timestamptz | 否 | 是 | |
| updated_at | 更新时间 | timestamptz | 否 | 是 | |

```sql
CREATE TABLE iam_project (
  id          uuid PRIMARY KEY,
  tenant_id   uuid NOT NULL REFERENCES iam_tenant(id),
  code        varchar(64) NOT NULL,
  name        varchar(128) NOT NULL,
  status      varchar(24) NOT NULL DEFAULT 'ACTIVE',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_iam_project_code UNIQUE (tenant_id, code),
  CONSTRAINT ck_iam_project_status CHECK (status IN ('ACTIVE','SUSPENDED','ARCHIVED'))
);
CREATE INDEX ix_iam_project_list ON iam_project (tenant_id, status, updated_at DESC);
COMMENT ON TABLE iam_project IS '项目与隔离边界';
```

### 4.4 `iam_role` 角色

| 字段名 | 中文名 | 类型 | 主键 | 非空 | 描述 |
| --- | --- | --- | --- | --- | --- |
| id | 角色 ID | uuid | 是 | 是 | |
| code | 角色编码 | varchar(64) | 否 | 是 | 见 4.8 基线 |
| name | 角色名称 | varchar(128) | 否 | 是 | |
| scope | 作用域 | varchar(32) | 否 | 是 | PROJECT（当前仅项目级） |
| is_business_approval_role | 是否业务审批角色 | boolean | 否 | 是 | 供 M07 判定槽位 |
| created_at | 创建时间 | timestamptz | 否 | 是 | |

```sql
CREATE TABLE iam_role (
  id                          uuid PRIMARY KEY,
  code                        varchar(64) NOT NULL,
  name                        varchar(128) NOT NULL,
  scope                       varchar(32) NOT NULL DEFAULT 'PROJECT',
  is_business_approval_role   boolean NOT NULL DEFAULT false,
  created_at                  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_iam_role_code UNIQUE (code),
  CONSTRAINT ck_iam_role_scope CHECK (scope IN ('PROJECT'))
);
COMMENT ON TABLE iam_role IS '角色定义，系统配置，运行期只读';
```

### 4.5 `iam_member` 成员

| 字段名 | 中文名 | 类型 | 主键 | 非空 | 描述 |
| --- | --- | --- | --- | --- | --- |
| id | 成员 ID | uuid | 是 | 是 | |
| tenant_id | 租户 ID | uuid | 否 | 是 | 冗余隔离键 |
| project_id | 项目 ID | uuid | 否 | 是 | |
| user_id | 用户 ID | uuid | 否 | 是 | |
| status | 状态 | varchar(24) | 否 | 是 | ACTIVE / REMOVED |
| created_at | 创建时间 | timestamptz | 否 | 是 | |
| updated_at | 更新时间 | timestamptz | 否 | 是 | |

```sql
CREATE TABLE iam_member (
  id          uuid PRIMARY KEY,
  tenant_id   uuid NOT NULL,
  project_id  uuid NOT NULL REFERENCES iam_project(id),
  user_id     uuid NOT NULL REFERENCES iam_user(id),
  status      varchar(24) NOT NULL DEFAULT 'ACTIVE',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_iam_member UNIQUE (project_id, user_id),
  CONSTRAINT ck_iam_member_status CHECK (status IN ('ACTIVE','REMOVED'))
);
CREATE INDEX ix_iam_member_list ON iam_member (project_id, status);
COMMENT ON TABLE iam_member IS '用户加入项目';
```

### 4.6 `iam_member_role` 成员角色

| 字段名 | 中文名 | 类型 | 主键 | 非空 | 描述 |
| --- | --- | --- | --- | --- | --- |
| id | 分配 ID | uuid | 是 | 是 | |
| tenant_id | 租户 ID | uuid | 否 | 是 | 冗余隔离键 |
| project_id | 项目 ID | uuid | 否 | 是 | |
| member_id | 成员 ID | uuid | 否 | 是 | 引用 `iam_member.id` |
| role_id | 角色 ID | uuid | 否 | 是 | 引用 `iam_role.id` |
| valid_from | 生效时间 | timestamptz | 否 | 是 | |
| valid_to | 失效时间 | timestamptz | 否 | 否 | 空表示当前有效 |
| assigned_by_user_id | 分配人 | uuid | 否 | 是 | |
| created_at | 创建时间 | timestamptz | 否 | 是 | |

```sql
CREATE TABLE iam_member_role (
  id                    uuid PRIMARY KEY,
  tenant_id             uuid NOT NULL,
  project_id            uuid NOT NULL,
  member_id             uuid NOT NULL REFERENCES iam_member(id),
  role_id               uuid NOT NULL REFERENCES iam_role(id),
  valid_from            timestamptz NOT NULL DEFAULT now(),
  valid_to              timestamptz,
  assigned_by_user_id   uuid NOT NULL,
  created_at            timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_iam_member_role_period CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE UNIQUE INDEX uq_iam_member_active_role
  ON iam_member_role (member_id, role_id)
  WHERE valid_to IS NULL;
COMMENT ON TABLE iam_member_role IS '成员角色分配，只追加与置失效，不覆盖历史';
```

### 4.7 `iam_auth_session` 会话

| 字段名 | 中文名 | 类型 | 主键 | 非空 | 描述 |
| --- | --- | --- | --- | --- | --- |
| id | 会话 ID | uuid | 是 | 是 | |
| user_id | 用户 ID | uuid | 否 | 是 | |
| token_hash | 令牌摘要 | char(64) | 否 | 是 | 令牌的 SHA256，不存明文 |
| issued_at | 签发时间 | timestamptz | 否 | 是 | |
| expires_at | 过期时间 | timestamptz | 否 | 是 | 签发 + 8 小时 |
| revoked_at | 注销时间 | timestamptz | 否 | 否 | |
| last_seen_at | 最近活动 | timestamptz | 否 | 否 | |

```sql
CREATE TABLE iam_auth_session (
  id            uuid PRIMARY KEY,
  user_id       uuid NOT NULL REFERENCES iam_user(id),
  token_hash    char(64) NOT NULL,
  issued_at     timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  last_seen_at  timestamptz,
  CONSTRAINT uq_iam_auth_session_token UNIQUE (token_hash),
  CONSTRAINT ck_iam_auth_session_expiry CHECK (expires_at > issued_at)
);
CREATE INDEX ix_iam_auth_session_user ON iam_auth_session (user_id, expires_at DESC);
COMMENT ON TABLE iam_auth_session IS '服务端会话，令牌只存摘要';
```

### 4.8 设计约束

1. **角色基线固定六类**：`MAKER`、`CHECKER_DATA`、`CHECKER_SECURITY`、`OPERATOR`、`AUDITOR`、`PROJECT_ADMIN`。`CHECKER_DATA` 与 `CHECKER_SECURITY` 的 `is_business_approval_role` 为 `true`；`PROJECT_ADMIN` 仅管成员与项目配置，**不进入审批职责槽**，因此该字段为 `false`。
2. **唯一性**：租户 `code` 全局唯一；项目 `(tenant_id, code)` 唯一；同一项目内 `(project_id, user_id)` 唯一；同一成员对同一角色只允许一条 `valid_to IS NULL` 的记录（部分唯一索引保证）。
3. **角色变更是追加式**：分配新角色不删除旧记录，只把旧记录 `valid_to` 置为当前时间。历史审批事实中具名主体因此可追溯。
4. **不设外键级联删除**：成员移除只把 `status` 置 `REMOVED` 并将角色置失效，不物理删除，避免历史审批记录失去主体。
5. **禁止物理删除**：`iam_member`、`iam_member_role`、`iam_auth_session` 均不做物理删除；`iam_auth_session` 允许按过期时间归档到冷表。
6. **不存明文凭据**：`iam_user` 不存密码哈希之外的任何凭据；密码哈希存 `iam_user_credential`（本地认证启用时创建，见 5.3.2）。
7. **隔离键冗余**：`iam_member`、`iam_member_role` 同时保存 `tenant_id` 与 `project_id`，写入前必须校验二者与 `iam_project` 一致，不一致返回 `IAM_SCOPE_MISMATCH`。

---

## 5. 后端设计

### 5.1 Schema 层（Pydantic v2）

#### 5.1.1 `LoginRequest`

- 路径：`apps/api/app/modules/iam/schemas.py`
- 用途：登录请求体

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| provider | `Literal["LOCAL","OIDC"]` | 是 | 当前仅 `LOCAL` 可用，`OIDC` 由配置开关控制 |
| external_subject | `str` | 是 | 1–256 字符 |
| credential | `str` | 是 | 本地认证为密码，最小 8 字符；不落日志 |

#### 5.1.2 `LoginResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| session_token | `str` | 一次性返回明文令牌，客户端存于 httpOnly Cookie 或内存 |
| expires_at | `datetime` | UTC |
| user | `UserBrief` | |
| projects | `list[ProjectBrief]` | 该用户可见项目 |

#### 5.1.3 `SessionResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| user | `UserBrief` | id、display_name、status |
| tenant | `TenantBrief` | id、code、name |
| project | `ProjectBrief \| None` | 当前切换到的项目，未选择为 null |
| roles | `list[str]` | 角色 code 列表 |
| approval_slots | `list[str]` | 该用户可承担的审批槽位：`DATA` / `SECURITY` |
| capabilities | `list[str]` | 权限标识列表，供前端渲染入口 |

#### 5.1.4 `CreateProjectRequest`

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| code | `str` | 是 | `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$` |
| name | `str` | 是 | 1–128 字符 |

#### 5.1.5 `MemberResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | `UUID` | 成员 ID |
| user_id | `UUID` | |
| display_name | `str` | |
| email_masked | `str \| None` | 脱敏值 |
| roles | `list[RoleBrief]` | 当前有效角色 |
| status | `str` | ACTIVE / REMOVED |
| last_login_at | `datetime \| None` | |

#### 5.1.6 `AssignRoleRequest`

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| role_code | `str` | 是 | 必须是基线六类之一 |
| valid_from | `datetime \| None` | 否 | 缺省为当前时间 |
| reason | `str` | 是 | 3–256 字符，写入审计，不可为空 |

### 5.2 Router 层

#### 5.2.1 `AuthRouter`

- 类路径：`apps/api/app/modules/iam/router.py`
- 路由前缀：`/api/v1/auth`
- 依赖注入：`AuthService`

| 方法名 | 请求方式 | 路径 | 权限 | 幂等 | 说明 |
| --- | --- | --- | --- | --- | --- |
| login | POST | `/auth/login` | 匿名 | 否 | 认证并签发会话 |
| logout | POST | `/auth/logout` | 登录态 | 否 | 注销当前会话 |
| get_session | GET | `/auth/session` | 登录态 | — | 返回上下文与能力清单 |
| switch_project | POST | `/auth/session/project` | 登录态 | 否 | 切换当前项目 |

##### 方法说明

**`login`**

- 参数：JSON Body `LoginRequest`
- 返回：`LoginResponse`，HTTP 200
- 逻辑：调用 `AuthService.login`；失败按错误码映射为 401；成功写 `debug` 入口日志（不含 credential）与 `info` 完成日志

**`logout`**

- 参数：从 Cookie 或 `Authorization` 取令牌
- 返回：`None`，HTTP 204
- 逻辑：调用 `AuthService.logout`，把会话 `revoked_at` 置为当前时间并写 Redis 黑名单（TTL 取剩余有效期）

**`get_session`**

- 参数：无
- 返回：`SessionResponse`
- 逻辑：从 `RequestContext` 组装；`capabilities` 由 `roles.py` 的角色→能力映射计算

**`switch_project`**

- 参数：JSON Body `{"project_id": "uuid"}`
- 返回：`SessionResponse`
- 逻辑：校验该用户在目标项目内存在 `ACTIVE` 成员记录，否则 `IAM_NOT_MEMBER`；成功后把 `project_id` 写入会话（服务端会话表新增 `current_project_id`，见迁移 `0003_iam_session_project`）

#### 5.2.2 `ProjectRouter`

- 路由前缀：`/api/v1/projects`
- 依赖注入：`ProjectService`、`MemberService`

| 方法名 | 请求方式 | 路径 | 权限 | 幂等 | 说明 |
| --- | --- | --- | --- | --- | --- |
| list_projects | GET | `/projects` | `iam:project:read` | — | 游标分页 |
| create_project | POST | `/projects` | `iam:project:write` | 是 | 创建项目 |
| get_project | GET | `/projects/{project_id}` | `iam:project:read` | — | 项目详情 |
| update_project | PATCH | `/projects/{project_id}` | `iam:project:write` | 是 | 改名称/状态 |
| list_members | GET | `/projects/{project_id}/members` | `iam:member:read` | — | 成员列表 |
| invite_member | POST | `/projects/{project_id}/members` | `iam:member:write` | 是 | 按 `external_subject` 邀请 |
| update_member | PATCH | `/projects/{project_id}/members/{member_id}` | `iam:member:write` | 是 | 启用/移除 |
| assign_role | POST | `/projects/{project_id}/members/{member_id}/roles` | `iam:role:assign` | 是 | 追加角色 |
| revoke_role | DELETE | `/projects/{project_id}/members/{member_id}/roles/{assignment_id}` | `iam:role:assign` | — | 置失效 |
| list_roles | GET | `/projects/{project_id}/roles` | `iam:member:read` | — | 角色基线 |

##### 方法说明

**`create_project`**

- 参数：JSON Body `CreateProjectRequest`；`tenant_id` 取自 `RequestContext`，**不接受客户端传入**
- 返回：`ProjectResponse`，HTTP 201
- 逻辑：`code` 格式校验 → 唯一性冲突转 `IAM_PROJECT_CODE_CONFLICT` → 插入 → 创建人自动成为 `PROJECT_ADMIN` 成员

**`invite_member`**

- 参数：JSON Body `{"external_subject": "...", "role_codes": ["MAKER"]}`
- 返回：`MemberResponse`，HTTP 201
- 逻辑：按 `external_subject` 查 `iam_user`；不存在返回 `IAM_USER_NOT_FOUND`（**不自动建用户**，避免伪造主体）→ 查重 `IAM_MEMBER_EXISTS` → 建成员 → 逐条分配角色

**`assign_role`**

- 参数：路径 `member_id`，Body `AssignRoleRequest`
- 返回：`MemberResponse`
- 逻辑：见 5.3.4

**`revoke_role`**

- 参数：路径 `assignment_id`
- 返回：`MemberResponse`
- 逻辑：仅置 `valid_to`；若移除的是该成员最后一个角色，保留成员但 `roles` 为空，由前端提示「无角色成员不可操作任何资源」

### 5.3 Service 层

#### 5.3.1 `AuthService`

| 方法名 | 参数 | 返回 | 说明 |
| --- | --- | --- | --- |
| `login` | `req: LoginRequest`, `ip: str` | `LoginResponse` | 认证、建会话、更新 `last_login_at` |
| `logout` | `session_id: UUID` | `None` | 置吊销并写黑名单 |
| `resolve_context` | `token: str` | `RequestContext` | 校验会话并装配上下文 |
| `switch_project` | `ctx`, `project_id: UUID` | `SessionResponse` | 切换项目 |

**`login` 实现逻辑**

1. `debug` 日志：`auth.login.start`，字段 `provider`、`subject_hash`（对 `external_subject` 取 SHA256 前 16 位，**不打印原文**）。
2. 校验 `provider`：非 `LOCAL` 且 OIDC 未启用 → 抛 `AUTH_PROVIDER_DISABLED`。
3. 按 `external_subject` 查 `iam_user`；不存在 → `AUTH_INVALID_CREDENTIALS`（不区分「用户不存在」与「密码错误」，避免账号枚举）。
4. `status = DISABLED` → `AUTH_USER_DISABLED`。
5. 校验凭据：`LOCAL` 走 `iam_user_credential.password_hash`（Argon2id），失败 → `AUTH_INVALID_CREDENTIALS`。
6. 生成 32 字节随机令牌，`secrets.token_urlsafe(32)`，`token_hash = sha256(token)` 入库；`expires_at = now + 8h`。
7. 更新 `last_login_at`；查询该用户在所有 `ACTIVE` 项目的成员关系。
8. `info` 日志：`auth.login.success`，字段 `user_id`、`session_id`、`project_count`。
9. 返回 `LoginResponse`，**明文令牌只在这一次响应中出现**。

**`resolve_context` 实现逻辑**

1. 取 `token_hash` 查 `iam_auth_session`；无记录 → `AUTH_UNAUTHENTICATED`。
2. 命中 Redis 黑名单 → `AUTH_SESSION_REVOKED`。
3. `expires_at < now` → `AUTH_SESSION_EXPIRED`。
4. 查用户状态，`DISABLED` → `AUTH_USER_DISABLED`。
5. 装配 `RequestContext`：`user_id`、`tenant_id`、`project_id`（会话当前项目，可能为 None）、`roles`（当前项目有效角色 code）、`capabilities`。
6. 异步更新 `last_seen_at`（每 60 秒最多一次，用 Redis `SET NX EX 60` 去重，避免每请求写库）。

#### 5.3.2 凭据存储

`iam_user_credential` 为本地认证启用时创建的附属表，不在 M01 的核心七表内，字段：`user_id`（PK，FK `iam_user.id`）、`password_hash`（varchar(255)，Argon2id）、`updated_at`、`failed_attempts`（int）、`locked_until`（timestamptz，可空）。

连续 5 次失败锁定 15 分钟；锁定期间返回 `AUTH_ACCOUNT_LOCKED`。OIDC 启用后该表可为空，不参与认证。

#### 5.3.3 `ProjectService`

| 方法名 | 参数 | 返回 | 说明 |
| --- | --- | --- | --- |
| `create_project` | `ctx`, `req` | `ProjectResponse` | 创建并绑定创建人为管理员 |
| `list_projects` | `ctx`, `cursor`, `limit` | `PageResult[ProjectResponse]` | 仅返回当前用户为成员的项目 |
| `get_project` | `ctx`, `project_id` | `ProjectResponse` | 非成员返回 `IAM_NOT_MEMBER` |
| `update_project` | `ctx`, `project_id`, `req` | `ProjectResponse` | `ARCHIVED` 为终态，不可改回 |

**`create_project` 实现逻辑**

1. `debug`：`project.create.start`，`tenant_id`、`code`。
2. `code` 正则校验，失败 `IAM_INVALID_CODE_FORMAT`。
3. 查 `(tenant_id, code)` 是否占用，占用 `IAM_PROJECT_CODE_CONFLICT`。
4. 事务内：插入 `iam_project` → 查 `external_subject = 当前用户` 的 `iam_user` → 插入 `iam_member`（status ACTIVE）→ 插入 `iam_member_role`（`PROJECT_ADMIN`，`assigned_by_user_id` = 自己）。
5. `info`：`project.create.success`，`project_id`、`code`。
6. 提交后投递 `IAM_PROJECT_CREATED` 事件到 M11 审计（异步，失败不影响主流程）。

#### 5.3.4 `MemberService`

| 方法名 | 参数 | 返回 | 说明 |
| --- | --- | --- | --- |
| `list_members` | `ctx`, `project_id`, `cursor`, `limit` | `PageResult[MemberResponse]` | 含有效角色 |
| `invite_member` | `ctx`, `project_id`, `req` | `MemberResponse` | 不自动建用户 |
| `update_member` | `ctx`, `project_id`, `member_id`, `status` | `MemberResponse` | 移除不可恢复 |
| `assign_role` | `ctx`, `project_id`, `member_id`, `req` | `MemberResponse` | 追加式 |
| `revoke_role` | `ctx`, `project_id`, `member_id`, `assignment_id` | `MemberResponse` | 置失效 |
| `list_roles` | — | `list[RoleResponse]` | 读基线 |

**`assign_role` 实现逻辑**

1. `debug`：`member.role.assign.start`，`member_id`、`role_code`。
2. 校验 `role_code` 属于基线六类，否则 `IAM_ROLE_UNKNOWN`。
3. 校验目标成员属于当前项目，否则 `IAM_MEMBER_NOT_FOUND`。
4. 若该成员已有同角色且 `valid_to IS NULL` → `IAM_ROLE_ALREADY_ASSIGNED`（幂等语义：同请求体重放返回既有结果，由 `Idempotency-Key` 拦截）。
5. 组装写入：`tenant_id`、`project_id` 必须与项目一致，否则 `IAM_SCOPE_MISMATCH`。
6. 插入新记录；**不**修改旧记录。
7. `info`：`member.role.assign.success`，`member_id`、`role_code`、`assignment_id`；`warn` 分支：若被分配角色使成员同时具备 `MAKER` 与任一 `CHECKER_*`，写 `warn` 日志 `member.role.separation_notice`，但**允许**分配——职责分离的逐单判定在 M07，这里只提示。
8. 投递 `IAM_ROLE_ASSIGNED` 审计事件。

### 5.4 Repository 层

| Repository | 继承/基类 | 使用的方法 | 业务场景 |
| --- | --- | --- | --- |
| `TenantRepository` | `BaseRepository[IamTenant]` | `get_by_id`、`get_by_code` | 租户解析 |
| `UserRepository` | `BaseRepository[IamUser]` | `get_by_id`、`get_by_subject`、`update_last_login` | 登录、上下文装配 |
| `ProjectRepository` | `BaseRepository[IamProject]` | `get_by_id`、`get_by_code`、`list_by_member`、`insert`、`update` | 项目 CRUD |
| `RoleRepository` | `BaseRepository[IamRole]` | `get_by_code`、`list_all` | 角色基线 |
| `MemberRepository` | `BaseRepository[IamMember]` | `get_by_project_and_user`、`list_by_project`、`insert`、`update_status` | 成员管理 |
| `MemberRoleRepository` | `BaseRepository[IamMemberRole]` | `list_active_by_member`、`get_active`、`insert`、`expire` | 角色分配 |
| `SessionRepository` | `BaseRepository[IamAuthSession]` | `get_by_token_hash`、`insert`、`revoke`、`touch` | 会话 |

约束：`list_by_member` 必须带 `tenant_id` 与 `status = 'ACTIVE'` 条件，禁止无条件全表查询。所有列表方法必须带游标参数，默认 `limit=20`，上限 `100`。

---

## 6. 前端设计

前端细节见同目录《前端SPEC.md》，此处只列与本模块后端的契约交点。

| 交点 | 约定 |
| --- | --- |
| 认证态 | 令牌由后端以 httpOnly Cookie 下发，前端不读不存 |
| 能力渲染 | 按 `GET /auth/session` 的 `capabilities` 决定按钮可见性 |
| 角色展示 | 直接展示 `roles` 的 code，中文名由前端静态字典映射 |
| 错误呈现 | 按 `code` 映射文案，`AUTH_INVALID_CREDENTIALS` 统一提示「账号或密码不正确」 |
| 幂等键 | 成员邀请、角色分配由前端生成 `Idempotency-Key`（`crypto.randomUUID()`） |

---

## 7. 接口契约

### 7.1 统一响应结构

见《开发规范》5.1。成功示例：

```json
{
  "code": "OK",
  "message": "success",
  "data": {"project_id": "0193a1f2-7c4e-7b21-9f30-6a2b5c8d1e44"},
  "trace_id": "01HQ8Z3K7V2N5R9T4B6C8D0E1F"
}
```

### 7.2 POST /api/v1/auth/login

- 权限：匿名
- 请求参数：

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| provider | string | 是 | `LOCAL` / `OIDC` |
| external_subject | string | 是 | 认证主体 |
| credential | string | 是 | 凭据 |

请求示例：

```json
{
  "provider": "LOCAL",
  "external_subject": "local:zhanglan",
  "credential": "CorrectHorseBattery"
}
```

成功响应：

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "session_token": "dq3n8Xk2...（32 字节 URL 安全随机串）",
    "expires_at": "2026-11-23T23:31:02Z",
    "user": {
      "id": "0193a1e8-4b2c-7d10-8e55-1c2d3e4f5a6b",
      "display_name": "张岚",
      "status": "ACTIVE"
    },
    "projects": [
      {"id": "0193a1f2-7c4e-7b21-9f30-6a2b5c8d1e44", "code": "crm-sync", "name": "客户主数据同步", "status": "ACTIVE"}
    ]
  },
  "trace_id": "01HQ8Z3K7V2N5R9T4B6C8D0E1F"
}
```

错误码：

| 错误码 | HTTP | 说明 |
| --- | --- | --- |
| AUTH_INVALID_CREDENTIALS | 401 | 主体或凭据不正确（不区分具体原因） |
| AUTH_USER_DISABLED | 403 | 用户已停用 |
| AUTH_ACCOUNT_LOCKED | 423 | 连续失败锁定，响应含 `locked_until` |
| AUTH_PROVIDER_DISABLED | 400 | 认证方式未启用 |

### 7.3 POST /api/v1/auth/logout

- 权限：登录态
- 请求参数：无（令牌来自 Cookie）
- 成功响应：HTTP 204，无响应体
- 错误码：`AUTH_UNAUTHENTICATED`（401）

### 7.4 GET /api/v1/auth/session

- 权限：登录态
- 请求参数：无

成功响应：

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "user": {"id": "0193a1e8-4b2c-7d10-8e55-1c2d3e4f5a6b", "display_name": "张岚", "status": "ACTIVE"},
    "tenant": {"id": "0193a1c0-1111-7a00-9000-000000000001", "code": "acme", "name": "Acme 数据平台"},
    "project": {"id": "0193a1f2-7c4e-7b21-9f30-6a2b5c8d1e44", "code": "crm-sync", "name": "客户主数据同步", "status": "ACTIVE"},
    "roles": ["MAKER"],
    "approval_slots": [],
    "capabilities": ["iam:project:read", "iam:member:read", "asset:connection:read", "studio:session:write"]
  },
  "trace_id": "01HQ8Z3K7V2N5R9T4B6C8D0E1F"
}
```

错误码：

| 错误码 | HTTP | 说明 |
| --- | --- | --- |
| AUTH_UNAUTHENTICATED | 401 | 无有效令牌 |
| AUTH_SESSION_EXPIRED | 401 | 会话过期 |
| AUTH_SESSION_REVOKED | 401 | 已注销 |

### 7.5 POST /api/v1/auth/session/project

- 权限：登录态
- 请求参数：

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| project_id | uuid | 是 | 目标项目 |

请求示例：

```json
{"project_id": "0193a1f2-7c4e-7b21-9f30-6a2b5c8d1e44"}
```

成功响应：同 7.4，`project` 为切换后的项目。

错误码：`IAM_NOT_MEMBER`（403）、`IAM_PROJECT_NOT_FOUND`（404）

### 7.6 POST /api/v1/projects

- 权限：`iam:project:write`
- 请求头：`Idempotency-Key` 必填

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| code | string | 是 | 租户内唯一 |
| name | string | 是 | |

请求示例：

```json
{"code": "crm-sync", "name": "客户主数据同步"}
```

成功响应：

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "id": "0193a1f2-7c4e-7b21-9f30-6a2b5c8d1e44",
    "tenant_id": "0193a1c0-1111-7a00-9000-000000000001",
    "code": "crm-sync",
    "name": "客户主数据同步",
    "status": "ACTIVE",
    "created_at": "2026-11-23T08:31:02Z",
    "updated_at": "2026-11-23T08:31:02Z"
  },
  "trace_id": "01HQ8Z3K7V2N5R9T4B6C8D0E1F"
}
```

错误码：

| 错误码 | HTTP | 说明 |
| --- | --- | --- |
| IAM_INVALID_CODE_FORMAT | 400 | 编码不符合规则 |
| IAM_PROJECT_CODE_CONFLICT | 409 | 租户内编码已存在 |
| SYS_IDEMPOTENCY_CONFLICT | 409 | 同键不同请求体 |

### 7.7 GET /api/v1/projects/{project_id}/members

- 权限：`iam:member:read`
- 请求参数：

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| cursor | string | 否 | 游标 |
| limit | int | 否 | 默认 20，上限 100 |

成功响应：

```json
{
  "code": "OK",
  "message": "success",
  "data": {
    "items": [
      {
        "id": "0193a200-2222-7c00-8000-000000000010",
        "user_id": "0193a1e8-4b2c-7d10-8e55-1c2d3e4f5a6b",
        "display_name": "张岚",
        "email_masked": "z***n@corp.com",
        "roles": [{"code": "MAKER", "name": "需求提出者", "is_business_approval_role": false}],
        "status": "ACTIVE",
        "last_login_at": "2026-11-23T07:20:11Z"
      }
    ],
    "next_cursor": null
  },
  "trace_id": "01HQ8Z3K7V2N5R9T4B6C8D0E1F"
}
```

### 7.8 POST /api/v1/projects/{project_id}/members/{member_id}/roles

- 权限：`iam:role:assign`
- 请求头：`Idempotency-Key` 必填

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| role_code | string | 是 | 基线六类之一 |
| valid_from | string | 否 | ISO 8601，缺省当前时间 |
| reason | string | 是 | 3–256 字符 |

请求示例：

```json
{"role_code": "CHECKER_DATA", "valid_from": null, "reason": "业务维度审批由王策承担"}
```

成功响应：`MemberResponse`，`roles` 包含新角色。

错误码：

| 错误码 | HTTP | 说明 |
| --- | --- | --- |
| IAM_ROLE_UNKNOWN | 400 | 角色不在基线 |
| IAM_MEMBER_NOT_FOUND | 404 | 成员不属于该项目 |
| IAM_ROLE_ALREADY_ASSIGNED | 409 | 已持有同角色 |
| IAM_SCOPE_MISMATCH | 409 | 租户/项目不一致 |

### 7.9 DELETE /api/v1/projects/{project_id}/members/{member_id}/roles/{assignment_id}

- 权限：`iam:role:assign`
- 成功响应：`MemberResponse`
- 错误码：`IAM_ASSIGNMENT_NOT_FOUND`（404）、`IAM_SCOPE_MISMATCH`（409）

---

## 8. 权限配置

### 8.1 权限标识清单

| 权限标识 | 权限名称 | 类型 | 说明 |
| --- | --- | --- | --- |
| `iam:project:read` | 查看项目 | 读 | 列出与查看所属项目 |
| `iam:project:write` | 管理项目 | 写 | 创建、修改项目 |
| `iam:member:read` | 查看成员 | 读 | 成员与角色基线只读 |
| `iam:member:write` | 管理成员 | 写 | 邀请、启用、移除 |
| `iam:role:assign` | 分配角色 | 写 | 追加与失效角色 |
| `auth:session:write` | 会话操作 | 写 | 切换项目、注销 |

### 8.2 角色 → 能力映射

| 角色 | 能力 |
| --- | --- |
| PROJECT_ADMIN | `iam:project:read`、`iam:project:write`、`iam:member:read`、`iam:member:write`、`iam:role:assign`、`auth:session:write` |
| MAKER | `iam:project:read`、`iam:member:read`、`auth:session:write` |
| CHECKER_DATA | `iam:project:read`、`iam:member:read`、`auth:session:write` |
| CHECKER_SECURITY | `iam:project:read`、`iam:member:read`、`auth:session:write` |
| OPERATOR | `iam:project:read`、`iam:member:read`、`auth:session:write` |
| AUDITOR | `iam:project:read`、`iam:member:read`、`auth:session:write` |

说明：其余模块的能力标识（`asset:*`、`studio:*`、`harness:*` 等）由各模块 SPEC 定义并在 `roles.py` 的映射表中追加，M01 只负责输出聚合后的清单。`approval_slots` 的计算规则：`CHECKER_DATA` → `["DATA"]`，`CHECKER_SECURITY` → `["SECURITY"]`，两者兼有 → `["DATA","SECURITY"]`，其余为空。

### 8.3 前端入口可见性

| 入口 | 所需能力 |
| --- | --- |
| 成员与设置页 | `iam:member:read` |
| 邀请成员按钮 | `iam:member:write` |
| 分配角色按钮 | `iam:role:assign` |
| 新建项目按钮 | `iam:project:write` |

---

## 9. 日志点清单

### 9.1 后端日志点

| 位置 | 级别 | 内容格式 |
| --- | --- | --- |
| `AuthService.login` 入口 | debug | `auth.login.start` provider subject_hash ip |
| `AuthService.login` 成功 | info | `auth.login.success` user_id session_id project_count |
| `AuthService.login` 凭据失败 | warn | `auth.login.denied` code=AUTH_INVALID_CREDENTIALS subject_hash ip |
| `AuthService.login` 锁定 | warn | `auth.login.locked` subject_hash locked_until |
| `AuthService.resolve_context` 失败 | warn | `auth.session.invalid` code 原因 |
| `AuthService.logout` | info | `auth.logout` user_id session_id |
| `AuthService.switch_project` | info | `auth.project.switch` user_id from to |
| `ProjectService.create_project` 入口 | debug | `project.create.start` tenant_id code |
| `ProjectService.create_project` 成功 | info | `project.create.success` project_id code |
| `ProjectService.update_project` | info | `project.update` project_id fields |
| `MemberService.invite_member` 成功 | info | `member.invite.success` project_id member_id user_id |
| `MemberService.update_member` | info | `member.status.change` member_id from to |
| `MemberService.assign_role` 成功 | info | `member.role.assign.success` member_id role_code assignment_id |
| `MemberService.assign_role` 职责重合提示 | warn | `member.role.separation_notice` member_id roles |
| `MemberService.revoke_role` | info | `member.role.revoke` member_id assignment_id |
| 任一 Repository 唯一约束冲突 | warn | `repo.constraint.conflict` table constraint |

敏感字段禁止入日志：`credential`、`session_token`、`email` 明文、`external_subject` 原文。

### 9.2 前端日志点

| 位置 | 内容格式 |
| --- | --- |
| 登录提交前 | `[iam] login submit provider=` |
| 登录成功后 | `[iam] login ok user=` |
| 登录失败 | `[iam] login fail code=` |
| 会话加载后 | `[iam] session loaded roles= caps=` |
| 切换项目 | `[iam] switch project id=` |
| 成员列表加载 | `[iam] members loaded count=` |
| 角色分配提交前 | `[iam] assign role member= role=` |
| 角色分配结果 | `[iam] assign role result code=` |

---

## 10. 验收标准

### 10.1 认证与会话

- [ ] 正确凭据登录返回 200，响应含 `session_token`、`expires_at`、`projects`
- [ ] 错误凭据返回 401 `AUTH_INVALID_CREDENTIALS`，且不区分「用户不存在」与「密码错误」
- [ ] 停用用户登录返回 403 `AUTH_USER_DISABLED`
- [ ] 连续 5 次失败后返回 423 `AUTH_ACCOUNT_LOCKED`，`locked_until` 为 15 分钟后
- [ ] 会话超过 8 小时后访问 `GET /auth/session` 返回 401 `AUTH_SESSION_EXPIRED`
- [ ] 注销后同一令牌再访问返回 401 `AUTH_SESSION_REVOKED`
- [ ] 数据库 `iam_auth_session.token_hash` 与明文令牌不同，且全库无明文令牌
- [ ] 登录成功后 `last_login_at` 被更新

### 10.2 项目隔离

- [ ] 非成员访问 `GET /projects/{id}` 返回 403 `IAM_NOT_MEMBER`
- [ ] `GET /projects` 只返回当前用户为 `ACTIVE` 成员的项目
- [ ] 租户内重复 `code` 创建返回 409 `IAM_PROJECT_CODE_CONFLICT`
- [ ] `code` 含大写或下划线返回 400 `IAM_INVALID_CODE_FORMAT`
- [ ] 创建项目后创建人自动具备 `PROJECT_ADMIN` 且能访问成员列表
- [ ] `ARCHIVED` 项目不可再改回 `ACTIVE`

### 10.3 成员与角色

- [ ] 邀请不存在的 `external_subject` 返回 404 `IAM_USER_NOT_FOUND`，且不创建用户
- [ ] 重复邀请同一用户返回 409 `IAM_MEMBER_EXISTS`
- [ ] 重复分配同一角色返回 409 `IAM_ROLE_ALREADY_ASSIGNED`
- [ ] 分配未知角色返回 400 `IAM_ROLE_UNKNOWN`
- [ ] 角色失效后 `valid_to` 非空，历史记录仍可查询
- [ ] 同一成员对同一角色只存在一条 `valid_to IS NULL` 记录（并发调用下由部分唯一索引兜底）
- [ ] 跨项目传入 `member_id` 返回 404 而非越权成功
- [ ] `PROJECT_ADMIN` 不出现在 `approval_slots` 中

### 10.4 接口与幂等

- [ ] `POST /projects` 缺少 `Idempotency-Key` 返回 400 `SYS_IDEMPOTENCY_KEY_REQUIRED`
- [ ] 相同键相同体重放返回首次结果，不产生第二条记录
- [ ] 相同键不同体返回 409 `SYS_IDEMPOTENCY_CONFLICT`
- [ ] 所有响应含 `trace_id`，且与日志中的 `trace_id` 一致
- [ ] 响应体不含 `credential`、明文邮箱、`token_hash`

### 10.5 权限控制

- [ ] MAKER 调用 `POST /projects` 返回 403 `AUTH_FORBIDDEN`
- [ ] AUDITOR 调用 `POST /members` 返回 403
- [ ] 无 `iam:role:assign` 的用户调用分配角色返回 403
- [ ] 能力清单与 8.2 映射表逐项一致（参数化测试覆盖六个角色）

### 10.6 日志

- [ ] 登录入口日志不含 `credential` 与 `external_subject` 原文
- [ ] 每次角色分配产生一条 `info` 与对应审计事件
- [ ] 职责重合时产生 `warn` 且不阻断操作
- [ ] 所有日志为 JSON 且含 `trace_id`、`module`、`action`
