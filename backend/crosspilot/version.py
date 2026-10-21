"""CrossPilot 版本号。

与 ``pyproject.toml`` 的 ``version`` 字段保持一致；改动时两处同步。
扁平布局下原 ``crosspilot/__init__.py`` 已移除，版本号迁到这里。
"""

from __future__ import annotations

__version__ = "0.3.0"

__all__ = ["__version__"]
