"""CrossPilot —— 跨境电商 AI 内容工作台（竞品分析 + Listing 生成）。

本包只承载业务逻辑，通过 HTTP 接口对外提供能力，不依赖任何特定宿主运行时。

目录职责（扁平工程根为 ``backend/``，前端在仓库根 ``frontend/``）：

- ``api/``          HTTP 层：按业务域拆分的 FastAPI router 集合
- ``services/``     业务服务层：跨入口复用的编排逻辑
- ``agent/``        Agent Runtime（LangGraph）与 Registry
- ``engine/``       内容引擎：竞品分析、Listing 生成、质检、规则与词典
- ``llm/``          模型接入：OpenAI 兼容客户端、Provider、多厂商配置
- ``market/``       平台规格与市场数据 Provider（Mock / Live）
- ``persistence/``  持久化：PostgreSQL、迁移、文件存储、凭据加密
- ``ingest/``       数据导入：CSV / JSON / Excel 解析与逐行校验
- ``demo/``         演示与种子数据
- 包根模块          入口（``app`` / ``cli`` / ``worker*``）、配置、领域模型、
                    租户与认证等横切关注点
"""

from __future__ import annotations

from .config import Settings, get_settings
from .version import __version__

__all__ = ["Settings", "get_settings", "__version__"]
