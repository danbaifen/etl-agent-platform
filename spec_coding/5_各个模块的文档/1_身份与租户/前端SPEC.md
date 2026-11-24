# 生产级 ETL-Agent 数据集成平台 身份与租户 前端 SPEC

## 1. 文档说明

### 1.1 文档目的

本文档是 M01 身份与租户模块的前端实现规格。编码人员据此可直接写出页面结构、状态、请求封装、校验与样式，不需要再推敲交互细节。后端契约以同目录《后端SPEC.md》为准，本文只定义前端如何消费。

### 1.2 适用范围

| 范围 | 内容 |
| --- | --- |
| 前端源码 | `web/src/views/iam/`、`web/src/components/iam/`、`web/src/api/iam.ts`、`web/src/stores/auth.ts`、`web/src/types/iam.ts` |
| 页面 | 登录页、成员与设置页 |
| 原型 | `2_原型图/桌面端/登录页.pen`、`2_原型图/桌面端/成员与设置.pen` |
| 不覆盖 | 顶栏项目切换器的挂载位置（布局层负责）、总览工作台（M12 前端） |

### 1.3 相关文档

| 文档 | 路径 | 说明 |
| --- | --- | --- |
| PRD | `1_PRD/ETL-Agent平台-PRD.md` | 登录与成员管理需求 |
| 概要设计 | `3_概要设计/生产级 ETL-Agent 数据集成平台-概要设计.md` | 前端分层与能力清单约定 |
| 数据实体设计 | `3_概要设计/ETL-Agent平台-数据实体设计.md` | 角色基线定义 |
| 开发规范 | `4_开发规范/ETL-Agent平台-开发规范.md` | 目录、请求层、类型要求 |
| 后端 SPEC | `5_各个模块的文档/1_身份与租户/后端SPEC.md` | 接口契约与错误码 |
| 部署手册 | `5_各个模块的文档/1_身份与租户/后端开发部署手册.md` | 联调环境准备 |

---

## 2. 模块概览

### 2.1 模块定位

身份与租户模块的前端承担两个入口：**登录页**负责认证与会话建立，**成员与设置页**负责项目成员与角色分配。同时它向全局提供会话上下文（`auth` store），供路由守卫与 `v-capability` 指令使用。

### 2.2 原型结构摘要

| 原型文件 | 页面 | 关键区域 |
| --- | --- | --- |
| `登录页.pen` | 登录 | 左侧品牌主张区（620px）+ 右侧登录卡（480px） |
| `成员与设置.pen` | 成员与设置 | 页头（标题/项目切换/邀请）+ 成员表格卡 + 右侧角色说明卡 |

两个页面不共用布局壳——登录页不渲染侧栏与顶栏。

### 2.3 依赖关系

```
┌──────────────┐   读能力清单    ┌──────────────────┐
│ router 守卫   │ ─────────────▶ │ stores/auth.ts   │
└──────┬───────┘                 └────────┬─────────┘
       │                                  │ GET /auth/session
       ▼                                  ▼
┌──────────────┐                 ┌──────────────────┐
│ 布局层（顶栏） │ ◀── 角色/项目 ── │ api/iam.ts       │
└──────────────┘                 └────────┬─────────┘
                                          │
                    ┌─────────────────────┴───────────────┐
                    ▼                                     ▼
            登录页 LoginView                    成员设置 MemberSettingsView
```

下游依赖：M02 及之后所有页面的路由守卫都读 `auth.has(capability)`，因此本模块必须先于其他前端模块完成。

---

## 3. 目录与文件放置

### 3.1 后端目录结构（契约来源）

```
apps/api/app/modules/iam/
├── router.py        # /api/v1/auth, /api/v1/projects
├── schemas.py       # 请求/响应模型
├── service.py       # AuthService / ProjectService / MemberService
└── roles.py         # 角色基线与能力映射
```

前端不直接引用后端代码，只依赖 `router.py` 暴露的路径与 `schemas.py` 的字段名。

### 3.2 前端目录结构

