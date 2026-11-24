# 生产级 ETL-Agent 数据集成平台 开发规范

> 本规范是全部模块 SPEC 的约束来源。SPEC 只描述"这个模块怎么做"，共性约束一律以本文为准，不在各 SPEC 中重复定义。

---

## 1. 适用范围与权威顺序

| 优先级 | 文档 | 说明 |
| --- | --- | --- |
| 1 | `1_PRD/生产级 ETL-Agent 数据集成平台-项目要求.md` | 原始需求基线，冲突以它为准 |
| 2 | `1_PRD/ETL-Agent平台-PRD.md` | 需求细化 |
| 3 | `3_概要设计/生产级 ETL-Agent 数据集成平台-概要设计.md` | 架构与技术选型 |
| 4 | `3_概要设计/ETL-Agent平台-数据实体设计.md` | 表名、字段与不可变边界 |
| 5 | 本规范 | 编码层面的统一约定 |
| 6 | 各模块 SPEC | 模块内部实现细节 |

SPEC 与本文冲突时改 SPEC；本文与概要设计冲突时改本文。概要设计与项目要求冲突时改概要设计。

---

## 2. 后端技术栈与分层

| 项 | 约定 |
| --- | --- |
| 运行时 | Python 3.11+，启用 `from __future__ import annotations` |
| Web 框架 | FastAPI，全部路由挂载在 `/api/v1` 下 |
| 契约 | Pydantic v2，请求/响应/内部载荷共用同一套模型 |
| ORM | SQLAlchemy 2.0 async，禁止在 Service 层写裸 SQL 字符串拼接 |
| 迁移 | Alembic，一次迁移只做一件事，必须可回滚 |
| 任务 | Celery + Redis，按 `exec` / `meta` / `bench` 分队列 |
| 日志 | structlog，JSON 输出 |
| 测试 | pytest + pytest-asyncio，服务层用真实 PostgreSQL（testcontainers 或本地库），不用 sqlite 模拟 |

### 2.1 强制分层

```
router  →  service  →  repository  →  models
```

| 层 | 允许 | 禁止 |
| --- | --- | --- |
| `router.py` | 解析请求、鉴权依赖、调用 service、映射异常为 HTTP | 业务判断、直接访问 ORM 会话 |
| `service.py` | 用例编排、事务边界、领域校验 | 拼接 SQL、构造 HTTP 响应 |
| `repository.py` | 数据访问、查询条件组装 | 业务规则、抛业务异常 |
| `models.py` | 表映射 | 业务方法 |

跨模块调用只允许调用对方的 `service`，不得跨模块 import `repository` 或 `models`。唯一例外见概要设计 §4（Commit 事务内创建执行记录），代码处必须写 `# ARCH-EXCEPTION: <理由>` 注释。

### 2.2 目录约定

```
apps/api/app/
  main.py
  core/            # 配置、日志、错误基类、请求上下文
  modules/<domain>/
    router.py
    schemas.py
    service.py
    repository.py
    models.py
    deps.py
    errors.py
  workers/         # Celery 任务
  migrations/      # Alembic
```

模块目录名与数据域前缀对应：`iam`、`asset`、`meta`、`studio`、`flow`、`gen`、`harness`、`exec`、`audit`、`bench`。

---

## 3. 命名规范

| 对象 | 规则 | 示例 |
| --- | --- | --- |
| 表 | `<域前缀>_<名词>`，复数用单数 | `iam_project`、`harness_preparation` |
| 字段 | snake_case | `content_sha256`、`created_by_user_id` |
| ORM 类 | PascalCase，表名单数 | `class IamProject(Base)` |
| Pydantic 模型 | `<动作><对象>Request` / `<对象>Response` | `CreateProjectRequest`、`MemberResponse` |
| Service | `<对象>Service`，方法用动词 | `ProjectService.create_project` |
| Repository | `<对象>Repository` | `MemberRepository.find_active_roles` |
| 路由函数 | snake_case，与 service 同名 | `def create_project(...)` |
| 常量枚举 | 大写字符串值与 Python Enum 同名 | `ProjectStatus.ACTIVE = "ACTIVE"` |

禁止：`utils.py` 万能工具、`common.py` 垃圾桶、`manager`/`helper` 这类无信息量的类名。

---

## 4. 数据库规范

以《数据实体设计》第 2 章为准，SPEC 中不重复展开，只强调四条：

1. 主键统一 `uuid`，由应用生成 UUIDv7，不使用 `serial`。
2. 时间统一 `timestamptz`，以 UTC 存储，展示层转 `Asia/Shanghai`。
3. 项目资源表必须同时冗余 `tenant_id` 与 `project_id`。
4. 协议、审批、执行、质量、证据表禁止删除；配置类表只允许停用，不做物理删除。

