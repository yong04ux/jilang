# 激浪

公开可访问的**跨境电商 AI 运营演示站**：访客用自己的 LLM Key（BYOK）跑通真实的
竞品分析、Listing 生成、数据导入与审批流水线。

一句话定位：**数据可以是模拟的，标记必须是真的。**

- 平台数据（店铺、商品、订单、广告、指标）默认来自**模拟数据源**，全部带 `Mock` / `示例` 标记；
- 每个数据域都实现同一套 `MarketplaceDataProvider` 协议，将来接入真实 API 只换实现、不改页面；
- 业务流程完全真实：任务、步骤、报告、Listing、导入、审批、审计都是真实读写与真实状态机；
- 跨境平台不接真实授权，`LiveMarketplaceProvider` 明确返回「未接入」，**绝不降级成 Mock**；
- 全免费部署：Vercel（静态）+ Render（API/worker）+ Supabase（PG/Storage）。

技术栈：**Python ≥ 3.10 + FastAPI + Pydantic v2 + PostgreSQL 16**。
前端为无构建步骤的原生 HTML/CSS/JS 中文界面（品牌蓝 `#1B6EF3`）。

---

## 1. 核心设计原则

1. **不编造事实**
   - 商品规格/材质/认证缺失时进入 `pending_confirmations`，文案中不出现任何具体参数；
   - 生成后逐项审计数字、认证、功效承诺，未在输入中出现即判为 `error`；
   - 模型输出残留 `[Brand]`、`{product_name}` 之类的占位符，同样判 `error`。
2. **不编造指标**
   - 关键词没有 `search_volume` / `rank` 时只列词表，不计算机会分、不推断流量；
   - 模型层用校验器强制：`has_metrics=False` 的关键词不得携带任何指标。
3. **证据分级**
   - 每条结论标记 `fact` / `statistic` / `inference` / `assumption`，尽量附竞品名或评论原文；
   - `fact` / `statistic` 在模型层要求必须有 `evidence`，否则构造失败。
4. **数据可以假，接口必须真**
   - 应用层只依赖 `MarketplaceDataProvider` 协议，不 import 具体实现；
   - Mock 每条记录带 `is_mock=True`；Live 未配置时抛 `ProviderNotConfigured`，明确 501；
   - 页面按数据源打三级标记：`示例`（种子）/ `Mock`（连接器）/ 无标（真实计算）。
5. **不伪造进度**
   - 进度就是真实 `task_steps` 的状态；只有"未完成"这一个不确定态用条纹进度条，
     **页面永不出现伪造百分比**。
6. **确定性归代码，语言归模型**
   - 价格统计、字符/字节限制、单位换算、字段校验、机会分计算全部由可测试的业务代码完成；
   - LLM 只负责目标解析、归纳与文案撰写，且输出必须通过 schema 校验与事实对齐质检。
7. **BYOK 不静默降级**
   - 平台不提供模型额度。没有可用 Key 时，需要模型的接口返回 **428 `api_key_required`**，
     前端跳转设置页；**不会降级成规则引擎后再显示"成功"**。

---

## 2. 能力总览

### 已实现

| 模块 | 能力 |
|---|---|
| **竞品分析** | 价格统计与定位、卖点覆盖、评论痛点/需求/顾虑挖掘、关键词机会（有指标才算分）、差异化机会、内容建议；**全异步**（`?async_run=true`） |
| **Listing 生成** | 标题、五点描述、产品描述、A+ 大纲、Search Terms、事实台账、逐项审计、质量检查；**全异步** |
| **多厂商 LLM** | 只做 OpenAI 兼容协议，9 个预置（DeepSeek / OpenAI / Moonshot / 智谱 / 通义 / 硅基流动 / OpenRouter / Ollama / 自定义）；多套配置、单一激活、连通性测试、`base_url` 白名单 |
| **数据导入** | CSV / JSON / Excel 逐行校验，列识别 + 字段映射 + 预览，错误可定位到单元格并可下载 CSV |
| **Agent 工作流** | 目标解析（LLM）→ 确定性计划 → LangGraph 7 节点执行 → 完整性检查 → 市场机会总结 → Listing → 质检 → 落库 |
| **注册表与自定义** | 平台内置 3 Agent / 6 Skill / 4 Tool；租户可增改停用自己的 Agent / Skill（`admin+`，软删为 `disabled`，**不能覆盖平台内置**；自定义定义为元数据，运行仍走固定工作流图） |
| **市场数据 Provider** | `MockMarketplaceProvider`（确定性种子，全 `is_mock`）与 `LiveMarketplaceProvider` 骨架；商品/订单/广告/指标四类只读接口 |
| **多租户与角色** | 个人空间自动创建、`X-Tenant-Id` 校验成员关系、viewer / editor / admin / owner |
| **任务与执行** | 任务状态机、真实步骤与耗时、线程执行器（默认）与 arq 执行器（可选）、检查点取消、失败可追踪 |
| **演示站机制** | 固定 `demo` 账号（只读示例、禁止存 Key）、一键体验 24h 临时账号、按账号限流、`seed-demo` / `cleanup-guests` 命令 |
| **审批与审计** | 发布审批（只记录结论，不接平台发布）、审计日志（敏感字段已脱敏） |
| **店铺连接** | Mock 连接器（确定性数据，全部 `is_mock`）；真实 SP-API 未接入 |
| **导出与版本** | 报告导出 md / json / csv，Listing 导出 md / json / txt、版本链与差异、编辑后复检 |

