"""HTTP 层：按业务域拆分的 FastAPI router 集合。

分层约定
========

- ``api/deps.py``     —— 装配好的 ``ApiContext``（唯一共享依赖）
- ``api/helpers.py``  —— 无状态小工具（附件头、校验错误整形）
- ``api/handlers.py`` —— 异步任务的外层保护
- ``api/<domain>.py`` —— 某一业务域的端点，只依赖 ``ApiContext``
- ``api/__init__.py`` —— 汇总 ``ALL_ROUTERS``，由 ``app.create_app()`` 挂载

**依赖方向单向**：``api/*`` → 领域服务（``services/``、``*.py``），反过来不成立。
领域层不知道 HTTP 存在，因此可以脱离 FastAPI 单测。
"""

from __future__ import annotations

from . import (
    accounts,
    agents,
    analyses,
    dashboard,
    imports,
    listings,
    marketplace,
    meta,
    settings,
    skills,
    stores,
    tasks,
)

#: 挂载顺序即 OpenAPI 分组顺序；前缀互不重叠，顺序不影响正确性
ALL_ROUTERS = (
    meta.router,
    accounts.router,
    settings.router,
    analyses.router,
    listings.router,
    imports.router,
    tasks.router,
    dashboard.router,
    agents.router,
    skills.router,
    marketplace.router,
    stores.router,
)

__all__ = ["ALL_ROUTERS"]