```
web/src/
├── api/
│   └── iam.ts                     # 认证与成员接口封装
├── types/
│   └── iam.ts                     # 与后端字段一一对应的 TS 类型
├── stores/
│   └── auth.ts                    # 会话、角色、能力清单
├── views/iam/
│   ├── LoginView.vue              # 登录页
│   └── MemberSettingsView.vue     # 成员与设置页
├── components/iam/
│   ├── InviteMemberDrawer.vue     # 邀请成员抽屉
│   ├── AssignRoleDialog.vue       # 分配角色弹窗
│   └── RoleTag.vue                # 角色标签（code → 中文名）
├── router/
│   └── guards.ts                  # 登录守卫与能力守卫
└── directives/
    └── capability.ts              # v-capability 指令
```

### 3.3 页面注册要求

| 项 | 要求 |
| --- | --- |
| 路由文件 | 统一在 `router/index.ts` 注册，模块不自行 `createRouter` |
| 懒加载 | 页面必须 `() => import(...)`，不允许同步引入 |
| 路由名 | 与组件名一致，如 `Login`、`MemberSettings` |
| meta | 必填 `title`；需权限的页面必填 `capability`；公开页填 `public: true` |
| 面包屑 | `meta.breadcrumb` 为数组，缺省时用 `title` |

```ts
{ path: '/login', name: 'Login', component: () => import('@/views/iam/LoginView.vue'),
  meta: { title: '登录', public: true } }

{ path: '/settings/members', name: 'MemberSettings',
  component: () => import('@/views/iam/MemberSettingsView.vue'),
  meta: { title: '成员与设置', capability: 'iam:member:read',
          breadcrumb: ['设置', '成员与设置'] } }
```

---

## 4. 前端对象与字段设计

### 4.1 接口字段约束

字段命名与后端 **snake_case 完全一致**，不做驼峰转换，避免映射层引入偏差。接口只能使用后端已有字段，不得构造 `roleText`、`statusText`、`emailPlain` 这类拼接字段。

| 约束 | 说明 |
| --- | --- |
| 时间 | 后端返回 ISO 8601 UTC，前端统一转 `Asia/Shanghai` 展示 |
| 脱敏邮箱 | 只有 `email_masked`，**没有** `email`；前端不得请求明文 |
| 角色 | `roles` 为角色对象数组，不是字符串数组；`code` 用于逻辑，`name` 用于展示 |
| 状态 | 使用枚举原值（`ACTIVE`/`REMOVED`），中文由字典映射 |
| 分页 | 使用 `cursor` + `next_cursor`，不使用 `page`/`total` |

### 4.2 TypeScript 类型（`types/iam.ts`）

| 类型 | 字段 | 类型 | 说明 |
| --- | --- | --- | --- |
| `UserBrief` | `id` | `string` | |
| | `display_name` | `string` | |
| | `status` | `'ACTIVE' \| 'DISABLED'` | |
| `TenantBrief` | `id` / `code` / `name` | `string` | |
| `ProjectBrief` | `id` / `code` / `name` | `string` | |
| | `status` | `'ACTIVE' \| 'SUSPENDED' \| 'ARCHIVED'` | |
| `RoleBrief` | `code` | `string` | 基线六类 |
| | `name` | `string` | |
| | `is_business_approval_role` | `boolean` | 是否进入审批槽 |
| `SessionResponse` | `user` | `UserBrief` | |
| | `tenant` | `TenantBrief` | |
| | `project` | `ProjectBrief \| null` | |
| | `roles` | `string[]` | 角色 code |
| | `approval_slots` | `string[]` | `DATA` / `SECURITY` |
| | `capabilities` | `string[]` | 权限标识 |
| `MemberResponse` | `id` | `string` | 成员 ID |
| | `user_id` | `string` | |
| | `display_name` | `string` | |
| | `email_masked` | `string \| null` | |
| | `roles` | `RoleBrief[]` | 当前有效角色 |
| | `status` | `'ACTIVE' \| 'REMOVED'` | |
| | `last_login_at` | `string \| null` | ISO 8601 |
| `CreateProjectRequest` | `code` / `name` | `string` | |
| `InviteMemberRequest` | `external_subject` | `string` | |
| | `role_codes` | `string[]` | 至少 1 项 |
| `AssignRoleRequest` | `role_code` | `string` | |
| | `valid_from` | `string \| null` | |
| | `reason` | `string` | 3–256 字符 |
| `ApiResult<T>` | `code` / `message` / `trace_id` | `string` | |
| | `data` | `T` | |
| | `retriable` | `boolean?` | |