### 开发中（导航可见，界面上明确标注）

选品与市场研究 · 商品素材工作室 · 运营分析 · 工作流编排器 · 知识库

### 待接入

真实 Amazon SP-API（需卖家自注册应用并通过审核）、平台真实发布接口、关键词搜索量服务。

---

## 3. 目录结构

monorepo 布局：**`backend/`（Python 工程根）+ `frontend/`（无构建前端）+ 仓库根资产**。

```
CrossPilot/
├── README.md                        # 本文件
├── render.yaml                      # Render Blueprint（rootDir: backend）
├── vercel.json                      # Vercel 静态托管 + /api/* 反代到 Render
├── docker-compose.yml               # PostgreSQL 16（本地开发用）
├── .gitignore
├── backend/                         # Python 工程根：venv / 依赖 / 测试 / 脚本都在这
│   ├── README.md                    # 后端导读
│   ├── pyproject.toml               # 打包声明（包布局：crosspilot*）
│   ├── requirements.txt             # 唯一依赖清单（含测试与可选队列）
│   ├── pytest.ini
│   ├── crosspilot.cmd               # Windows 一键启动
│   ├── .env.example                 # 配置模板（复制为 .env 后填写）
│   ├── config/
│   │   ├── platform_rules.json      # 平台/站点字符限制、禁售字符
│   │   └── banned_terms.json        # 分类禁用词、绝对化表述
│   ├── crosspilot/                  # Python 包（9 个子包按业务域划分，职责见 __init__.py）
│   │   ├── __init__.py              # 目录职责总说明
│   │   ├── __main__.py              # python -m crosspilot 薄转发 → cli.py
│   │   ├── cli.py                   # CLI：serve / demo / check / migrate / seed-demo / cleanup-guests
│   │   ├── app.py                   # FastAPI 装配：挂载路由 + 静态资源 + 错误处理
│   │   ├── worker_service.py        # 生产入口：FastAPI + worker + /health（Render 用）
│   │   ├── config.py                # pydantic-settings 配置
│   │   ├── models.py                # Pydantic 数据模型
│   │   ├── tenancy.py               # 租户上下文与角色
│   │   ├── auth.py                  # 会话与口令
│   │   ├── worker.py                # arq worker 入口（可选后端）
│   │   ├── api/                     # HTTP 层：按业务域拆分的端点（deps/handlers/helpers + 各域）
│   │   ├── agent/                   # Agent Runtime（LangGraph 图、planner、tools/skills、registry）
│   │   ├── services/                # 业务服务层（tasks/queue/conversations/audit/approvals/invites…）
│   │   ├── engine/                  # 分析与生成引擎：analysis listing listing_llm facts
│   │   │                            #   lexicon textutils rules scrubbing
│   │   ├── llm/                     # LLM 客户端与多厂商配置：llm providers provider_configs model_settings
│   │   ├── market/                  # 市场数据 Provider：marketplaces marketplace_provider
│   │   ├── persistence/             # 持久化：db migrations storage secrets
│   │   ├── ingest/                  # 数据导入：importers
│   │   └── demo/                    # 演示机制：seed demo_data demo_mode
│   ├── tests/                       # pytest 套件
│   └── scripts/                     # 检查与验收脚本（编码/前端契约/冒烟/E2E/PG 专项）
├── frontend/                        # 单一前端（无构建，原生 HTML/CSS/JS）
│   ├── index.html
│   ├── assets/                      # logo-mark.svg / logo-full.svg / favicon.svg
│   ├── css/{tokens,base,components,layout,pages}.css
│   ├── js/{api,auth,catalog,render,router,shell,ui,async-run,icons,app}.js + pages/
│   └── scripts/                     # 前端侧脚本：vercel-build.mjs（部署搬运）+ ui_*.mjs（诊断）
├── integrations/
│   ├── HARNESS_INTEGRATION.md       # 集成方案与已验证事实
│   └── harness-plugin/              # Cordis 工具插件骨架
├── skills/
│   └── crosspilot-listing/SKILL.md
├── examples/                        # CSV / JSON 示例文件
└── docs/                            # 设计文档、改造计划、部署手册
```

