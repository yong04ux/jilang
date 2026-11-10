## 总体方案

仓库是 monorepo：`backend/` 为 Python FastAPI 服务，`frontend/` 为 React+TypeScript 前端静态站点。两套技术栈各自使用原生工具链管理第三方依赖，不存在跨语言的统一锁文件或私有注册表。

- **后端**：`setuptools` + `requirements.txt` 双清单；`pyproject.toml` 仅声明运行时 `dependencies` 和可选依赖（`queue`、`dev`），不启用 `pip-tools` / `Poetry` / `uv` 等更严格的锁定机制。
- **前端**：`npm` + `Vite`，`package.json` 用 `^` 语义化版本范围，唯一锁定产物 `frontend/package-lock.json` 提交到仓库。
- **根级**：`pyproject.toml` 与 `requirements.txt` 只是 Vercel 部署的薄包装——前者声明入口点 `backend.surge.worker_service:app`，后者 `-r backend/requirements.txt` 转发。

## 关键文件

| 文件 | 作用 |
|---|---|
| `backend/pyproject.toml` | 包元数据、运行时依赖、可选依赖 (`queue`/`dev`)、setuptools 包发现与 package-data 规则 |
| `backend/requirements.txt` | 唯一 pip 依赖清单（运行 + 测试 + arq worker），注释标注了每个分组用途 |
| `requirements.txt` | 根级 shim，仅 `-r backend/requirements.txt` |
| `pyproject.toml` | 根级 shim，仅 `[tool.vercel] entrypoint` |
| `frontend/package.json` | 前端依赖、脚本（dev/build/parity/smoke 等）、Node 引擎约束 `>=22.12.0` |
| `frontend/package-lock.json` | npm 安装锁文件 |

## 架构与约定

1. **后端依赖分层**
   - `backend/pyproject.toml[project.dependencies]` 声明运行时依赖（fastapi、uvicorn、pydantic、langgraph、openai、psycopg[binary] 等）。
   - `backend/pyproject.toml[project.optional-dependencies]` 把队列依赖 (`arq`, `redis`) 与开发依赖 (`pytest`, `httpx`) 分离。
   - `backend/requirements.txt` 则是面向部署/CI 的扁平化清单，同时包含运行、测试、可选 arq worker 所需的全部包；它被视作“唯一清单”，注释明确写有 `# Surge 依赖（唯一清单）`。
   - `backend/pyproject.toml[tool.setuptools.package-data]` 将技能目录下的 `SKILL.md` 与 `*.json` schema 打入 wheel，否则运行时找不到技能定义。
   - `backend/pyproject.toml[tool.setuptools.packages.find]` 只 include `surge*`，并显式排除 `tests/scripts/config`（`config/` 是纯数据目录，不能列为包）。

2. **版本策略**
   - Python 端普遍采用“主版本上限”范围（如 `fastapi>=0.115,<1.0`、`langgraph>=1.0,<2.0`、`langchain-anthropic>=1.7,<2.0`），允许次/补丁升级但阻止破坏性大版本升级；少数包（如 `openai>=1.40`、`psycopg[binary]>=3.2`）仅设下限。
   - 前端依赖使用 npm 的 `^` 范围（例如 `react ^19.3.1`、`@tanstack/react-query ^5.105.0`），由 `package-lock.json` 固定实际解析结果。

3. **构建与部署集成**
   - Vercel 通过根 `pyproject.toml` 的 `[tool.vercel] entrypoint` 指向 `backend.surge.worker_service:app`；根 `requirements.txt` 让 Vercel 能读取后端依赖。
   - Render 部署定义在 `render.yaml`（未在此处展开），Docker Compose 编排数据库与服务。
   - 前端 `build` 脚本顺序执行 Tailwind 编译、`tsc --noEmit`、`vite build`、`node scripts/verify-build.mjs`，产物输出到 `frontend/dist/`，由 FastAPI 直接托管。

4. **没有私有注册表或镜像配置**
   - 仓库中未发现 `pip.conf`、`PIP_INDEX_URL`、`PYPI_MIRROR`、`.npmrc` 等任何私有源/代理配置；所有依赖均从公共 PyPI/npm registry 拉取。

## 约定与约束

- 新增 Python 运行时依赖应同时出现在 `backend/pyproject.toml[project.dependencies]` 与 `backend/requirements.txt`，以保持两者同步（根 `requirements.txt` 已强制通过 `-r backend/requirements.txt` 避免根级漂移）。
- 可选功能（任务队列）必须通过 `pip install surge[queue]` 或 `--extra-index-url` 外的方式启用，依赖名见 `backend/pyproject.toml[project.optional-dependencies]`。
- Node.js 版本被 `engines.node >=22.12.0` 约束，前端依赖以 `package.json` 中的 `^` 范围为主，实际安装版本锁定在 `frontend/package-lock.json`。
- 技能（skills）的 `SKILL.md` 与 `output.schema.json` 必须随包发布，这是由 `tool.setuptools.package-data` 强制的打包契约。