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
前端为 React + TypeScript 中文界面（Vite 构建，品牌蓝 `#1B6EF3`）。

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
| **注册表与自定义** | 平台内置 3 Agent / 7 Skill / 4 Tool；技能定义集中在 `crosspilot/skills/registry.py`，接口、执行、对话调度共用同一份；租户可增改停用自己的 Agent / Skill（`admin+`，软删为 `disabled`，**不能覆盖平台内置**；自定义定义为元数据，运行仍走固定工作流图） |
| **市场数据 Provider** | `MockMarketplaceProvider`（确定性种子，全 `is_mock`）与 `LiveMarketplaceProvider` 骨架；商品/订单/广告/指标四类只读接口 |
| **多租户与角色** | 个人空间自动创建、`X-Tenant-Id` 校验成员关系、viewer / editor / admin / owner |
| **任务与执行** | 任务状态机、真实步骤与耗时、线程执行器（默认）与 arq 执行器（可选）、检查点取消、失败可追踪 |
| **演示站机制** | 固定 `demo` 账号（只读示例、禁止存 Key）、一键体验 24h 临时账号（**可存自己的 Key**、按 IP 限流）、按账号限流、`seed-demo` / `cleanup-guests` 命令 |
| **审批与审计** | 发布审批（只记录结论，不接平台发布）、审计日志（敏感字段已脱敏） |
| **店铺连接** | Mock 连接器（确定性数据，全部 `is_mock`）；演示账号进站即预置 3 家有品牌感的店铺（含商品/订单/同步汇总，带 `is_demo`）；真实 SP-API 未接入 |
| **平台接入目录** | `/api/platforms` 开放 9 个跨境平台（Amazon / Temu / TikTok Shop / Shopee / eBay / Walmart / AliExpress / Shopify / 自定义）的能力声明、站点、`live_status` 与 OAuth 端点，另提供 `build_authorize_url()` 骨架；**授权换取环节显式抛错，不伪造 token** |
| **导出与版本** | 报告导出 md / json / csv，Listing 导出 md / json / txt、版本链与差异、编辑后复检 |

### 开发中（导航可见，界面上明确标注）

选品与市场研究 · 商品素材工作室 · 运营分析 · 工作流编排器 · 知识库

### 待接入

真实 Amazon SP-API（需卖家自注册应用并通过审核）、平台真实发布接口、关键词搜索量服务。

平台侧的**数据接口已预留**：`market/platforms.py` 声明了各平台的 `product_id_field`、`marketplaces`、`capabilities`、`oauth` 与 `live_status`，授权链接可生成；缺的是真实应用凭据与换取 token 的实现（`exchange_code()` 当前直接抛 `PlatformNotConnected`，接入时只替换这一处）。

---

## 3. 目录结构

monorepo 布局：**`backend/`（Python 工程根）+ `frontend/`（React 前端，Vite 构建）+ 仓库根资产**。

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
│   │   ├── market/                  # 市场数据与平台接入：marketplaces marketplace_provider platforms
│   │   ├── persistence/             # 持久化：db migrations storage secrets
│   │   ├── ingest/                  # 数据导入：importers
│   │   └── demo/                    # 演示机制：seed demo_data demo_mode store_data store_seed
│   ├── tests/                       # pytest 套件
│   └── scripts/                     # 检查与验收脚本（编码/前端契约/冒烟/E2E/PG 专项）
├── frontend/                        # 单一前端（React + TypeScript，Vite 构建）
│   ├── index.html
│   ├── assets/                      # logo-mark.svg / logo-full.svg / favicon.svg
│   ├── css/{tokens,base,components,layout,pages}.css
│   ├── js/{api,auth,catalog,render,router,shell,ui,async-run,icons,app}.js + pages/
│   └── scripts/                     # 前端侧脚本：verify-build / *-parity / ui_*.mjs 诊断
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

### 多环境配置（本地 / 线上）

配置文件由 `CROSSPILOT_ENV_FILE` 定位，默认 `backend/.env`。CLI 提供 `--env` 简写：

| 命令 | 使用的文件 | 典型用途 |
|---|---|---|
| `python -m crosspilot serve` | `backend/.env` | 本地 PostgreSQL + 本地上传目录 |
| `python -m crosspilot serve --env cloud` | `backend/.env.cloud` | 本地连线上 Supabase |
| `python -m crosspilot migrate --env cloud` | `backend/.env.cloud` | 对线上库跑迁移 |

`--env local` 与不带参数等价——「本地」就是 `.env` 本身，不再复制第二份内容，
避免两个文件各自演化。`--env X` 找不到 `.env.X` 时**直接报错**，不会静默退回默认配置
（那种失败最难发现：以为连着线上库，实际写进了本地库）。