---

## 4. 安装

环境要求：**Python ≥ 3.10** + **PostgreSQL 16**。

```bash
cd backend                         # Python 工程根：venv / 依赖 / 测试都在这里
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，至少填写 CROSSPILOT_DATABASE_URL
```

也可以用可编辑模式安装（装完可在任意目录使用 `crosspilot` 命令）：

```bash
cd backend
pip install -e .
```

> 目录约定：`backend/` 是 Python 工程根（venv、依赖、测试、脚本都在这）；
> 仓库根的 `frontend/` 是前端静态站；包代码在 `backend/crosspilot/`。
> 所有 Python 命令都在 `backend/` 下执行——站在仓库根运行会报
> `No module named crosspilot`，不是安装失败，是站错了目录。

---

## 5. 启动

### 数据库

需要先准备 PostgreSQL 16，并在 `.env` 里配置连接串：

```
CROSSPILOT_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/crosspilot
```

缺省时应用拒绝启动，不会静默回退到 SQLite。
迁移在启动时自动执行；也可手动执行并查看版本：

```bash
crosspilot migrate
```

本地开发环境可用仓库附带的 `docker-compose.yml` 快速起一个库：

```bash
docker compose up -d
```

### 服务

本地开发（等价于生产入口，含 `/health`；在 `backend/` 下执行）：

```bash
uvicorn crosspilot.worker_service:app --host 127.0.0.1 --port 8000
```

或未安装本包时：

```bash
cd backend
export PYTHONPATH=.            # Windows: $env:PYTHONPATH='.'
python -m crosspilot serve --port 8000
```

或直接用 uvicorn 起 API（不含 `/health`）：

```bash
cd backend
export PYTHONPATH=.
uvicorn crosspilot.app:app --host 0.0.0.0 --port 8000
```

启动后打开 `http://127.0.0.1:8000/`。首次访问会引导创建管理员账号；
配置了 `CROSSPILOT_DEMO_PASSWORD` 时会自动创建 `demo` 账号。

### 演示站：种子数据与清理

```bash
cd backend
# 写入 demo 账号 + 3 份示例报告 + 3 份示例 Listing + 6 个示例任务
export CROSSPILOT_DEMO_PASSWORD="demo-pass-1234"
python -m crosspilot seed-demo

# 删除过期的一键体验临时账号及其数据
python -m crosspilot cleanup-guests
```

### 其他 CLI

```bash
python -m crosspilot check          # 检查依赖、规则文件、数据库连通性
python -m crosspilot demo           # 用模拟数据在终端跑通分析 + 生成
python -m crosspilot demo --json out.json
python -m crosspilot migrate        # 应用迁移并打印版本
```

### 启动失败对照表

| 报错 | 原因 | 处理 |
|---|---|---|
| `DatabaseError: 无法连接数据库` | PostgreSQL 未启动或连接串错误 | 先启动数据库，核对 `CROSSPILOT_DATABASE_URL` |
| `ModuleNotFoundError` | 依赖未安装 | `cd backend && pip install -r requirements.txt` |
| `No module named crosspilot` | 站在 `backend/` 外，或未安装、未设 `PYTHONPATH` | 回到 `backend/`，或 `pip install -e .` |
| `[Errno 10048]` 端口占用 | 端口已被占用 | 换端口：`--port 8010` |

---

## 6. 测试

```bash
cd backend
pytest
```

