# CrossPilot 后端（backend/）

本目录是 CrossPilot 的 **Python 工程根**：FastAPI 应用、领域包、测试、部署配置都在这里。

- 包结构、子包职责 → `crosspilot/__init__.py` 的目录说明
- 开发/部署命令、整体仓库结构 → 回到仓库根 [`../README.md`](../README.md)
- 本地跑起来：

  ```bash
  # 在 backend/ 下
  pip install -r requirements.txt
  python -m crosspilot check     # 环境自检
  python -m crosspilot serve     # 启动（默认 127.0.0.1:8000）
  ```

- 数据库：仓库根 `docker-compose.yml` 提供本地 PostgreSQL（`postgresql://postgres:postgres@127.0.0.1:5432/crosspilot`）。
- 前端在仓库根的 `frontend/`（无构建静态站），由本服务的 `settings.web_dir` 指向并挂载。
