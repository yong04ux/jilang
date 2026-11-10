## 1. 使用的框架与工具

- **Python 标准库 `logging`**，未引入第三方日志框架（无 loguru、structlog、python-json-logger 等）。所有模块通过 `logging.getLogger(__name__)` 获取 logger。
- 日志格式和级别在两个入口统一配置：
  - 集成部署（Render 单进程）：`backend/surge/worker_service.py` 调用 `logging.basicConfig(...)`。
  - 独立 arq worker 进程：`backend/surge/worker.py:main()` 再次调用 `logging.basicConfig(level=logging.INFO)`。
- FastAPI 应用本身不额外安装中间件或 hook；性能观测走独立的 `surge.perf` 模块，仅当 `SURGE_PROFILE=1` 时输出。

## 2. 关键文件

| 文件 | 作用 |
|---|---|
| `backend/surge/worker_service.py` | 生产进程入口，集中设置 basicConfig、全局 `SURGE_LOG_LEVEL` |
| `backend/surge/worker.py` | 独立 arq worker 进程入口，硬编码 `INFO` 级别 |
| `backend/surge/app.py` | FastAPI 装配层，按 `__name__` 取 logger，记录迁移跳过、checkpoint 初始化失败、demo 账号异常等 |
| `backend/surge/api/handlers.py` | API 外层保护器，用 logger 记录请求/任务级信息 |
| `backend/surge/services/audit.py` | 审计日志写入（业务审计事件） |
| `backend/surge/persistence/db.py` / `storage.py` | 数据库/存储层异常以 WARNING/INFO 级别记录 |
| `backend/surge/agent/checkpoint.py` | LangGraph checkpoint 初始化失败降级记录 |
| `backend/surge/services/queue.py` | 任务队列后端错误记录 |
| `backend/surge/perf.py` | 可选的性能快照，通过 `logger.info("perf ...", payload)` 输出结构化 perf 行 |

## 3. 架构与约定

### 3.1 进程级初始化
`worker_service.py` 中：
```python
logging.basicConfig(
    level=os.environ.get("SURGE_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
```
这是仓库中唯一一处定义日志格式的 basicConfig。`worker.py` 的独立进程入口只设 level 为 `INFO`，没有自定义 format，因此独立 worker 默认使用 Python 标准格式。

### 3.2 Logger 命名空间
每个模块采用 Python 惯例：`logger = logging.getLogger(__name__)`，形成层级命名（如 `surge.app`、`surge.api.handlers`、`surge.persistence.db`），便于按子树过滤。

### 3.3 日志级别策略
- **INFO**：启动配置、健康检查、正常业务流程（如 `worker_service._log_startup` 打印 queue/storage/demo_account 等运行期参数）。
- **WARNING**：可恢复的异常路径，例如 `app.py` 中 `SURGE_AUTO_MIGRATE=false` 提示、checkpoint 表初始化失败、demo 账号初始化失败、数据库不可用等。
- **ERROR**：真正的失败路径（如 listing 引擎中的规则校验失败、LLM 调用失败等，这些集中在 `engine/listing_llm.py`、`engine/listing.py`，但属于业务领域语义上的 `Severity.ERROR`，而非 Python logging 级别——业务模型 `models.py` 中的 `Severity` 枚举是独立于 logging 的领域概念）。
- 脚本类文件（`cli.py`、`check_frontend.py` 等）直接使用 `print(f"[ERROR] ...")`，不走 logging。

### 3.4 结构化字段
没有统一的 JSON 结构化日志方案。唯一接近结构化的输出是 `perf.log_line(payload, state)` 生成的一行文本，由 `app.py` 中以 `logger.info("perf %s %s %s", method, path, payload)` 方式输出，并附加 `Server-Timing` / `X-Perf` 响应头供外部采集。

### 3.5 输出目标
basicConfig 默认输出到 stderr（控制台），没有文件 handler、没有 syslog/remote sink、没有按模块分流。部署方通过环境变量 `SURGE_LOG_LEVEL` 控制级别，其他一切由容器编排（Docker Compose、Render、Vercel）负责收集 stdout/stderr。

## 4. 约定与约束

- **环境变量 `SURGE_LOG_LEVEL`**：决定进程级日志级别，默认 `INFO`，取值需能 `.upper()` 解析（`worker_service.py` 直接 `.upper()` 后传给 basicConfig，未做白名单校验）。
- **FastAPI 集成模式**：不在 FastAPI 层面注册自定义 Handler/Middleware，而是让 `logging` 根处理器接管所有 `logging.getLogger(__name__)` 的输出。
- **独立 worker 进程**：`worker.py` 的 `main()` 单独调用 `logging.basicConfig(level=logging.INFO)`，不使用 `SURGE_LOG_LEVEL`，这是一个与集成模式不一致的硬编码分支。
- **业务 `Severity` 与 Python logging 级别分离**：`models.py` 定义了 `class Severity: INFO/WARNING/ERROR`，用于 listing/engine 领域的结构化错误对象，不是日志级别，两者互不影响。
- **CLI 脚本绕过 logging**：`backend/surge/cli.py`、`backend/scripts/check_frontend.py` 等使用 `print(f"[ERROR] ...")`，不属于 logging 子系统范围。
- **无统一日志门面**：不存在一个 `surge/logging.py` 之类的封装；各模块直接 import `logging`，因此无法强制统一格式或 sink。
- **无敏感字段脱敏**：日志字符串中直接拼接异常消息（如 `f"数据库不可用：%s"`），未经过显式脱敏逻辑。