需要测试数据库。默认使用 `CROSSPILOT_DATABASE_URL`，也可单独指定：

```bash
cd backend
export CROSSPILOT_TEST_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/crosspilot"
pytest
```

> 测试会在独立 schema / 独立数据上运行，不会污染开发库。

### 检查与验收脚本

```bash
cd backend
python scripts/check_encoding.py   # 源文件 UTF-8 与语法（覆盖 backend + frontend + docs）
python scripts/check_frontend.py   # 前端资源契约与 JS 语法
python scripts/smoke_new.py        # 新接口冒烟（数据源 / 多厂商 / 演示机制 / 异步）
python scripts/live_check.py       # 对运行中的服务做 HTTP 端到端断言
python scripts/pg_check.py <PG_URL> --reset   # PostgreSQL 专项验收

# 交互验收脚本在 frontend/scripts/（只吃 URL，与工作目录无关）
node frontend/scripts/ui_flows_v2.mjs http://127.0.0.1:8000   # 交互验收：抽屉、异步、配置表单、SSRF 拦截
node frontend/scripts/ui_workbench_v2.mjs http://127.0.0.1:8000  # 工作台运行态：两栏 + 三个结果 Tab
node frontend/scripts/ui_shots_auth_v2.mjs http://127.0.0.1:8000 ./shots  # 逐页截图
```

### 测试覆盖要点

| 文件 | 覆盖点 |
|---|---|
| `test_analysis.py` | 输入校验、去重、评论痛点与原文证据、否定句不误判、价格统计、无指标关键词不打分 |
| `test_listing.py` | 完整生成、缺规格不编造、未支持数字/认证/功效报错、占位符拦截、字符与字节限制 |
| `test_importers.py` | CSV/JSON/Excel 各分支、BOM + 中文表头、同名合并、逐行错误 |
| `test_api.py` | 健康检查、页面、demo 数据集、分析/生成、422/404/502/503、测试隔离 |
| `test_migrations.py` | 新库全量迁移、幂等、旧库升级不丢数据 |
| `test_tenancy.py` | 个人租户、伪造 `X-Tenant-Id` 403、跨租户 404、角色权限、成员邀请 |
| `test_agent.py` | 图计划与节点、失败定位、LLM 降级、不编造指标 |
| `test_conversations.py` | 会话 CRUD、自动标题、隐私边界、viewer 权限 |
| `test_async_runs.py` | 异步完成、检查点取消、终态幂等 |
| `test_planner.py` | 规则解析、LLM 成功/失败降级、Prompt 脱敏 |
| `test_audit.py` | 关键动作审计、Key 脱敏、admin 权限 |
| `test_approvals.py` | 发起/通过/拒绝、角色限制、不谎称已发布 |
| `test_invites.py` | 关闭注册开关、令牌一次性、过期/无效 |
| `test_reports_export.py` | 双写、多格式导出、租户隔离 |
| `test_listing_versions.py` | 版本链、差异、编辑后复检 |
| `test_import_preview.py` | 列识别、字段映射、预览/提交、错误 CSV |
| `test_stores.py` | Mock 确定性同步、`is_mock`、凭据加密、live 拒绝 |
| `test_marketplace_provider.py` | Mock 确定性、Live 缺凭据报错不降级、工厂拒绝未知模式、数据域状态 |
| `test_provider_configs.py` | `base_url` 白名单与 SSRF 拦截、加密落库、掩码、激活/删除回落、demo 账号禁止写入 |
| `test_demo_mode.py` | BYOK 428、一键体验临时账号、过期检测与清理、限流、异步竞品分析真实步骤 |
| `test_isolation_matrix.py` | 多类资源跨租户 404、权限矩阵 |

---