### 4.3 页面状态

| 页面 | 状态 | 类型 | 初始值 |
| --- | --- | --- | --- |
| 登录页 | `form.external_subject` | `string` | `''` |
| | `form.credential` | `string` | `''` |
| | `remember` | `boolean` | `true` |
| | `submitting` | `boolean` | `false` |
| | `errorText` | `string` | `''` |
| 成员页 | `members` | `MemberResponse[]` | `[]` |
| | `loading` | `boolean` | `false` |
| | `currentProjectId` | `string` | `auth.session?.project?.id ?? ''` |
| | `cursor` / `nextCursor` | `string \| null` | `null` |
| | `inviteVisible` / `assignVisible` | `boolean` | `false` |
| | `assignTarget` | `MemberResponse \| null` | `null` |
| | `roles` | `RoleBrief[]` | `[]` |
| 全局 | `auth.session` | `SessionResponse \| null` | `null` |
| | `auth.loading` | `boolean` | `false` |

`session` 不持久化到 `localStorage`；刷新后靠 `fetchSession()` 恢复。令牌由后端 httpOnly Cookie 承载，前端代码中不得出现读取令牌的逻辑。

---

## 5. 前端设计

### 5.1 登录页 `views/iam/LoginView.vue`

布局：左侧品牌主张区宽 620，右侧登录卡宽 480 居中偏右，`min-height: 100vh`。该路由不渲染侧栏与顶栏。

#### 模板结构

| 区域 | 组件 | 绑定 | 说明 |
| --- | --- | --- | --- |
| 品牌区 | 静态标题 + 副标题 + 三个能力标签 | — | 文案固定，不做配置 |
| 卡片标题 | `h2` | — | 「登录」 |
| 账号输入 | `el-input` | `form.external_subject` | placeholder `name@company.com`，`autocomplete="username"` |
| 密码输入 | `el-input`（`type="password"`、`show-password`） | `form.credential` | `autocomplete="current-password"` |
| 保持登录 | `el-checkbox` | `remember` | 仅影响提示文案，不改变后端 8 小时策略 |
| 主按钮 | `el-button type="primary"` | `@click="onSubmit"` | `:loading="submitting"`，整行宽 42px |
| SSO 入口 | `el-button`（`disabled`） | — | 文案「企业 SSO 登录（暂未开放）」，对应 TBD-03 |
| 错误提示 | `el-alert type="error"` | `errorText` | 位于按钮上方，不用 `ElMessage` 以免重复提示 |

#### 表单校验规则

| 字段 | 规则 | 提示语 |
| --- | --- | --- |
| `external_subject` | `required`、`min 3`、`max 256` | 请输入企业邮箱或工号 |
| `credential` | `required`、`min 8`、`max 128` | 密码至少 8 位 |

#### 错误码 → 文案

| 错误码 | 文案 |
| --- | --- |
| `AUTH_INVALID_CREDENTIALS` | 账号或密码不正确 |
| `AUTH_USER_DISABLED` | 账号已停用，请联系项目管理员 |
| `AUTH_ACCOUNT_LOCKED` | 失败次数过多，请 15 分钟后重试 |
| `AUTH_PROVIDER_DISABLED` | 该登录方式未开放 |
| 其他 | 登录失败，请稍后重试（`trace_id` 附在文案末尾） |

### 5.2 成员与设置页 `views/iam/MemberSettingsView.vue`

