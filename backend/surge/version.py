"""Surge 版本号。

对外显示用 ``V1.0``；打包版本见 ``pyproject.toml`` 的 ``version``（PEP 440 写法）。
扁平布局下原 ``surge/__init__.py`` 已移除，版本号迁到这里。
"""

from __future__ import annotations

__version__ = "V1.0"

__all__ = ["__version__"]
