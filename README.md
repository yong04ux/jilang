<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="激浪 Surge：跨境电商 AI 运营工作台">
</p>

<h1 align="center">激浪 Surge</h1>

<p align="center">
  跨境卖家的 AI 运营工作台。<br/>
  竞品分析、Listing 撰写、数据导入、店铺看板，装在同一条可追踪的工序里。
</p>

<p align="center">
  <code>V1.0</code> · <code>Python 3.10+</code> · <code>FastAPI</code> · <code>Pydantic v2</code> · <code>PostgreSQL 16</code> · <code>React 19</code> · <code>TypeScript</code> · <code>Vite</code>
</p>

每个结论都有出处，每次生成都过事实审计，每个任务都有真实步骤与耗时。模型只负责解析目标与撰写文案；统计、字符限制、字段校验和机会分全部由可测试的代码计算。

---

## 界面

<a href="./assets/readme/shot-dashboard.png"><img src="./assets/readme/shot-dashboard.png" width="100%" alt="工作台：任务统计、30 天经营概览、任务趋势与最近报告"></a>

<a href="./assets/readme/shot-assistant.png"><img src="./assets/readme/shot-assistant.png" width="100%" alt="AI 助手：用一句话发起竞品分析或 Listing 生成"></a>

<a href="./assets/readme/shot-skills.png"><img src="./assets/readme/shot-skills.png" width="100%" alt="技能广场：竞品分析、Listing 生成、成本与利润测算等技能卡片"></a>

<a href="./assets/readme/shot-task.png"><img src="./assets/readme/shot-task.png" width="100%" alt="任务详情：执行步骤、竞品报告、价格定位与证据分级"></a>

<a href="./assets/readme/shot-stores.png"><img src="./assets/readme/shot-stores.png" width="100%" alt="店铺经营看板：待处理事项、核心指标与业绩走势"></a>

---

## 工作方式

<img src="./assets/readme/pipeline.svg" width="100%" alt="五道工序：目标解析、计划编排、工序执行、事实审计、落库留痕">

一句话进，结构化结果出。中间不做三件事：**不编造事实、不编造指标、不伪造进度**。

- **确定性归代码，语言归模型。** 价格统计、字符与字节限制、单位换算、字段校验、机会分计算由业务代码完成；模型输出必须通过 schema 校验与事实对齐质检。
- **证据分级。** 每条结论标记 `事实` / `统计` / `推断` / `假设`，尽量附竞品名或评论原文；`事实` 与 `统计` 缺证据即构造失败。
- **BYOK，不静默降级。** 平台不提供模型额度。没有可用 Key 时，需要模型的接口返回 `428 api_key_required`，界面引导去配置，而不是悄悄换成规则引擎还显示成功。
- **进度就是状态。** 页面上的步骤与耗时来自真实任务记录，失败可定位，重试默认从断点续跑。

---

## 能力

| 模块 | 能力 |
|---|---|
| **竞品分析** | 价格统计与定位、卖点覆盖、评论痛点/需求/顾虑挖掘、关键词机会（有指标才打分）、差异化机会、内容建议；支持异步执行 |
| **Listing 生成** | 标题、五点描述、产品描述、A+ 大纲、Search Terms、事实台账、逐项审计与质量检查；支持异步执行 |
| **多厂商 LLM** | 走 OpenAI 兼容协议，预置 DeepSeek / OpenAI / Moonshot / 智谱 / 通义 / 硅基流动 / OpenRouter / Ollama / 自定义；多套配置、单一激活、连通性测试、`base_url` 白名单 |
| **数据导入** | CSV / JSON / Excel 逐行校验，列识别、字段映射、预览；错误定位到单元格并可下载错误清单 |
| **Agent 工作流** | 目标解析 → 确定性计划 → 图执行 → 完整性检查 → 市场机会总结 → Listing → 质检 → 落库 |
| **技能与 Agent 注册表** | 平台内置 3 Agent / 7 Skill / 4 Tool，定义集中一处；租户可增改停用自己的定义（`admin+`，软删为 `disabled`，不能覆盖平台内置） |
| **店铺经营** | 店铺连接、商品与订单汇总、经营看板、单品分析、经营明细；统一连接器协议，真实平台授权待接入 |
| **多租户与角色** | 个人空间自动创建、`X-Tenant-Id` 成员校验、viewer / editor / admin / owner 四级角色 |
| **任务与执行** | 任务状态机、真实步骤与耗时、线程执行器（默认）与 arq 执行器（可选）、检查点取消、失败重试 |
| **审批与审计** | 发布审批（只记录结论，不代发）、敏感字段脱敏的审计日志 |
| **平台接入目录** | 9 个跨境平台的能力声明、站点、授权状态与 OAuth 端点；授权换取环节显式报错，不伪造 token |
| **导出与版本** | 报告导出 md / json / csv；Listing 导出 md / json / txt，版本链、差异与编辑后复检 |