布局：页头（标题 + 项目切换 + 邀请按钮）+ 成员表格卡 + 右侧角色说明卡。

#### 模板结构

| 区域 | 组件 | 关键绑定 | 说明 |
| --- | --- | --- | --- |
| 项目切换 | `el-select` | `currentProjectId` | 选项来自 `auth.session.projects` |
| 邀请按钮 | `el-button type="primary"` | `@click="inviteVisible = true"` | `v-capability="'iam:member:write'"` |
| 成员表格 | `el-table` | `:data="members"` | 列定义见下 |
| 姓名列 | 默认渲染 | `prop="display_name"` | |
| 账号列 | 默认渲染 | `prop="email_masked"` | 空值显示 `—`，不显示明文 |
| 角色列 | `template` + `RoleTag` | `row.roles` | 多标签横向排列 |
| 状态列 | `el-tag` | `row.status` | `ACTIVE` 绿 / `REMOVED` 灰 |
| 最近活跃 | 默认渲染 | `prop="last_login_at"` | `YYYY-MM-DD HH:mm`，空值 `—` |
| 操作列 | `el-button link` | `@click="openAssign(row)"` | 文案「分配角色」，`v-capability="'iam:role:assign'"` |
| 分页 | `el-pagination` | `:total`、`@current-change` | 后端游标分页，前端用 `cursorStack` 模拟页码 |
| 空态 | `el-empty` | `v-if="!loading && members.length === 0"` | 「暂无成员，先邀请一位同事」 |
| 角色说明卡 | 静态列表 | — | 六角色 + 是否进入审批槽，数据来自 `GET /roles` |

#### 表格列宽

| 列 | 宽度 |
| --- | --- |
| 姓名 | 140 |
| 账号（脱敏） | 220 |
| 角色 | 220 |
| 状态 | 100 |
| 最近活跃 | 180 |
| 操作 | 120 |

### 5.3 `components/iam/InviteMemberDrawer.vue`

- `el-drawer` 宽 420 + `el-form`
- 字段：`external_subject`（`el-input`）、`role_codes`（`el-select multiple`，选项来自 `roles`，**排除 `PROJECT_ADMIN`**）
- 提交前生成 `Idempotency-Key`：`crypto.randomUUID()`，同一抽屉打开期间保持不变，成功后重置
- 成功后 `emit('invited')`；失败提示：`IAM_USER_NOT_FOUND` → 「该账号尚未加入平台，请先由管理员创建」，`IAM_MEMBER_EXISTS` → 「该成员已在项目中」

### 5.4 `components/iam/AssignRoleDialog.vue`

- `el-dialog` 宽 480 + 表单 + 当前角色列表（可逐个「失效」，调 `revokeRole`）
- 已持有角色在下拉中禁用
- 提交后 `emit('changed', memberResponse)`，父页面就地替换该行，不整表重载

#### 表单校验规则

| 字段 | 规则 | 提示语 |
| --- | --- | --- |
| `role_code` | `required` | 请选择角色 |
| `reason` | `required`、`min 3`、`max 256` | 请填写分配理由（不少于 3 字） |

理由必填的原因：角色分配写入审计，事后必须能回答「为什么给他这个角色」。

### 5.5 交互方法清单

| 方法 | 所属 | 逻辑 |
| --- | --- | --- |
| `onSubmit()` | 登录页 | 校验 → `submitting=true` → 埋点 → `auth.login` → 成功按 `redirect` 跳转（缺省 `/overview`）→ 失败映射 `errorText` → `finally` 复位 |
| `mapError(code)` | 登录页 | 按 5.1 表格映射文案 |
| `onMounted()` | 登录页 | 已登录直接跳 `/overview`；`route.query.reason === 'SESSION_EXPIRED'` 时提示过期 |
| `loadMembers(cursor?)` | 成员页 | 置 loading → 埋点 → `listMembers` → 追加/替换 → 更新 `nextCursor` → 失败 `ElMessage.error` |
| `loadRoles()` | 成员页 | `onMounted` 调一次，供角色卡与下拉使用 |
| `onSwitchProject(id)` | 成员页 | `auth.switchProject(id)` → 重载成员 → 埋点 |
| `openAssign(row)` | 成员页 | 设置 `assignTarget`，打开弹窗 |
| `onInvited()` | 成员页 | 关闭抽屉并 `loadMembers(null)` |
| `onRoleChanged(member)` | 成员页 | 关闭弹窗，就地替换对应行 |
| `logout()` | 布局层 | `auth.logout()` → 跳 `/login` |