`--env` 对所有子命令生效（`serve` / `demo` / `check` / `migrate` / `seed-demo` /
`cleanup-guests`），写在子命令**后面**。启动时会把实际使用的配置文件与
`用户@主机:端口/库名` 打出来（不含密码），省得反复确认"我现在连的是哪个库"。

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
# 写入 demo 账号 + 3 份示例报告 + 3 份示例 Listing + 6 个示例任务 + 3 家演示店铺（含商品/订单）
export CROSSPILOT_DEMO_PASSWORD="demo-pass-1234"
python -m crosspilot seed-demo

# 删除过期的一键体验临时账号及其数据
python -m crosspilot cleanup-guests
```

演示店铺（`EcoSip Official Store` / `PeakTrail Outdoors` / `LumiGlow Home`）由
`demo/store_data.py` 提供目录数据，与示例报告、Listing 的品牌保持一致；`seed-demo` 与
「一键体验」临时账号都会预置，名字即幂等键。店铺名命中演示目录时 Mock 连接器直接返回该目录，
自建店铺仍走原来的随机确定性逻辑。

### 对外演示上线

要让别人**在线操作**（临时账号 + 自己的 Key + 模拟数据跑一遍），看
`docs/14-supabase-vercel-from-scratch.md`。三个最容易漏的点：

1. **必须固定 `CROSSPILOT_SECRET_KEY`** —— 不设就落盘生成，免费实例重启丢文件后，
   访客已保存的 Key 全部解不开；
2. `vercel.json` 的 `rewrites.destination` 要回填成 Render 实际域名；
3. 「一键体验」按 IP 限流由 `CROSSPILOT_RATE_LIMIT_GUEST_PER_HOUR`（默认 5/h）控制。

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
# 注意：必须指向独立的测试库，不能是开发库
export CROSSPILOT_TEST_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/crosspilot_test"
pytest
```

> **⚠️ 必须用独立的测试库（如 `crosspilot_test`）。** 测试启动时会
> `DROP SCHEMA public CASCADE` 再重建，对开发库 `crosspilot` 执行会**清空业务数据**。
> 首次使用先建库：`createdb -U postgres crosspilot_test`。
>
> 当前套件 346 项，单机约 9 分钟（每个用例重建 schema，慢是正常的）。

### 检查与验收脚本

```bash
cd backend
python scripts/check_encoding.py   # 源文件 UTF-8 与语法（覆盖 backend + frontend + docs）
python scripts/check_secrets.py    # 密钥扫描：推送前跑一遍，命中 exit 1（输出只给掩码）
python scripts/check_frontend.py   # 前端资源契约 + 路由与 SPA_ROUTES 一致性 + tsc
python scripts/smoke_new.py        # 新接口冒烟（数据源 / 多厂商 / 演示机制 / 异步）
python scripts/live_check.py       # 对运行中的服务做 HTTP 端到端断言
python scripts/pg_check.py <PG_URL> --reset   # PostgreSQL 专项验收

# 交互验收脚本在 frontend/scripts/（只吃 URL，与工作目录无关）
node frontend/scripts/ui_flows_v2.mjs http://127.0.0.1:8000   # 交互验收：抽屉、异步、配置表单、SSRF 拦截
node frontend/scripts/ui_workbench_v2.mjs http://127.0.0.1:8000  # 工作台运行态：两栏 + 三个结果 Tab
node frontend/scripts/ui_shots_auth_v2.mjs http://127.0.0.1:8000 ./shots  # 逐页截图
```

