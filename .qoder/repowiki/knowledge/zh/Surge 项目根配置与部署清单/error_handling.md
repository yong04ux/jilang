## 1. 采用的体系

后端采用 **Python 自定义异常 + 集中式错误分类 + FastAPI `exception_handler`** 的三层方案：

- 各业务层抛出领域异常（如 `TenantError`、`DatabaseError`、`StorageError`、`QueueBackendError`、`Skill*` 系列、`LLMError`、`ProviderError` 等）。
- 在 `backend/surge/agent/errors.py` 中通过 `classify(exc)` 把任意 `BaseException` 映射为枚举类别，并附带 HTTP 状态码、重试策略和用户文案。
- 在 `backend/surge/app.py` 中用 `@app.exception_handler(...)` 将顶层异常转为结构化的 JSONResponse；异步任务则在 `api/handlers.run_guarded` 中兜底落库为终态。

前端没有独立的 error-handling 框架，仅消费后端返回的 `{code, category, message, retryable, action, detail}` 载荷（见 `errors.ErrorInfo.as_payload` 的注释对前端的约定）。

## 2. 关键文件

| 文件 | 职责 |
|---|---|
| `backend/surge/agent/errors.py` | 错误分类核心：`ErrorCategory` 枚举、`POLICIES` 默认策略、`DEFAULT_MESSAGES`、`ErrorInfo`/`make`/`classify` |
| `backend/surge/app.py` | FastAPI 装配层，注册 `TenantError` / `DatabaseError` / `RequestValidationError` / `ValidationError` 四个全局异常处理器 |
| `backend/surge/api/handlers.py` | 队列任务外层保护 `run_guarded`，保证任何异常都落到任务的失败/取消终态 |
| `backend/surge/api/helpers.py` | `validation_errors()` 把 Pydantic `ValidationError` 转成中文列表，复用 `humanize_error` |
| `backend/surge/labels.py` | 字段名 → 中文标签、Pydantic `type` → 用户可读提示的映射表 |
| `backend/surge/tenancy.py` | 权限类异常 `TenantError` 定义处 |
| `backend/surge/persistence/db.py` | `DatabaseError` |
| `backend/surge/persistence/storage.py` | `StorageError` |
| `backend/surge/services/queue.py` | `QueueBackendError`、`TaskCancelled` |
| `backend/surge/skills/base.py` | `SkillNotFound` / `SkillForbidden` / `SkillTimeout` 等 Skill 层异常 |
| `backend/surge/agent/contracts.py` | `SkillInputInvalid`、`SkillMissingInput`、`SkillDependencyMissing` 等契约异常 |

## 3. 架构与约定

### 3.1 十类错误枚举 (`ErrorCategory`)

```python
class ErrorCategory(str, Enum):
    VALIDATION_ERROR = "validation_error"
    MISSING_INPUT = "missing_input"
    PERMISSION_DENIED = "permission_denied"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    QUALITY_GATE_FAILED = "quality_gate_failed"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"
```

每个类别都有默认 `http_status`、`retryable`、`user_action`，由 `POLICIES` 集中声明。例如 `MODEL_TIMEOUT` 可重试且返回 504，`VALIDATION_ERROR` 不可重试且返回 422，`INTERNAL_ERROR` 固定 500。

### 3.2 `ErrorInfo` 作为分类结论

`ErrorInfo` 同时保留面向用户的 `message` 和仅供日志的 `log_message`，并通过 `as_payload()` 输出扁平结构，其中 `task_code` 属性直接取 `category.value`，用于写入 `tasks.error_code`。构造统一走 `make(category, ...)`，未指定的字段从 `POLICIES` / `DEFAULT_MESSAGES` 回填。

### 3.3 `classify(exc)` — 按类型逐个判定的映射表

`classify` 是异常到分类的唯一入口，规则按优先级排列：

1. `TaskCancelled` → `CANCELLED`（控制流，不是错误）
2. Skill 层异常（`SkillMissingInput`、`SkillInputInvalid`、`SkillNotFound`、`SkillDisabled`、`SkillNotExecutable`、`SkillForbidden`、`SkillDependencyMissing`、`SkillTimeout`）→ 各自映射
3. `LLMError` → 按 `kind`（`rate_limit`/`network`/`auth`/`bad_request`/`server`/`invalid_json`/`empty`）分支
4. `ProviderError` → `PROVIDER_UNAVAILABLE`
5. 数据源 `CompetitorProviderError` / `ProviderNotConfigured`
6. `pydantic.ValidationError` → `VALIDATION_ERROR`
7. `AnalysisInputError` / `ImportValidationError` / `ListingError` → `VALIDATION_ERROR`
8. 裸 `ValueError` → `VALIDATION_ERROR`（文档说明 engine 层用它表达输入校验失败）
9. `TenantError` / 带 `status_code in (401,403)` 的异常 → `PERMISSION_DENIED`
10. `DatabaseError` → `PROVIDER_UNAVAILABLE`
11. `TimeoutError` → `MODEL_TIMEOUT`
12. 未知异常 → `INTERNAL_ERROR`