---

## 6. API 封装设计

### 6.1 `api/iam.ts` 方法清单

| 方法名 | 请求方式 | 接口路径 | 参数 | 说明 |
| --- | --- | --- | --- | --- |
| `login` | POST | `/auth/login` | `LoginRequest` | 返回 `LoginResponse` |
| `logout` | POST | `/auth/logout` | — | 204 |
| `getSession` | GET | `/auth/session` | — | `SessionResponse` |
| `switchProject` | POST | `/auth/session/project` | `{project_id}` | `SessionResponse` |
| `listProjects` | GET | `/projects` | `{cursor?, limit?}` | 分页 |
| `createProject` | POST | `/projects` | `CreateProjectRequest` | 带幂等键 |
| `getProject` | GET | `/projects/{project_id}` | — | |
| `updateProject` | PATCH | `/projects/{project_id}` | `{name?, status?}` | 带幂等键 |
| `listMembers` | GET | `/projects/{project_id}/members` | `{cursor?, limit?}` | |
| `inviteMember` | POST | `/projects/{project_id}/members` | `InviteMemberRequest` | 带幂等键 |
| `updateMember` | PATCH | `/projects/{project_id}/members/{member_id}` | `{status}` | 带幂等键 |
| `assignRole` | POST | `/projects/{project_id}/members/{member_id}/roles` | `AssignRoleRequest` | 带幂等键 |
| `revokeRole` | DELETE | `/projects/{project_id}/members/{member_id}/roles/{assignment_id}` | — | |
| `listRoles` | GET | `/projects/{project_id}/roles` | — | |

页面不得直接 `import axios`，一律调用本文件方法。

### 6.2 请求头约定

| 头 | 何时携带 | 说明 |
| --- | --- | --- |
| `Content-Type` | 写操作 | `application/json` |
| `Idempotency-Key` | POST / PATCH / DELETE 写操作 | `crypto.randomUUID()`，由 `request.ts` 统一生成，调用方可显式传入以支持重试 |
| `X-Trace-Id` | 全部请求 | 前端生成 UUIDv7 透传，便于串联后端日志 |
| `Authorization` | 不使用 | 令牌由 httpOnly Cookie 承载 |

### 6.3 统一响应结构

```ts
interface ApiResult<T> {
  code: string
  message: string
  data: T
  trace_id: string
  retriable?: boolean
}
```

`request.ts` 统一解包：`code === 'OK'` 返回 `data`；否则抛 `ApiError`（含 `code`、`message`、`trace_id`）。收到 401 且 `code` 为 `AUTH_SESSION_EXPIRED` / `AUTH_SESSION_REVOKED` 时，清空 `auth` 并跳 `/login?reason=SESSION_EXPIRED`。

---

## 7. 接口契约

### 7.1 POST /api/v1/auth/login

请求：

```json
{"provider": "LOCAL", "external_subject": "local:zhanglan", "credential": "CorrectHorseBattery"}
```

响应 `data`：

```json
{
  "session_token": "dq3n8Xk2...（32 字节 URL 安全随机串）",
  "expires_at": "2026-11-23T23:31:02Z",
  "user": {"id": "0193a1e8-4b2c-7d10-8e55-1c2d3e4f5a6b", "display_name": "张岚", "status": "ACTIVE"},
  "projects": [
    {"id": "0193a1f2-7c4e-7b21-9f30-6a2b5c8d1e44", "code": "crm-sync", "name": "客户主数据同步", "status": "ACTIVE"}
  ]
}
```