## 7. API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` 及 SPA 路由 | 前端外壳（`/dashboard` 为默认页） |
| POST | `/api/auth/register` / `login` / `logout` | 注册 / 登录 / 退出 |
| POST | `/api/auth/demo` | 一键体验：创建 24h 临时账号并直接登录 |
| GET | `/api/auth/status` / `me` | 登录状态与账号（含 `is_guest`） |
| GET | `/api/health`、`/api/platforms`、`/api/platform-rules/{p}/{m}`、`/api/ban-lists` | 元信息与规则；health 含 `worker` / `requires_api_key` |
| GET | `/api/demo/dataset` | 模拟数据集（标记 demo） |
| POST | `/api/analyze/validate`、`/api/analyze[?async_run=true]` | 竞品分析（异步返回 `task_id` + `plan`） |
| GET | `/api/reports` / `{id}`、`/api/reports/{id}/export` | 报告查询与导出 |
| POST | `/api/listings/generate[?async_run=true]` | 生成 Listing（异步强制 BYOK） |
| GET | `/api/listings` / `{id}` | Listing 查询 |
| POST | `/api/listings/{id}/versions`、`GET /{id}/versions`、`GET /{id}/diff` | 版本链与差异 |
| POST | `/api/listings/{id}/check`、`GET /{id}/export` | 复检与导出 |
| POST | `/api/import`、`/api/import/preview`、`/api/import/commit` | 一步导入 / 预览 / 提交 |
| GET | `/api/data-sources` / `{id}`、`/{id}/errors.csv` | 数据源与错误清单 |
| GET | `/api/marketplace/sources` | 每个数据域的 Provider 模式、是否已接入、最后同步 |
| GET | `/api/marketplace/overview` / `products` / `orders` / `ads` / `metrics` | 市场数据（默认 Mock，全部 `is_mock`） |
| GET | `/api/settings/providers` | 预置厂商 + 已保存配置（Key 掩码） |
| POST | `/api/settings/providers` | 新增/更新一套配置（`base_url` 白名单） |
| DELETE | `/api/settings/providers/{id}` | 删除配置（删掉激活项自动回落） |
| POST | `/api/settings/providers/{id}/test` | 最小连通性测试（消耗极少额度） |
| POST | `/api/settings/providers/{id}/activate` | 设为当前使用 |
| GET/PUT/DELETE | `/api/settings/model`、`POST /test` | 旧的单套模型配置（保留兼容） |
| GET | `/api/agent/resolve` | 自然语言目标 → 结构化参数（需 Key） |
| POST | `/api/agent/runs` | 运行 Agent（支持 `async_run`，需 Key） |
| GET | `/api/agents` / `/api/skills` / `/api/tools` | 注册表（平台内置 + 本租户自定义） |
| POST/PUT/DELETE | `/api/agents[...]`、`/api/skills[...]` | 租户自定义 Agent / Skill（`admin+`；软删为 `disabled`；不能改平台内置） |
| GET | `/api/tasks`、`/api/tasks/{id}`、`POST /api/tasks/{id}/cancel`、`POST /api/tasks/{id}/retry` | 任务中心（重试仅限失败/取消的 Agent 工作流任务，默认断点续跑、`?resume=false` 整任务重跑；新建任务带 `retry_of` 血缘） |
| GET | `/api/conversations` 及其子路由 | 会话与消息 |
| GET | `/api/stores` 及其子路由 | 店铺连接（Mock） |
| GET | `/api/approvals`、`POST /api/approvals`、`POST /{id}/decide` | 发布审批 |
| GET | `/api/audit` | 审计日志（admin/owner） |
| GET/POST | `/api/tenants/invites` | 邀请令牌 |
| GET | `/api/tenants`、`/api/tenants/current`、`/api/tenants/members` | 租户与成员 |
| GET | `/api/dashboard` | 聚合统计 + 14 天任务趋势 + 数据源状态 |
| GET | `/docs` | OpenAPI 文档 |

---

## 8. 数据导入格式

CSV 列（表头支持中英文别名）：

| 列名 | 必填 | 说明 |
|---|---|---|
| `name` | ✅ | 竞品名称 |
| `brand` / `asin` / `category` | | 基本信息 |
| `price` / `currency` | | 价格；负数报错 |
| `rating` | | 0–5；越界报错 |
| `review_count` | | 评论总数（不等于样本数） |
| `key_features` | | 用 `\|` 分隔多个卖点 |
| `specifications` | | `容量:750ml\|材质:塑料` 或 JSON |
| `review_text` / `review_rating` / `review_title` / `review_date` | | 一条评论；多行可重复填写 |
| `is_demo` | | 真实数据填 `false` |

JSON 支持顶层数组，或 `{"competitors": [...], "keywords": [...]}`。

错误会逐行返回，不会静默丢弃：

```json
{
  "ok": false,
  "errors": [
    {"row": 2, "field": "name", "message": "缺少必填字段 name（商品名称）"},
    {"row": 3, "field": "price", "message": "价格不是合法数字: 'abc'"}
  ]
}
```