---

## 安装

环境要求：**Python ≥ 3.10** + **PostgreSQL 16**。

```bash
cd backend                         # Python 工程根：venv / 依赖 / 测试都在这里
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，至少填写 SURGE_DATABASE_URL
```

也可以可编辑模式安装，之后在任意目录使用 `surge` 命令：

```bash
cd backend
pip install -e .
```

> **目录约定**：`backend/` 是 Python 工程根（venv、依赖、测试、脚本都在这）；
> 包代码在 `backend/surge/`，前端静态站在仓库根的 `frontend/`。
> 所有 Python 命令都在 `backend/` 下执行——站在仓库根运行会报
> `No module named surge`，不是安装失败，是站错了目录。

---

## 启动

### 数据库

先准备 PostgreSQL 16，并在 `.env` 里配置连接串：

```
SURGE_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/surge
```

缺省时应用拒绝启动，不会静默回退到 SQLite。迁移在启动时自动执行，也可手动执行并查看版本：

```bash
surge migrate
```

本地开发可用仓库附带的 `docker-compose.yml` 快速起一个库：

```bash
docker compose up -d
```

### 多环境配置（本地 / 线上）

配置文件由 `SURGE_ENV_FILE` 定位，默认 `backend/.env`。CLI 提供 `--env` 简写：

| 命令 | 使用的文件 | 典型用途 |
|---|---|---|
| `python -m surge serve` | `backend/.env` | 本地 PostgreSQL + 本地上传目录 |
| `python -m surge serve --env cloud` | `backend/.env.cloud` | 本地连线上 Supabase |
| `python -m surge migrate --env cloud` | `backend/.env.cloud` | 对线上库跑迁移 |

`--env local` 与不带参数等价——「本地」就是 `.env` 本身，不再复制第二份内容，避免两个文件各自演化。`--env X` 找不到 `.env.X` 时**直接报错**，不会静默退回默认配置（那种失败最难发现：以为连着线上库，实际写进了本地库）。

`--env` 对所有子命令生效（`serve` / `check` / `migrate`），写在子命令**后面**。启动时会把实际使用的配置文件与 `用户@主机:端口/库名` 打出来（不含密码），省得反复确认"我现在连的是哪个库"。

### 服务

本地开发（等价于生产入口，含 `/health`；在 `backend/` 下执行）：

```bash
uvicorn surge.worker_service:app --host 127.0.0.1 --port 8000
```

或未安装本包时：

```bash
cd backend
export PYTHONPATH=.            # Windows: $env:PYTHONPATH='.'
python -m surge serve --port 8000
```

启动后打开 `http://127.0.0.1:8000/`。首次访问会引导创建管理员账号。

### 其他 CLI

```bash
python -m surge check          # 检查依赖、规则文件、数据库连通性
python -m surge migrate        # 应用迁移并打印版本
```

<details>
<summary><b>启动失败对照表</b></summary>

| 报错 | 原因 | 处理 |
|---|---|---|
| `DatabaseError: 无法连接数据库` | PostgreSQL 未启动或连接串错误 | 先启动数据库，核对 `SURGE_DATABASE_URL` |
| `ModuleNotFoundError` | 依赖未安装 | `cd backend && pip install -r requirements.txt` |
| `No module named surge` | 站在 `backend/` 外，或未安装、未设 `PYTHONPATH` | 回到 `backend/`，或 `pip install -e .` |
| `[Errno 10048]` 端口占用 | 端口已被占用 | 换端口：`--port 8010` |

</details>

---

## 配置

复制 `.env.example` 为 `.env` 后按需修改：

