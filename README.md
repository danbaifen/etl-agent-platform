# 生产级 ETL-Agent 数据集成平台

面向企业异构数据集成的控制面平台。按 `spec_coding/` 下的文档实施，**冲突以 `spec_coding/1_PRD/生产级 ETL-Agent 数据集成平台-项目要求.md` 为准**。

## 1. 实现范围

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| M01 身份与租户 | ✅ | 登录/会话/项目/成员/角色，职责分离硬拦截 |
| M02 凭据与连接 | ✅ | 连接 CRUD、连通性测试、Secret 引用与轮转记录 |
| M03 元数据探查 | ✅ | 只读探查（表/字段/空值率/基数）+ 敏感识别 + 脱敏样本 |
| M04 Studio 会话 | ✅ | 需求输入、澄清中断、Checkpoint、消息留痕 |
| M05 生成编排 | ✅ | EtlPlan + HOCON 生成（规则化生成器，非 LLM） |
| M06 门禁与版本 | ✅ | 7 类确定性门禁 + 不可变版本 + 组件分片 SHA256 |
| M07 Harness 内核 | ✅ | PDP 风险评级、Prepare/Approve/Commit、Ed25519 单次 Capability、Replay Guard、Outbox、证据链 |
| M08 执行调度 | ✅ | 本地执行器（Celery 未接入），真实读写数据面 |
| M09 监督与诊断 | ✅ | 预算监控、硬中断、失败快照、根因诊断、受管回滚 |
| M10 质量与发布 | ✅ | 质量契约分流、错误表、影子表原子 Swap |
| M11 证据账本 | ✅ | 哈希链 + Ed25519 签名 + 链完整性校验 |
| M12 评测与策略 | ✅ | Benchmark 套件、PDP 定级回归、准确率与拦截率 |

验收标准（2.8.10）9 条均有自动化用例覆盖，其中 4 条使用了本地替代组件，边界写在 `docs/验收测试报告.md` 第 4 节。

## 2. 目录结构

```
backend/
  app/core/          配置、日志、错误、上下文、时钟、摘要与签名
  app/modules/iam/       M01 身份与租户
  app/modules/asset/     M02 连接与 Secret
  app/modules/meta/      M03 元数据探查
  app/modules/studio/    M04/M05 会话与生成
  app/modules/pipe/      M06 门禁与版本
  app/modules/harness/   M07 Harness 内核
  app/modules/exec/      M08/M09/M10 执行、监督、质量与发布
  app/modules/bench/     M12 评测
  migrations/         Alembic
  tests/              pytest：30 个用例（验收矩阵 + 链路）
  app/scripts/        seed_iam / seed_demo
frontend/             Vue 3 + Element Plus 控制台（7 个页面）
deploy/               docker-compose（PostgreSQL / Redis / Vault）
docs/                 验收测试报告
spec_coding/          PRD、概要设计、开发规范、各模块 SPEC、原型
```

## 3. 启动项目

用 SQLite 跑通全链路，无需 Docker、无需 PostgreSQL。

### 3.1 本机现状（依赖已就绪，直接跑）

当前机器已全局装好全部 Python 依赖与 `frontend/node_modules`，**不要再执行 `pip install`**（外网 PyPI 不可达）。配置已在 `backend/.env` 内固定为 SQLite + 单机幂等，**不需要设任何环境变量**。

**后端必须先确认用哪个 Python**：系统里可能同时存在两个解释器，只有 `backend/.venv`（已创建，`--system-site-packages` 继承全部依赖）能跑起来；CMD 里默认的 Python 3.12（装在用户目录下，如 `C:\Users\<你>\AppData\Local\Programs\Python\Python312\python.exe`）可能缺 `pydantic_settings`、`aiosqlite`、`alembic` 等包，直接调会报 `ModuleNotFoundError`。启动脚本已自动探测并优先使用 `.venv`。

**方式 A：双击脚本**（项目根目录）

- `start-backend.cmd` —— 后端，端口 8010
- `start-frontend.cmd` —— 前端，端口 5173

两个窗口都要开着。前端窗口会打印访问地址。脚本结束时会停住等按键，方便看到报错。

> **脚本必须用 CRLF 换行**。`.cmd` 如果是 LF 换行（Unix 格式），CMD 解析 `if (...)` 括号块会出错，表现为双击后窗口一闪而过什么都不做。改脚本后请确认换行符为 CRLF、编码为 ASCII 或 UTF-8 无 BOM。

**方式 B：命令行**（CMD，注意 `cd /d`）

```bat
:: 窗口 1 —— 后端
cd /d "D:\path\to\etl-agent-platform\backend"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

```bat
:: 窗口 2 —— 前端
cd /d "D:\path\to\etl-agent-platform\frontend"
npx vite --port 5173
```

前端后端地址已写在 `frontend/.env`（`VITE_API_TARGET=http://127.0.0.1:8010`），不需要 `set`。要临时改指向别处，再 `set VITE_API_TARGET=...` 覆盖即可。

打开 **http://localhost:5173**，后端接口文档在 **http://127.0.0.1:8010/docs**。