示例见 `examples/competitors_sample.csv` 与 `examples/competitors_sample.json`。

---

## 9. 配置

复制 `.env.example` 为 `.env` 后按需修改：

| 变量 | 默认 | 说明 |
|---|---|---|
| `CROSSPILOT_DATABASE_URL` | 必填 | PostgreSQL 连接串（线上用 Supabase 6543 pooler） |
| `CROSSPILOT_MIGRATION_DATABASE_URL` | 空 | 迁移专用直连串（Supabase 5432）；为空则用 `DATABASE_URL` |
| `CROSSPILOT_HOST` / `CROSSPILOT_PORT` | `127.0.0.1` / `8000` | 监听地址与端口 |
| `CROSSPILOT_SECRET_KEY` | 自动生成文件 | API Key 加密主密钥；**一旦设定不要改**（改了旧 Key 全部失效） |
| `CROSSPILOT_REQUIRE_API_KEY` | `true` | BYOK 强制；`false` 时退回"缺 Key 降级并明确标注"（仅本地/测试用） |
| `CROSSPILOT_PROVIDER` | `rule` | 进程级默认 Provider（无用户配置时兜底） |
| `CROSSPILOT_DEMO_PASSWORD` | 空 | 固定 `demo` 账号的密码；为空则不创建该账号 |
| `CROSSPILOT_GUEST_TTL_HOURS` | `24` | 一键体验临时账号有效期 |
| `CROSSPILOT_RATE_LIMIT_ENABLED` | `true` | 是否启用按账号限流 |
| `CROSSPILOT_RATE_LIMIT_TASKS_PER_HOUR` | `10` | 每账号每小时任务数 |
| `CROSSPILOT_RATE_LIMIT_KEY_TESTS_PER_HOUR` | `5` | 每账号每小时 Key 测试数 |
| `CROSSPILOT_MARKETPLACE_MODE` | `mock` | 市场数据默认模式；真实接入按连接逐个切换 |
| `CROSSPILOT_ALLOW_OPEN_REGISTRATION` | `true` | 关闭后除首个用户外必须持邀请令牌 |
| `CROSSPILOT_TASK_QUEUE` | `thread` | `thread`（进程内）或 `arq`（需 Redis + worker） |
| `CROSSPILOT_REDIS_URL` | `redis://127.0.0.1:6379/0` | arq 队列使用的 Redis |
| `CROSSPILOT_AUTO_MIGRATE` | `true` | 生产建议 `false`，改由 `crosspilot migrate` 显式迁移 |
| `CROSSPILOT_COOKIE_SECURE` | `false` | HTTPS 部署必须设 `true` |
| `CROSSPILOT_STORAGE_BACKEND` | `local` | `local` 或 `supabase` |
| `CROSSPILOT_SUPABASE_URL` / `_SERVICE_KEY` / `_BUCKET` | 空 / 空 / `crosspilot` | Supabase Storage 配置 |
| `CROSSPILOT_ALLOWED_ORIGINS` | 空 | CORS 允许来源（逗号分隔）；空表示仅同源 |
| `CROSSPILOT_DATA_DIR` | `data/` | 本地存储与密钥目录 |
| `CROSSPILOT_MAX_UPLOAD_BYTES` | 5 MB | 上传限制 |

`.env.example` 不含任何真实密钥；`.env` 已在 `.gitignore` 中。

---

## 10. 敏感信息

- API Key、店铺凭据只加密存储，返回时仅给引用与掩码；
- 日志与模型上下文统一经过 `crosspilot/engine/scrubbing.py` 脱敏；
- 审计日志的 `detail` 字段在写入前同样脱敏。

---

## 11. 模拟数据声明（核心约束）

`crosspilot/demo/demo_data.py`、`MockMarketplaceProvider` 与 Mock 店铺连接器的所有商品、价格、
评分、评论、关键词、订单、广告数据均为**虚构数据**，全部带 `is_demo` / `is_mock` 标记：

- 报告与草稿会带 `data_provenance.is_demo = true` 与「请勿用于真实经营决策」警告；
- 界面按数据源打三级标记：`示例`（种子/演示）、`Mock`（模拟连接器）、无标（真实计算）；
- 页面顶部固定一条可关闭的提示条：「当前为演示数据 · 真实平台接口未接入」；
- Live Provider 未配置时 UI 显示「未接入（待审核）」并禁用同步按钮，**不隐藏、不降级成 Mock**；
- 设置页「数据源」区块列出每个域当前使用哪个 Provider、模式、最后同步时间。