Alembic 迁移中的 DDL 必须与 SPEC 第 4 章逐字一致，包括 `COMMENT`（PG 用 `COMMENT ON COLUMN`）。改动字段必须先改 SPEC 再改迁移。

---

## 5. 接口规范

| 项 | 约定 |
| --- | --- |
| 前缀 | `/api/v1` |
| 风格 | REST + JSON；动作用子资源表达（`/approvals/{slot}/decision`），不用 `POST /doApprove` |
| 幂等 | 所有写操作要求 `Idempotency-Key` 头；同键不同体返回 `409` |
| 追踪 | 入口生成或透传 `trace_id`，贯穿工作流、授权、执行、审计 |
| 分页 | 游标分页（`cursor` + `limit`），禁止 offset 无限翻页 |
| 时间 | 响应统一 ISO 8601 UTC（`2026-11-23T08:31:02Z`） |
| 脱敏 | 敏感字段不得出现在任何响应中；Secret 只回引用 ID |
| 空值 | 明确区分 `null` 与缺省，不使用空字符串代替空值 |

### 5.1 统一响应结构

```json
{
  "code": "OK",
  "message": "success",
  "data": {},
  "trace_id": "01HQ8Z3K7V2N5R9T4B6C8D0E1F"
}
```

失败：

```json
{
  "code": "IAM_PROJECT_CODE_CONFLICT",
  "message": "项目编码在该租户内已存在",
  "data": {"field": "code", "value": "crm-sync"},
  "trace_id": "01HQ8Z3K7V2N5R9T4B6C8D0E1F",
  "retriable": false
}
```

### 5.2 错误码规范

格式 `<域>_<对象>_<情形>`，域取 `AUTH`、`IAM`、`ASSET`、`META`、`FLOW`、`GEN`、`HARNESS`、`EXEC`、`QUAL`、`BENCH`、`SYS`。协议类拒绝必须使用稳定错误码，不得复用一个笼统码。

---

## 6. 日志规范

structlog JSON，必带字段：`trace_id`、`module`、`action`、`actor_id`、`project_id`、`result`、`duration_ms`。

| 场景 | 级别 | 说明 |
| --- | --- | --- |
| 每个 Router 方法入口 | `debug` | 记录参数摘要，**不记录** Secret、原始 PII、完整请求体 |
| Service 关键步骤 | `debug` | 步骤名 + 关键标识 |
| 用例完成 | `info` | 结果、耗时、影响行数 |
| 校验失败/拒绝 | `warn` | 错误码 + 原因，不抛栈 |
| 外部依赖失败 | `error` | 依赖名 + 重试次数；附异常栈 |
| 不可恢复 | `critical` | 触发告警 |

禁止：`print`、字符串拼接式日志、把异常吞掉只记一行"失败"。

---

## 7. 前端技术栈与规范

| 项 | 约定 |
| --- | --- |
| 框架 | Vue 3 组合式 API + `<script setup lang="ts">` |
| 构建 | Vite |
| 组件 | Element Plus |
| 状态 | Pinia，按域建 store，禁止跨 store 直接改对方 state |
| 请求 | 统一 `src/api/request.ts`，集中处理错误码与 `trace_id` 上报 |
| 类型 | 接口出参必须有 TS 类型，禁止 `any` 流转 |
| 样式 | 优先 Element Plus token；不写全局覆盖式 CSS |

### 7.1 目录约定

```
web/src/
  api/<domain>.ts
  views/<domain>/<View>.vue
  components/<domain>/<Component>.vue
  stores/<domain>.ts
  types/<domain>.ts
  router/index.ts
```

### 7.2 渲染与授权边界

前端只按后端返回的能力清单（`capabilities`）决定入口可见性，**不作为授权依据**；所有写操作后端必须再次校验。禁止在前端持有或传递 Secret 明文，只能提交 `secret_ref_id`。

---

## 8. 测试要求

| 层 | 要求 |
| --- | --- |
| Service | 每个公开方法至少一条正常路径 + 一条拒绝路径 |
| Repository | 唯一约束、隔离条件（tenant/project）必须有测试 |
| Router | 鉴权失败、参数校验失败、幂等冲突各一条 |
| 协议链路 | Commit、授权、重放必须有并发测试 |
| 前端 | 关键页面用 Vitest + Vue Test Utils 覆盖表单校验与权限渲染 |

---

## 9. 提交前自查

- [ ] 迁移与 SPEC 第 4 章一致，可 `alembic downgrade` 回滚
- [ ] 新接口已带 `Idempotency-Key` 校验与 `trace_id` 透传
- [ ] 响应中无 Secret、无原始 PII
- [ ] 日志覆盖 debug/info/warn 三类，无 `print`
- [ ] 跨模块调用只经 `service`
- [ ] 表名、字段名与《数据实体设计》完全一致
- [ ] 前端无 `any`、无硬编码权限判断