错误码：`AUTH_INVALID_CREDENTIALS`(401)、`AUTH_USER_DISABLED`(403)、`AUTH_ACCOUNT_LOCKED`(423)、`AUTH_PROVIDER_DISABLED`(400)

### 7.2 GET /api/v1/auth/session

响应 `data`：

```json
{
  "user": {"id": "0193a1e8-4b2c-7d10-8e55-1c2d3e4f5a6b", "display_name": "张岚", "status": "ACTIVE"},
  "tenant": {"id": "0193a1c0-1111-7a00-9000-000000000001", "code": "acme", "name": "Acme 数据平台"},
  "project": {"id": "0193a1f2-7c4e-7b21-9f30-6a2b5c8d1e44", "code": "crm-sync", "name": "客户主数据同步", "status": "ACTIVE"},
  "roles": ["MAKER"],
  "approval_slots": [],
  "capabilities": ["iam:project:read", "iam:member:read", "asset:connection:read", "studio:session:write"]
}
```

错误码：`AUTH_UNAUTHENTICATED`(401)、`AUTH_SESSION_EXPIRED`(401)、`AUTH_SESSION_REVOKED`(401)

### 7.3 GET /api/v1/projects/{project_id}/members

响应 `data`：

```json
{
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
}
```

错误码：`IAM_NOT_MEMBER`(403)、`AUTH_FORBIDDEN`(403)

### 7.4 POST /api/v1/projects/{project_id}/members/{member_id}/roles

请求：

```json
{"role_code": "CHECKER_DATA", "valid_from": null, "reason": "业务维度审批由王策承担"}
```

响应：`MemberResponse`，`roles` 含新角色。

错误码：`IAM_ROLE_UNKNOWN`(400)、`IAM_MEMBER_NOT_FOUND`(404)、`IAM_ROLE_ALREADY_ASSIGNED`(409)、`IAM_SCOPE_MISMATCH`(409)

---

## 8. 登录与权限配置

### 8.1 权限标识

| 权限标识 | 用途 | 前端使用位置 |
| --- | --- | --- |
| `iam:project:read` | 查看项目 | 项目切换、路由守卫 |
| `iam:project:write` | 管理项目 | 新建项目入口 |
| `iam:member:read` | 查看成员 | `/settings/members` 路由 |
| `iam:member:write` | 管理成员 | 邀请按钮、状态操作 |
| `iam:role:assign` | 分配角色 | 分配角色按钮、失效按钮 |
| `auth:session:write` | 会话操作 | 切换项目、注销 |

### 8.2 角色 → 能力映射（前端按此校验渲染一致性）

| 角色 | 能力 |
| --- | --- |
| `PROJECT_ADMIN` | 全部六项 |
| `MAKER` | `iam:project:read`、`iam:member:read`、`auth:session:write` |
| `CHECKER_DATA` | 同上 |
| `CHECKER_SECURITY` | 同上 |
| `OPERATOR` | 同上 |
| `AUDITOR` | 同上（无任何写能力） |

前端不自行推导角色能力，只消费 `session.capabilities`；上表用于测试用例编写与代码评审对照。

### 8.3 路由守卫规则

| 顺序 | 规则 | 失败行为 |
| --- | --- | --- |
| 1 | `meta.public === true` | 放行 |
| 2 | 无 `session` 时调 `fetchSession()` | 失败跳 `/login?redirect=<原路径>` |
| 3 | `meta.capability` 存在且 `!has(cap)` | 跳 `/403` 并埋点记录所需能力 |
| 4 | 已登录访问 `/login` | 跳 `/overview` |

### 8.4 入口可见性

| 元素 | 条件 | 不满足 |
| --- | --- | --- |
| `/settings/members` | `iam:member:read` | 跳 `/403` |
| 邀请成员按钮 | `iam:member:write` | 不渲染 |
| 分配角色按钮 | `iam:role:assign` | 不渲染 |
| 成员状态操作 | `iam:member:write` | 不渲染 |
| 新建项目入口 | `iam:project:write` | 不渲染 |