> `check_secrets.py` 扫 `crosspilot/ tests/ scripts/ config/` 与根配置里的高置信度特征
> （`sk-` 长串、`AKIA`、GitHub/GitLab/Slack token、PEM 私钥、带口令的连接串）；
> 输出只打印掩码，不会把密钥写进 CI 日志。测试里的构造密钥用文件级标记放行：
> 在文件前 10 行写 `# check_secrets: allow-placeholders`。

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
| `test_platforms.py` | 平台目录与能力声明、未知平台不报错、授权链接参数、缺凭据/未授权的显式报错、`/api/platforms` 公开、演示店铺预置与幂等 |
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
| POST | `/api/auth/demo` | 一键体验：创建 24h 临时账号并直接登录（**按 IP 限流**；不受关闭注册影响；可保存自己的 Key） |
| GET | `/api/auth/status` / `me` | 登录状态与账号（含 `is_guest`） |
| GET | `/api/health`、`/api/platforms`、`/api/platform-rules/{p}/{m}`、`/api/ban-lists` | 元信息与规则；health 含 `worker` / `requires_api_key`；`/api/platforms` 另含 `catalog`（9 个平台的接入能力/站点/`live_status`/OAuth）、`capabilities`、`default_platform` |
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
| GET | `/api/settings/providers` | 预置厂商 + 已保存配置（Key 掩码；`task_overrides` 以对象返回） |
| POST | `/api/settings/providers` | 新增/更新一套配置（`base_url` 白名单；可带 `task_overrides` 按步骤分配模型） |
| DELETE | `/api/settings/providers/{id}` | 删除配置（删掉激活项自动回落） |
| POST | `/api/settings/providers/{id}/test` | 最小连通性测试（消耗极少额度） |
| POST | `/api/settings/providers/{id}/activate` | 设为当前使用 |
| GET/PUT/DELETE | `/api/settings/model`、`POST /test` | 旧的单套模型配置（保留兼容） |
| GET | `/api/agent/resolve` | 自然语言目标 → 结构化参数（需 Key） |
| POST | `/api/agent/runs` | 运行 Agent（支持 `async_run`，需 Key） |
| GET | `/api/agents` / `/api/skills` / `/api/tools` | 注册表（平台内置 + 本租户自定义） |
| POST | `/api/skills/{key}/run` | **统一技能执行入口**：参数校验 → 依赖检查 → 执行 → 落库；同步返回产出，`?async_run=true` 转任务（正文返回 `task_id`，产出另存为结果引用） |
| POST/PUT/DELETE | `/api/agents[...]`、`/api/skills[...]` | 租户自定义 Agent / Skill（`admin+`；软删为 `disabled`；不能改平台内置） |
| GET | `/api/tasks`、`/api/tasks/{id}`、`POST /api/tasks/{id}/cancel`、`POST /api/tasks/{id}/retry` | 任务中心（重试仅限失败/取消的 Agent 工作流任务，默认断点续跑、`?resume=false` 整任务重跑；新建任务带 `retry_of` 血缘） |
| GET | `/api/conversations` 及其子路由 | 会话与消息 |
| GET | `/api/stores` 及其子路由 | 店铺连接（Mock）；返回体带 `is_mock` / `is_demo` / `platform_label` / `platform_known` / `capabilities` / `can_sync` |
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
| `CROSSPILOT_RATE_LIMIT_ENABLED` | `true` | 是否启用限流 |
| `CROSSPILOT_RATE_LIMIT_TASKS_PER_HOUR` | `10` | 每账号每小时任务数 |
| `CROSSPILOT_RATE_LIMIT_KEY_TESTS_PER_HOUR` | `5` | 每账号每小时 Key 测试数 |
| `CROSSPILOT_RATE_LIMIT_GUEST_PER_HOUR` | `5` | **每 IP** 每小时「一键体验」建号数（公网部署必看） |
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

## 12. 已知限制

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
12. **免费实例会休眠**。Render free 在无请求约 15 分钟后休眠，首次访问要等 30–60 秒冷启动；
    要对外演示建议加一个定时 ping `/health` 的保活任务，或换付费实例。
13. **并发上限 2**。`CROSSPILOT_MAX_JOBS=2`（免费实例 512MB 内存），多人同时跑 LLM 会排队。
14. **临时账号需要定期清理**。`cleanup-guests` 目前要手动/定时执行，过期账号不会自动消失。

---

## 13. 设计文档

`docs/` 只保留**仍然有效**的一份文档，历史阶段的计划/审计/阶段记录已归档清理
（本地备份在 `.workbuddy/backup/`，不入库）。完整索引见 `docs/README.md`。

产品需求文档单独放在仓库根目录 [`PRD.md`](PRD.md)（**入版本库**，不随 `docs/` 一起被忽略）。

| 文档 | 内容 |
|---|---|
| `PRD.md` | **产品需求文档 v3**：对标 LinkFox、Skill 协议层、意图路由、专家模板、功能清单与验收脚本 |
| `frontend/design.md` | **视觉规范唯一来源**（v2.0，shadcn/ui Nova）：Token、组件、动效、页面级细则（§13 店铺助手、§14 技能广场、§15 AI 助手首页） |
| `docs/14-supabase-vercel-from-scratch.md` | 零账号起步的云端部署手册：重建 Supabase 库/迁移/存储桶 + 应用平台部署 |

> `docs/` 在 `.gitignore` 中，不随仓库分发。阅读时以本机文件为准。

---

## 14. 后续路线

1. 接入真实 Amazon SP-API（实现 `LiveMarketplaceProvider`，配置 `store_connections.mode = "live"`，
   页面与接口不需要改）；
2. 其他真实数据源适配器（订单聚合指标、广告 API）；
3. ~~按任务分配模型~~ —— 已实现「按步骤分配模型」：一套配置的 `task_overrides` 可让
   `analyze` / `listing` 各用不同配置或模型（见第 10 节 API 表与 §7 的能力说明）；
   剩余是跨厂商端到端验证，需要两把真实 Key；
4. ~~租户级自定义 Agent / Skill~~ —— 已实现（`POST/PUT/DELETE /api/agents`、`/api/skills`）；
   自定义定义目前是元数据，自定义执行图未做；
5. 知识库与向量检索；
6. Anthropic / Gemini 原生协议适配器（新增一个 `Provider` 实现即可）。