这些数据不是真实 Amazon 商品，也不含任何真实销量、搜索量或排名。

---

## 12. 与 DeepSeek Harness 集成

详见 [`integrations/HARNESS_INTEGRATION.md`](integrations/HARNESS_INTEGRATION.md)。

- **方式 A（已验证）**：把 `skills/crosspilot-listing/` 放入 Harness 的技能目录，
  模型即可按 Skill 指引调用 CrossPilot HTTP 接口。
- **方式 B（骨架）**：`integrations/harness-plugin` 使用真实的 `defineTool` API，
  已通过 TypeScript 编译与 mock 宿主冒烟测试，但尚未在真实宿主进程中加载验证。

---

## 13. 已知限制

1. **平台规则未核验**。`config/*.json` 为示例配置，不能作为合规依据，发布前需人工复核。
2. **评论主题识别基于规则词典**。同义表达可能漏检；样本量小时占比波动大。
3. **真实模型未做端到端验证**。LLM 链路已用假客户端完整验证（含编造数字/认证/功效的反例拦截），
   但真实文案质量需配置 Key 后实测。
4. **审批不等于发布**。平台发布接口未接入，审批通过只记录结论。
5. **会话不共享**。聊天记录属于个人；团队共享的是任务、报告与草稿。
6. **重试默认从断点续跑**：`POST /api/tasks/{id}/retry` 复用原任务**已成功步骤**的输出
   （含 LLM 生成的 Listing），只从失败点继续，被复用的步骤在时间线标注「复用上次成功步骤（未重跑）」；
   `?resume=false` 则整任务重跑。仅 Agent 工作流任务，新建任务带 `retry_of` 血缘。
7. **历史 Listing 可能没有商品事实快照**，无法复检；新生成与新版本可以。
8. **真实平台数据未接入**。`LiveMarketplaceProvider` 只是骨架：构造时校验凭据，
   缺凭据即抛 `ProviderNotConfigured`，调用一律 501。商品/订单/广告/指标目前全部来自 Mock。
9. **arq 队列需要 Redis**。默认线程执行器不依赖外部服务；线上用 `CROSSPILOT_TASK_QUEUE=thread`。
10. **只支持 OpenAI 兼容协议**。Anthropic / Gemini 原生协议未适配（非兼容协议，需要独立适配器）。
11. **单实例假设**。线程队列、取消语义、限流计数都假设只有一个进程；Render 免费也只有单实例。

---

## 14. 设计文档

| 文档 | 内容 |
|---|---|
| `docs/00-audit-current-state.md` | 项目现状审计 |
| `docs/01-information-architecture.md` | 信息架构与页面规格 |
| `docs/02-roadmap-and-decisions.md` | 目标架构、数据模型、A–G 路线 |
| `docs/03-prototype-stage-b.md` | 前端改造与真实接入 |
| `docs/04-tenancy-and-agent.md` | 多租户与 Agent Runtime |
| `docs/05-stage-cd.md` | 阶段 C/D：迁移、会话、异步、审计、邀请、Planner、审批 |
| `docs/06-stage-ef.md` | 阶段 E/F：双写、导出、版本、两步导入、Mock 店铺、PostgreSQL |
| `docs/07-vercel-supabase-deployment.md` | 部署背景（已被 09/10 取代计划部分） |
| `docs/08-deliverable-spec.md` | 交付规格（背景与细节来源） |
| **`docs/09-refactor-plan.md`** | **改造总计划（唯一执行依据，M0–M8）** |
| **`docs/10-deployment-runbook.md`** | **部署手册（Supabase + Render + Vercel + 故障排查）** |

---

## 15. 后续路线

1. 接入真实 Amazon SP-API（实现 `LiveMarketplaceProvider`，配置 `store_connections.mode = "live"`，
   页面与接口不需要改）；
2. 其他真实数据源适配器（订单聚合指标、广告 API）；
3. 按任务分配模型（`user_provider_configs.task_overrides` 已预留字段）；
4. 工作流可视化编排与租户级自定义 Agent / Skill；
5. 知识库与向量检索；
6. Anthropic / Gemini 原生协议适配器（新增一个 `Provider` 实现即可）。