审计角色进入该页时，所有写按钮应全部消失且**不出现「无权限」报错**——这是验收项之一。

---

## 9. 日志点清单

### 9.1 后端日志点

本模块后端日志点见《后端SPEC.md》第 9.1 节，前端不重复定义。前端只需保证每次请求透传 `X-Trace-Id`，使两端日志可串联。

### 9.2 前端日志点

| 位置 | 内容格式 | 说明 |
| --- | --- | --- |
| 登录提交前 | `console.log('[iam] login submit provider=LOCAL')` | 入口 |
| 登录成功 | `console.log('[iam] login ok user_id=')` | 不打印令牌 |
| 登录失败 | `console.log('[iam] login fail code= trace_id=')` | 便于对照后端 |
| 会话恢复 | `console.log('[iam] session loaded roles= caps=')` | 角色与能力数量 |
| 会话恢复失败 | `console.warn('[iam] session restore fail code=')` | |
| 路由拦截 | `console.warn('[iam] route denied cap=')` | 能力不足 |
| 切换项目 | `console.log('[iam] switch project from= to=')` | |
| 成员加载前 | `console.log('[iam] members load cursor=')` | |
| 成员加载后 | `console.log('[iam] members load ok count=')` | |
| 成员加载失败 | `console.log('[iam] members load fail code=')` | |
| 邀请提交 | `console.log('[iam] invite submit subject_hash=')` | 仅打印哈希前 8 位 |
| 邀请结果 | `console.log('[iam] invite result code=')` | |
| 角色分配提交 | `console.log('[iam] assign role member_id= role_code=')` | |
| 角色分配结果 | `console.log('[iam] assign role result code=')` | |

敏感信息约束：不打印 `credential`、完整 `external_subject`、任何令牌、完整邮箱。

---

## 10. 样式规范

### 10.1 色板

| 用途 | 值 |
| --- | --- |
| 页面背景 | `#F6F7F9` |
| 卡片背景 | `#FFFFFF` |
| 主色（主按钮/选中） | `#2B5CE6` |
| 主色浅底 | `#EDF1FE` |
| 主文本 | `#1D2129` |
| 次文本 | `#667085` |
| 弱文本 | `#98A2B3` |
| 分割线 | `#D9DEE7` |
| 成功 | `#067647` |
| 警示 | `#B54708` |
| 危险 | `#B42318` |

### 10.2 排版与间距

| 项 | 规格 |
| --- | --- |
| 字体 | Inter + 系统中文回退（`Microsoft YaHei`） |
| 标题 | 20px / 600 |
| 卡片标题 | 13px / 600 |
| 正文 | 13px / 400，行高 1.45 |
| 辅助文字 | 11px / 400 |
| 卡片圆角 | 10px |
| 输入框圆角 | 6px，高 40px |
| 按钮圆角 | 6px，主按钮高 42px、次按钮 32px |
| 卡片内边距 | 16px |
| 卡片间距 | 16px |
| 内容区左右边距 | 32px |

### 10.3 组件规格

| 组件 | 规格 |
| --- | --- |
| 登录卡 | 480 × 540，仅 1px 边框，不加明显投影 |
| 表格行高 | 56px（成员表），表头 40px |
| 角色标签 | 高 22px，圆角 4px，字号 11px |
| 抽屉 | 宽 420，右侧滑入 |
| 弹窗 | 宽 480，居中 |

### 10.4 溢出与自适应约束

- 最小支持宽度 1280px；低于该宽度时成员表出现横向滚动，不得挤压操作列。
- 角色列超过 3 个标签时换行，不横向溢出。
- 脱敏邮箱超长时省略号截断（`text-overflow: ellipsis`），不通过 tooltip 展示明文。
- 登录卡在高度小于 700px 的视口内垂直居中且不出现滚动条。

---

## 11. 测试与验证

### 11.1 前端 Mock 测试

目标：不依赖后端时验证布局、权限渲染、空态与表单校验。Mock 数据必须使用第 4 章字段，不得出现 `roleText`、`email`、`statusText` 这类拼接或明文字段。

