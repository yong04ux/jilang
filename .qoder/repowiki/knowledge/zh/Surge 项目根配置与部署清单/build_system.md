## 1. 使用的构建与部署系统

仓库采用 **双端独立构建、多平台部署** 的架构：

- **后端 (backend/)**: Python 包，使用 `setuptools` + `pyproject.toml` 打包，通过 `uvicorn` 启动 FastAPI 应用。依赖管理同时维护 `requirements.txt`（顶层，供 Vercel 使用）和 `backend/requirements.txt`（Render 使用）。
- **前端 (frontend/)**: React + TypeScript + Tailwind CSS，使用 **Vite** (`vite.config.ts`) 构建为静态资源到 `frontend/dist/`，由后端 FastAPI 直接托管。
- **容器化**: 仅 `docker-compose.yml` 提供本地开发用的 PostgreSQL 16 (Alpine) 服务，无 Dockerfile。
- **部署平台**: 同时支持 **Vercel** (serverless, `vercel.json`) 和 **Render** (常驻进程, `render.yaml`) 两种方案；另有 `render.yaml` 注释说明 Render 免费实例 15 分钟休眠行为。

## 2. 关键文件

| 文件 | 作用 |
|---|---|
| `pyproject.toml` | 仓库根元数据，声明 `tool.vercel.entrypoint = "backend.surge.worker_service:app"`，强制 Python ≥3.13 |
| `backend/pyproject.toml` | 后端包定义：`setuptools.build_meta`，包名 `surge`，入口脚本 `surge` → `surge.cli:main`，可选依赖 `queue` / `dev` |
| `backend/requirements.txt` | Render 安装依赖清单 |
| `requirements.txt` | Vercel 安装依赖清单 |
| `frontend/package.json` | Vite 构建脚本、Tailwind CLI、Node ≥22.12.0 引擎约束 |
| `frontend/vite.config.ts` | Vite 构建配置 |
| `frontend/scripts/verify-build.mjs` | 构建后校验脚本 |
| `docker-compose.yml` | 本地开发 Postgres 16-alpine |
| `vercel.json` | Vercel serverless 函数、cron、缓存与安全头策略 |
| `render.yaml` | Render Blueprint 定义，Python runtime + uvicorn 启动命令 |

## 3. 构建流程约定

### 前端构建链
```bash
npm run build:css   # tailwindcss -i src/styles/tailwind.css -o css/tailwind.css --minify
npm run typecheck    # tsc --noEmit
vite build           # 产物输出 frontend/dist/
node scripts/verify-build.mjs  # 校验 dist 目录结构
```
`build` 脚本顺序执行上述四步，确保 Tailwind 先产出、TypeScript 只类型检查不编译、Vite 再产出最终静态文件。

### 后端打包
- 包布局：`backend/` 是工程根，`surge/` 是唯一顶级包（`tool.setuptools.packages.find.include = ["surge*"]`）。
- 包数据：`skills/catalog/*/SKILL.md` 与 `skills/catalog/*/*.json` 随 wheel 发布（`tool.setuptools.package-data`），保证技能目录可被分发。
- `config/`、`tests/`、`scripts/` 明确排除在 wheel 之外（源码部署时直接读 `backend/config/`）。

### 版本管理
- 仓库根 `pyproject.toml` 中 `version = "0.1.0"`（Vercel 元数据用）。
- `backend/pyproject.toml` 中 `version = "1.0.0"`（实际发布的 Python 包版本）。
- 两个版本号独立维护，未看到自动同步机制。

## 4. 部署约定

### Vercel (serverless)
- 入口由根 `pyproject.toml` 的 `[tool.vercel] entrypoint` 指定。
- `vercel.json` 将 `backend/surge/worker_service.py` 声明为函数，`maxDuration = 300` 秒。
- 内置 cron: `0 3 * * *` 调用 `/health/deep`，用于唤醒 free 实例并保活 Supabase。
- 静态资源缓存：`/css/**` 5 分钟、`/js/**` 5 分钟、`/media/**` 24 小时。
- 安全响应头：`X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: strict-origin-when-cross-origin`。
- `public: false`，所有路径需鉴权。

### Render (常驻进程)
- `runtime: python`，`rootDir: backend`，`buildCommand: pip install -r requirements.txt`，`startCommand: uvicorn surge.worker_service:app --host 0.0.0.0 --port $PORT --workers 1`。
- 关键环境变量：
  - `SURGE_TASK_QUEUE=thread`（进程内线程队列，无需 Redis）
  - `SURGE_FORCE_SYNC_TASKS=false`（常驻进程模式）
  - `SURGE_STORAGE_BACKEND=supabase` + `SURGE_SUPABASE_BUCKET=jilang`
  - `SURGE_WEB_DIR=../frontend/dist`（前后端同源，由 FastAPI StaticFiles 托管）
  - `SURGE_AUTO_MIGRATE=false`（表已在 Supabase 上建好）
  - `SURGE_COOKIE_SECURE=true`（生产 HTTPS）
- 敏感变量（`sync: false`）需在 Dashboard 手工填入：`SURGE_DATABASE_URL`、`SURGE_MIGRATION_DATABASE_URL`、`SURGE_SECRET_KEY`、`SURGE_DEMO_PASSWORD`、`SURGE_SUPABASE_URL`、`SURGE_SUPABASE_SERVICE_KEY`。

### 本地开发
- `docker-compose.yml` 仅启动 `postgres:16-alpine`，端口 5432，数据库 `surge`，用户名 `postgres`，密码 `postgres`，卷名为 `cp-pg-data`。
- 健康检查使用 `pg_isready -U postgres -d surge`，间隔 5s、超时 3s、重试 10 次。

## 5. 约束与规则

- **Python 版本要求**：根 `pyproject.toml` 声明 `requires-python = ">=3.13"`，Render 显式设置 `PYTHON_VERSION=3.13.0`。
- **Node 版本要求**：`frontend/package.json` 的 `engines.node = ">=22.12.0"`。
- **前后端同域**：Render 下 `SURGE_WEB_DIR=../frontend/dist` 且 `SURGE_ALLOW_OPEN_REGISTRATION=false`，关闭开放注册，统一走「一键体验」临时账号。
- **任务模式差异**：`render.yaml` 注释明确区分 serverless (Vercel) 与常驻进程 (Render) 的任务处理——只有 serverless 需要 `SURGE_FORCE_SYNC_TASKS=true`。
- **前端构建产物必须预提交**：`render.yaml` 注释写明「前端构建产物（dist/ 已入库，Render 不跑 npm）」，因此 `frontend/dist/` 应纳入版本控制，而非在部署时重新构建。
- **技能数据随包发布**：`backend/pyproject.toml` 的 `package-data` 强制 `SKILL.md` 与 `*.json` schema 随 wheel 分发，否则运行时无法发现技能。
- **测试路径**：`backend/pyproject.toml` 中 `testpaths = ["tests"]`，Pytest 默认从 `backend/tests/` 运行。

## 6. 缺失项

- 无 CI/CD 配置文件（如 `.github/workflows/`、`.gitlab-ci.yml` 等）。
- 无 `Dockerfile`，容器编排仅通过 `docker-compose.yml` 提供开发环境。
- 无 Makefile 或 shell 脚本作为统一入口，各端构建命令散落在 `package.json` 与平台配置文件中。