> **CMD 三个坑**：① 跨盘切换目录必须写 `cd /d`，只写 `cd` 不会真正进入 D 盘（提示符仍停在 `C:\Users\<你>>`），之后会报 `No module named 'app'` 或找不到 `package.json`；② 变量要单独一行 `set X=Y`，`VAR=x cmd` 这种写在命令前的写法是 bash 的，CMD 会把 `VAR` 当成程序名报「不是内部或外部命令」；③ `export` 也是 bash 语法。PowerShell 对应写法是 `$env:X="Y"`，且 `cd` 不需要 `/d`。

`backend/var/platform.db` 与 `backend/var/demo/` 已初始化。若要重置数据：

```bat
cd /d "D:\path\to\etl-agent-platform\backend"
del var\platform.db
python -m alembic upgrade head
python -m app.scripts.seed_demo --data-dir ./var/demo
```

### 3.2 从 GitHub 克隆后（全新环境）

仓库**不包含** `backend/.env` 与 `backend/var/`（前者是本地配置、后者是含账号数据的数据库文件）。克隆后先在 `backend/` 下新建 `.env`：

```ini
DATABASE_URL=sqlite+aiosqlite:///./var/platform.db
IDEMPOTENCY_BACKEND=memory
```

`backend/.env.example` 是接入 PostgreSQL + Redis + Vault 的生产模板，单机本地运行不要直接用它。

然后：

```bash
cd backend
python -m venv .venv && source .venv/Scripts/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

`var/` 会在首次启动时自动建库并灌演示数据（`start-backend.cmd` 会检测数据库是否存在并自动跑 alembic + seed）。

**演示账号**（密码统一 `DemoPass!2026`）：

| 账号 | 角色 | 能做什么 |
| --- | --- | --- |
| `local:zhanglan` | MAKER | 建连接、探查、生成、冻结、提交准备单 |
| `local:liwei` | CHECKER_DATA | 业务维度审批 |
| `local:wangce` | CHECKER_SECURITY | 安全维度审批、触发 Benchmark |
| `local:chenmo` | OPERATOR | Commit、启动执行、受管回滚 |
| `local:zhouxin` | AUDITOR | 证据账本与执行历史 |

### 3.3 演示路径

1. `数据源与资产` → 对「CRM 生产库」点探查，看脱敏样本（`138****1111`）
2. `Pipeline Studio` → 选源/目标对象，输入需求 → 回答澄清 → 生成候选
3. 点「执行门禁并冻结版本」→ 看门禁 finding 与版本 SHA256
4. 点「生成准备单」→ 看风险等级 P1、两个具名审批槽
5. `运行中心与审批` → 用李维、王策分别登录批准 → 用陈默 Commit（拿单次 Capability）
6. 点「启动执行」→ 真实读 12 行、写 10 行、分流 2 行、原子 Swap 发布
7. `证据账本` → 看 7 条记录链完整
8. `安全治理与评测` → 触发 Benchmark，看准确率与 P0/P1 拦截率

### 3.4 脏数据与硬中断

仓库里 `log_event` 表故意做成 5/10 行脏数据。用它生成流水线执行会因拒绝率 50% 超过 20% 预算触发硬中断，产生失败快照、根因诊断，可用「受管回滚」清理影子表。

## 4. 验证

```bat
cd /d "D:\path\to\etl-agent-platform\backend"
.venv\Scripts\python.exe -m pytest tests -v      :: 30 passed
```

前端构建：

```bash
cd frontend
npm run build                  # vue-tsc --noEmit && vite build
```

## 5. 关键约束

- 令牌只存 SHA256 摘要，明文只在登录响应出现一次；前端用 httpOnly Cookie。
- `tenant_id` / `project_id` 只来自会话；会话项目与请求项目不一致返回 `IAM_SCOPE_MISMATCH`。
- 写接口强制 `Idempotency-Key`；所有响应带 `trace_id`。
- 角色分配追加式，旧记录只置 `valid_to`；职责分离硬拦截（`IAM_ROLE_DUTY_CONFLICT`）。
- 申请人不得审批自己的准备单（`HARNESS_SELF_APPROVAL_FORBIDDEN`）；非指定审批人不能代批。
- Capability 5 分钟、单次消费，重放返回 `HARNESS_REPLAY_DETECTED`。
- 版本冻结后组件内容不可改；Commit 前重校验制品指纹。

## 6. 已知边界

| 边界 | 现状 |
| --- | --- |
| 数据源类型 | 仅 SQLite 参与真实连通性测试与探查；其他类型明确返回 `UNSUPPORTED`，不伪造成功 |
| 生成器 | 规则化确定性生成，未接 LLM Provider；中断/恢复语义对齐 LangGraph，但不是其运行时 |
| 执行 | 本地进程内同步执行，未接 Celery Worker 与 SeaTunnel Zeta；搬运/分流/指标真实发生 |
| 发布 | 用 SQLite 表改名实现原子 Swap，未接 Doris `REPLACE TABLE` |
| Secret | 只记录 Vault 路径与版本，未接真实 Vault 读写 |
| 数据库 | 默认 SQLite；PostgreSQL 需装 asyncpg 并改用 `postgresql+asyncpg://` |

详见 `docs/验收测试报告.md`。
