"""Surge 版本号唯一真源。

``__version__`` 是 PEP 440 写法（如 ``1.0.0``），供打包元数据、FastAPI
``version`` 与 CLI ``--version`` 等机器面向的场景使用。
``display_version()`` 从它派生对外展示值：去掉末尾的 ``.0``，前面加 ``V``
（例如 ``1.0.0`` → ``V1.0``、``1.2.0`` → ``V1.2``、``1.2.3`` → ``V1.2.3``）。
"""

from __future__ import annotations

__version__ = "1.0.0"


def display_version() -> str:
    """从 ``__version__`` 派生对外展示值（去掉末尾 ``.0``，加 ``V`` 前缀）。"""
    version = __version__
    if version.endswith(".0"):
        version = version[: -len(".0")]
    return f"V{version}"


__all__ = ["__version__", "display_version"]