所有跨层导入都放在函数内部，避免 `agent` 包反向依赖 `api`/`services` 造成循环。

### 3.4 FastAPI 全局异常处理器

`app.py` 中注册了四类处理器：

- `TenantError` → 403，`{"detail": str(exc)}`
- `DatabaseError` → 503，固定中文消息「数据服务暂时不可用，请稍后重试」
- `RequestValidationError` → 422，`detail.message` + `detail.errors[]`（经 `humanize_error` 翻译）
- `pydantic.ValidationError` → 422，同样走 `helpers.validation_errors` → `humanize_error`

其他未被捕获的异常会走 FastAPI 默认的 500，但不会把堆栈暴露给前端——开发者应主动抛上述领域异常或让 `classify` 归入 `INTERNAL_ERROR`。

### 3.5 异步任务保护

`handlers.run_guarded` 包裹队列执行体：

- `TaskCancelled` → 记录 info 日志，不抛（job 自己已落库为 cancelled）
- 其他 `BaseException` → `recorder.fail(code="worker_error", message=...)` + `logger.exception`，再向上重抛 `KeyboardInterrupt` / `SystemExit`

这是防止任务永远停在 `running` 状态的最后一道防线。

### 3.6 用户文案与敏感信息隔离

`labels.humanize_error` 把 Pydantic 的英文原句（如 `"Input should be a valid number"`）和内部字段名（如 `own_key_features`、`deepseek`）翻译成中文；`ErrorCategory.DEFAULT_MESSAGES` 提供面向用户的中文文案。原始异常文本只进入 `log_message`，不进 API 响应。`classify` 中显式截断 raw 字符串为 500 字符，避免长堆栈污染日志。

## 4. 观察到的约定与约束

- **唯一分类点**：`agent/errors.py` 的注释明确声明“这里建立唯一分类点”，所有失败都应走 `classify`/`make`，而不是在各处写 `code="agent_step_failed"`。
- **不做重试**：`ErrorPolicy.retryable` 只是声明，具体重试逻辑由调用方决定（当前 dispatcher 只对超时重试，图节点不重试），`errors.py` 不实现退避或队列重投。
- **不向用户暴露异常原文**：`message` 一律是面向用户的中文说明，原始文本只在 `log_message` 里供日志使用，不进 API 响应。
- **按类型判定而非按消息猜**：`classify` 使用 `isinstance` 逐个判断异常类，注释说明“猜消息会在文案改动时静默失效”。
- **细粒度 `code` + 粗粒度 `category` 双字段**：`ErrorInfo.code` 用于定位具体原因（如 `llm_auth_failed`、`database_unavailable`），`category` 决定处置策略；两者都要保留。
- **任务必须落终态**：`handlers.py` 的模块级注释强调“任何异常都必须把任务落到终态：任务停在 running 会让前端无限轮询”。
- **权限错误统一 403**：`TenantError` 以及带 `status_code in (401,403)` 的异常都被归类为 `PERMISSION_DENIED`。
- **数据库/存储/队列配置错误在启动期转换为 `RuntimeError`**：`app.py` 在构建 storage 和 task_queue 时捕获 `StorageError` / `QueueBackendError` 并 raise `RuntimeError`，使启动失败可见。
- **验证错误统一 422 结构化载荷**：FastAPI 的 `RequestValidationError` 和 Pydantic v2 的 `ValidationError` 都通过同一套 `humanize_error` 流程，返回 `{detail: {message, errors[]}}`。
- **Skill 层异常集中在 `skills/base.py` 与 `agent/contracts.py`**：`SkillNotFound`/`SkillForbidden`/`SkillTimeout`/`SkillInputInvalid`/`SkillMissingInput`/`SkillDependencyMissing` 等被 `classify` 一一识别。
- **裸 `ValueError` 被视为输入校验失败**：`classify` 最后才匹配 `ValueError`，并注释说明 engine 层用它表达输入校验失败，需放在更精确的子类之后。

## 5. 缺失或不一致之处

- 只有 FastAPI 层面的全局异常处理器；业务层 handler 内部仍需自行 try/except 或抛出上述领域异常，不存在统一的中间件拦截器。
- `classify` 中的映射表持续增长（约 40+ 行 if/elif），属于集中式 but monolithic 的分类逻辑，尚未看到基于注册表的扩展机制。
- 前端侧未见与 `category`/`retryable`/`action` 字段对应的完整错误展示组件（仓库以静态 HTML/CSS 为主，JS 产出位于 `frontend/dist/js`），错误 UI 可能仍依赖后端 `message` 字段直出。
