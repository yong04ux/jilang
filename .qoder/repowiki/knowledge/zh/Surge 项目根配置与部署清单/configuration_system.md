## 1. 使用的系统与工具

- **核心框架**：`pydantic-settings.BaseSettings`（依赖 `pydantic>=2.7`），通过 `SettingsConfigDict(env_prefix="SURGE_", env_file_encoding="utf-8", extra="ignore")` 声明。
- **环境变量来源**：进程环境 + `.env` 文件（由 `python-dotenv` 驱动，在 `BaseSettings.__init__` 时动态传入 `_env_file`）。
- **可配置数据文件**：`backend/config/` 下的 `platform_rules.json`、`banned_terms.json`，通过 `load_json_config()` 加载。
- **部署级配置**：`docker-compose.yml`（本地 PostgreSQL）、`render.yaml`（Render 环境变量注入）、`vercel.json`（Vercel Serverless 函数入口与头部策略）、根 `pyproject.toml`（Vercel entrypoint）。

## 2. 关键文件

| 文件 | 职责 |
|---|---|
| `backend/surge/config.py` | Settings 模型、`.env` 解析、JSON 规则加载、`get_settings()` 单例 |
| `backend/pyproject.toml` | Python 包元数据，声明 `pydantic-settings`、`python-dotenv` 依赖 |
| `render.yaml` | Render 生产环境的环境变量清单（含敏感项标记 `sync: false`） |
| `vercel.json` | Vercel Serverless 入口、Cron、响应头策略 |
| `docker-compose.yml` | 本地 Postgres 容器及其环境变量 |
| `backend/surge/app.py` | 调用 `get_settings()` 装配 FastAPI，使用 settings 构造 DB、存储、队列、CORS |
| `backend/tests/test_env_file_switch.py` | 对 `resolve_env_file()` 的单元测试，覆盖 local/cloud/绝对路径/缺失等分支 |

## 3. 架构与约定

### 3.1 配置分层

```进程环境变量 → .env 文件 → Settings 字段默认值```

- 所有运行时配置统一以 `SURGE_` 为前缀（`Settings.model_config.env_prefix = "SURGE_"`），例如 `SURGE_DATABASE_URL`、`SURGE_SECRET_KEY`、`SURGE_STORAGE_BACKEND`。
- `Settings` 中每个字段都有合理默认值，因此**不设置任何环境变量也能启动**（默认走 rule 引擎、mock 数据源、thread 队列、local 存储）。
- `.env` 文件不在模块导入期固定，而是在 `Settings.__init__` 内通过 `resolve_env_file()` 计算，这样 CLI 的 `--env` 参数或测试 monkeypatch 能在实例化前改写行为。

### 3.2 `.env` 文件定位规则（`resolve_env_file()`）

1. 未设 `SURGE_ENV_FILE` → 使用 `backend/.env`（源码部署时的默认开发文件）。
2. 相对路径（如 `.env.cloud`）→ 按 `backend/` 工程根解析，与当前工作目录无关。
3. 绝对路径 → 原样使用。
4. 文件不存在 → **直接抛 `FileNotFoundError`**，注释明确说明“静默回退是最坏的失败方式”。

该逻辑由 `test_env_file_switch.py` 覆盖：验证默认 `.env`、`.env.cloud`、绝对路径、缺失时报错、临时目录隔离等行为。

### 3.3 JSON 规则文件

- 查找顺序：当前工作目录 `config/` > `backend/config/`（`find_config_dir()`）。
- 需要存在 `platform_rules.json` 才会被识别为有效 config 目录；找不到则退回 `backend/config/`。
- `load_json_config()` 要求根节点是 dict，否则抛 `ValueError`。
- 这些文件存放运营可调的规则（字符限制、禁用词、合规声明），避免硬编码进代码逻辑。

### 3.4 配置读取模式

`get_settings()` 用 `@lru_cache(maxsize=1)` 缓存，保证进程内单例。首次调用会执行 `settings.ensure_dirs()`（创建 `data/uploads` 目录），之后返回同一个对象。

### 3.5 平台差异处理

- **Render**（常驻进程）：`render.yaml` 显式设置 `SURGE_TASK_QUEUE=thread`、`SURGE_FORCE_SYNC_TASKS=false`、`SURGE_COOKIE_SECURE=true`、`SURGE_AUTO_MIGRATE=false`，并声明数据库/密钥等敏感变量。
- **Vercel**（Serverless）：`vercel.json` 将入口指向 `backend/surge/worker_service.py`，函数超时 300s；`pyproject.toml` 的 `[tool.vercel]` 也声明了相同 entrypoint。Serverless 下必须打开 `SURGE_FORCE_SYNC_TASKS`，因为请求结束后进程会被冻结。
- **Docker Compose**：仅定义本地 Postgres，服务连接串仍通过 `SURGE_DATABASE_URL` 注入。

### 3.6 安全相关

- `secret_key` 用于加密用户 API Key；留空时本地回退到 `data/.secret_key` 文件，但 Serverless 文件系统只读，**必须显式设置 `SURGE_SECRET_KEY`**，否则会 500。
- 注释解释为什么需要这个字段：SecretBox 只读进程环境变量，而 `.env` 不会注入 `os.environ`；没有此字段时 `.env` 中的 `SURGE_SECRET_KEY` 会被 `extra="ignore"` 丢弃，导致本地与线上各一套密钥。
- Render 中将数据库 URL、迁移 URL、secret key、demo password、Supabase 凭据都标记为 `sync: false`，不写入 Blueprint。

## 4. 观察到的约定与约束

- **约定**：所有运行期配置以 `SURGE_` 为环境变量前缀，字段名与 Settings 属性一一对应（如 `SURGE_HOST` → `host`）。这是 `SettingsConfigDict(env_prefix="SURGE_")` 强制的行为。
- **约定**：新增配置应在 `Settings` 中添加字段并提供默认值，而不是在业务代码里 `os.getenv`。
- **约定**：面向运营的可调规则放在 `config/*.json`，通过 `load_json_config()` 读取，而非硬编码。
- **约定**：相对路径一律相对于 `BACKEND_ROOT`（`backend/` 工程根），由 `resolve_path()` 或 `Path.resolve()` 保证，不受 CWD 影响。
- **约束**：`.env` 文件缺失时会抛出异常（非静默回退），由 `resolve_env_file()` 实现并在测试中覆盖。
- **约束**：JSON 规则文件根节点必须是对象（dict），否则 `load_json_config()` 抛 `ValueError`。
- **约束**：Settings 使用 `extra="ignore"`，未知环境变量会被忽略——新增环境变量必须在 Settings 中声明字段才能生效。
- **约束**：`SECRET_KEY` 等敏感值不能出现在 Blueprint/仓库中，Render 通过 Dashboard 手工注入（`sync: false`）。