验证项：

- 无会话时访问 `/settings/members` 被重定向到 `/login`
- `capabilities` 不含 `iam:member:read` 时跳 `/403`
- `members=[]` 时展示空态而非空表格
- 3 个角色标签时横向排列不溢出
- `email_masked=null` 时该单元格显示 `—`
- `last_login_at=null` 时显示 `—`，非空时按 `Asia/Shanghai` 展示

### 11.2 表单校验用例

| 用例 | 输入 | 期望 |
| --- | --- | --- |
| 账号为空 | `external_subject=''` | 阻断提交，提示「请输入企业邮箱或工号」 |
| 账号过短 | `'ab'` | 阻断提交 |
| 密码过短 | `'1234567'` | 提示「密码至少 8 位」 |
| 理由过短 | `reason='同意'` | 提示「请填写分配理由（不少于 3 字）」 |
| 未选角色 | `role_codes=[]` | 阻断提交 |

### 11.3 权限渲染用例

| 角色 | 期望可见 |
| --- | --- |
| `PROJECT_ADMIN` | 邀请、分配角色、状态操作全部可见 |
| `MAKER` | 均不可见，页面只读 |
| `AUDITOR` | 均不可见，且不出现 403 提示 |

### 11.4 联调验证顺序

1. 启动后端，`GET /auth/session` 未登录返回 401
2. 登录成功后刷新页面，会话可恢复（Cookie 生效）
3. 手工置空 `iam_auth_session.expires_at`，刷新后跳登录页并提示过期
4. 用 AUDITOR 账号登录，确认写按钮全部消失

---

## 12. 验收标准

### 12.1 登录页

- [ ] 账号或密码为空时提交，出现校验提示且不发起请求
- [ ] 密码少于 8 位时提示「密码至少 8 位」
- [ ] 凭据错误展示「账号或密码不正确」，不区分用户是否存在
- [ ] 登录成功跳 `redirect` 指定页，无 `redirect` 跳 `/overview`
- [ ] 已登录访问 `/login` 跳 `/overview`
- [ ] SSO 按钮为禁用态且文案标明「暂未开放」
- [ ] 源码与 `localStorage` 中不存在令牌

### 12.2 成员与设置页

- [ ] 无 `iam:member:read` 访问该路由跳 `/403`
- [ ] 审计角色进入页面时所有写按钮不渲染且无报错
- [ ] 账号列只显示脱敏邮箱，空值显示 `—`
- [ ] 角色列多标签横向排列不溢出
- [ ] 最近活跃按 `Asia/Shanghai` 展示，空值 `—`
- [ ] 空成员时展示空态文案
- [ ] 切换项目后列表重载且不残留旧数据

### 12.3 邀请与角色分配

- [ ] 邀请抽屉角色下拉不含 `PROJECT_ADMIN`
- [ ] 邀请已存在成员提示「该成员已在项目中」
- [ ] 邀请未注册账号提示「该账号尚未加入平台」
- [ ] 理由少于 3 字无法提交
- [ ] 已持有角色在分配下拉中禁用
- [ ] 分配成功后对应行就地更新，不整表刷新
- [ ] 同一抽屉重复点击只产生一条记录（幂等键生效）

### 12.4 接口与错误处理

- [ ] 会话过期时清空状态并跳 `/login?reason=SESSION_EXPIRED`，登录页展示过期提示
- [ ] 所有错误提示包含 `trace_id`
- [ ] 列表分页使用游标，无 `offset` 参数
- [ ] 所有请求携带 `X-Trace-Id`，与后端日志可对应

### 12.5 代码质量

- [ ] `types/iam.ts` 字段名与后端响应逐字一致，无驼峰转换层
- [ ] 全模块无 `any`
- [ ] 页面不直接 `import axios`
- [ ] 按钮可见性统一走 `v-capability` 或 `auth.has`
- [ ] 样式使用第 10 章色板，无散落魔法值