| 变量 | 默认 | 说明 |
|---|---|---|
| `SURGE_DATABASE_URL` | 必填 | PostgreSQL 连接串 |
| `SURGE_MIGRATION_DATABASE_URL` | 空 | 迁移专用直连串；为空则用 `DATABASE_URL` |
| `SURGE_HOST` / `SURGE_PORT` | `127.0.0.1` / `8000` | 监听地址与端口 |
| `SURGE_SECRET_KEY` | 自动生成文件 | API Key 加密主密钥；**一旦设定不要改**（改了旧 Key 全部失效） |
| `SURGE_REQUIRE_API_KEY` | `true` | BYOK 强制；仅本地调试可关闭 |
| `SURGE_PROVIDER` | `rule` | 进程级默认 Provider（无用户配置时兜底） |
| `SURGE_RATE_LIMIT_ENABLED` | `true` | 是否启用限流 |
| `SURGE_RATE_LIMIT_TASKS_PER_HOUR` | `10` | 每账号每小时任务数 |
| `SURGE_RATE_LIMIT_KEY_TESTS_PER_HOUR` | `5` | 每账号每小时 Key 测试数 |
| `SURGE_ALLOW_OPEN_REGISTRATION` | `true` | 关闭后除首个用户外必须持邀请令牌 |
| `SURGE_TASK_QUEUE` | `thread` | `thread`（进程内）或 `arq`（需 Redis + worker） |
| `SURGE_REDIS_URL` | `redis://127.0.0.1:6379/0` | arq 队列使用的 Redis |
| `SURGE_AUTO_MIGRATE` | `true` | 生产建议 `false`，改由 `surge migrate` 显式迁移 |
| `SURGE_COOKIE_SECURE` | `false` | HTTPS 部署必须设 `true` |
| `SURGE_STORAGE_BACKEND` | `local` | `local` 或 `supabase` |
| `SURGE_SUPABASE_URL` / `_SERVICE_KEY` / `_BUCKET` | 空 / 空 / `surge` | Supabase Storage 配置 |
| `SURGE_ALLOWED_ORIGINS` | 空 | CORS 允许来源（逗号分隔）；空表示仅同源 |
| `SURGE_MAX_UPLOAD_BYTES` | 5 MB | 上传限制 |

`.env.example` 不含任何真实密钥；`.env` 已在 `.gitignore` 中。

---

## 测试与验收

```bash
cd backend
pytest
```

测试需要独立数据库。默认使用 `SURGE_DATABASE_URL`，也可单独指定：

```bash
cd backend
export SURGE_TEST_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/surge_test"
pytest
```

> **⚠️ 必须用独立的测试库。** 测试启动时会 `DROP SCHEMA public CASCADE` 再重建，
> 对开发库执行会**清空业务数据**。首次使用先建库：`createdb -U postgres surge_test`。

套件覆盖分析、Listing、导入、API、迁移、租户隔离、Agent、会话、异步任务、审计、审批、店铺、平台目录、多厂商配置、身份与权限矩阵。另有检查脚本：

```bash
cd backend
python scripts/check_encoding.py   # 源文件 UTF-8 与语法
python scripts/check_secrets.py    # 密钥扫描，命中 exit 1（输出只给掩码）
python scripts/check_frontend.py   # 前端资源契约 + 路由一致性 + tsc
python scripts/live_check.py       # 对运行中的服务做 HTTP 端到端断言
python scripts/pg_check.py <PG_URL> --reset   # PostgreSQL 专项验收

node frontend/scripts/ui_flows_v2.mjs http://127.0.0.1:8000        # 交互验收
node frontend/scripts/ui_workbench_v2.mjs http://127.0.0.1:8000    # 运行态与结果 Tab
node frontend/scripts/ui_shots_auth_v2.mjs http://127.0.0.1:8000 ./shots   # 逐页截图
```

---

## API

完整交互式文档在 `/docs`。主要端点：

| 分组 | 路径 |
|---|---|
| 健康与规则 | `GET /api/health`、`/api/platforms`、`/api/platform-rules/{p}/{m}`、`/api/ban-lists` |
| 认证 | `POST /api/auth/register` / `login` / `logout` / `password`；`PUT /api/auth/display-name` / `avatar` / `phone` |
| 竞品分析 | `POST /api/analyze/validate`、`POST /api/analyze[?async_run=true]` |
| Listing | `POST /api/listings/generate[?async_run=true]`、`POST /{id}/versions`、`POST /{id}/check`、`GET /{id}/diff` |
| 导入 | `POST /api/import`、`/api/import/preview`、`/api/import/commit`；`GET /api/data-sources` |
| 市场数据 | `GET /api/marketplace/sources`、`/overview`、`/products`、`/orders`、`/ads`、`/metrics` |
| 技能与 Agent | `GET /api/agents` / `skills` / `tools`、`POST /api/skills/{key}/run[?async_run=true]`、`POST /api/agent/runs` |
| 任务 | `GET /api/tasks`、`/api/tasks/{id}`、`POST /{id}/cancel`、`POST /{id}/retry` |
| 店铺 | `GET /api/stores` 及其子路由 |
| 审批与审计 | `GET/POST /api/approvals`、`POST /{id}/decide`、`GET /api/audit` |
| 租户 | `GET /api/tenants`、`/current`、`/members`；`GET/POST /api/tenants/invites` |
| 模型配置 | `GET/POST/DELETE /api/settings/providers`、`POST /{id}/test`、`POST /{id}/activate` |

---

## 目录结构

```
Surge/
├── backend/                    # Python 工程根：venv / 依赖 / 测试 / 脚本
│   ├── surge/                  # 业务包
│   │   ├── api/                # HTTP 层，按业务域拆分
│   │   ├── agent/              # Agent Runtime：图、planner、tools/skills/registry
│   │   ├── services/           # 任务、队列、会话、审计、审批、邀请
│   │   ├── engine/             # 分析与生成引擎：analysis / listing / facts / rules
│   │   ├── llm/                # LLM 客户端与多厂商配置
│   │   ├── market/             # 市场数据与平台接入
│   │   ├── persistence/        # 数据库、迁移、存储、密钥
│   │   └── ingest/             # CSV / JSON / Excel 导入
│   ├── config/                 # 平台规则与禁用词
│   └── tests/                  # pytest 套件
├── frontend/                   # React 19 + TypeScript（Vite）
│   ├── src/features/           # 逐页模块：dashboard / workbench / tasks / skills / stores …
│   ├── src/components/         # 书脊导航、顶栏、UI 基元、图表
│   ├── src/styles/             # 设计 Token 与语义样式
│   └── design.md               # 视觉规范（唯一来源）
├── assets/readme/              # 本 README 的图形与截图
├── examples/                   # CSV / JSON 导入模板
├── docker-compose.yml          # 本地 PostgreSQL 16
├── render.yaml                 # Render Blueprint
└── vercel.json                 # Vercel 静态托管 + /api 反代
```

---

## 敏感信息

- API Key、店铺凭据只加密存储，返回时仅给引用与掩码；
- 日志与模型上下文统一经过 `surge/engine/scrubbing.py` 脱敏；
- 审计日志的 `detail` 字段在写入前同样脱敏。

---

## 已知限制

1. **平台规则未核验。** `config/*.json` 为初始配置，不能作为合规依据，发布前需人工复核。
2. **评论主题识别基于规则词典。** 同义表达可能漏检；样本量小时占比波动大。
3. **真实模型需自备 Key 实测。** LLM 链路已用假客户端验证（含编造数字、认证、功效的反例拦截），真实文案质量取决于所选模型。
4. **审批不等于发布。** 平台发布接口未接入，审批通过只记录结论。
5. **会话不共享。** 聊天记录属于个人；团队共享的是任务、报告与草稿。
6. **重试默认断点续跑。** `POST /api/tasks/{id}/retry` 复用原任务已成功步骤的输出，只从失败点继续；`?resume=false` 整任务重跑。仅适用于 Agent 工作流任务，新任务带 `retry_of` 血缘。
7. **历史 Listing 可能没有商品事实快照**，无法复检；新生成与新版本可以。
8. **真实平台数据与授权待接入。** 连接器缺凭据时显式报错，不会退回本地数据。
9. **arq 队列需要 Redis。** 默认线程执行器不依赖外部服务。
10. **只支持 OpenAI 兼容协议。** Anthropic / Gemini 原生协议未适配。
11. **单实例假设。** 线程队列、取消语义、限流计数都假设只有一个进程。

---
