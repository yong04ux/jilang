"""目录式技能加载器。

约定：一个技能 = 一个目录，目录里至少有一份 ``SKILL.md``::

    catalog/competitor_analysis/
      SKILL.md              # frontmatter 描述 + 正文使用说明
      output.schema.json    # 可选：产出结构

``SKILL.md`` 的头部承载「有哪些技能、各自要什么参数、由谁执行」，
正文承载「什么时候用、怎么用」。新增内置技能只需新增一个目录，
不再改 ``registry.py``。

引用写法
========

头部用 ``模块:属性`` 指向 Python：

- ``input_model: crosspilot.skills.inputs:CompetitorAnalysisInput``
- ``executor: crosspilot.skills.executors:competitor_analysis``

这是**内置目录专用**。租户导入的 SKILL.md 由 ``importer`` 解析，
不会走这里的 import 逻辑，避免用户输入变成任意代码执行。
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .base import RENDERERS, SkillSpec
from .frontmatter import FrontmatterError, split_document

BUILTIN_CATALOG = Path(__file__).with_name("catalog")
REQUIRED_FIELDS = ("name", "title", "description", "input_model", "executor")


class CatalogError(RuntimeError):
    """内置技能目录不合法。启动即失败，不允许静默丢技能。"""


def _import_ref(ref: Any, *, field: str, where: Path) -> Any:
    text = str(ref or "").strip()
    module_name, sep, attr = text.partition(":")
    if not sep or not module_name or not attr:
        raise CatalogError(f"{where}: {field} 必须写成 模块:属性，收到 {text!r}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise CatalogError(f"{where}: 无法导入 {module_name}") from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise CatalogError(f"{where}: {module_name} 没有 {attr}") from exc


def _load_output_schema(value: Any, where: Path) -> dict[str, Any]:
    if not value:
        return {}
    path = where / str(value)
    if not path.is_file():
        raise CatalogError(f"{where}: 找不到产出结构文件 {value}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise CatalogError(f"{path}: 不是合法的 JSON") from exc
    if not isinstance(data, dict):
        raise CatalogError(f"{path}: 产出结构必须是 JSON 对象")
    return data


def load_skill_dir(path: Path) -> SkillSpec:
    """加载单个目录。任何一处不合法都抛 ``CatalogError``，不降级。"""
    skill_md = path / "SKILL.md"
    try:
        meta, body = split_document(skill_md.read_text(encoding="utf-8"))
    except FrontmatterError as exc:
        raise CatalogError(f"{skill_md}: {exc}") from exc
    except OSError as exc:
        raise CatalogError(f"{skill_md}: 读不出来") from exc

    missing = [field for field in REQUIRED_FIELDS if not str(meta.get(field) or "").strip()]
    if missing:
        raise CatalogError(f"{skill_md}: 缺少头部字段 {', '.join(missing)}")

    key = str(meta["name"]).strip()
    if key != path.name:
        raise CatalogError(
            f"{skill_md}: name={key!r} 必须与目录名 {path.name!r} 一致"
        )

    inputs = _import_ref(meta["input_model"], field="input_model", where=skill_md)
    if not (isinstance(inputs, type) and issubclass(inputs, BaseModel)):
        raise CatalogError(f"{skill_md}: input_model 必须是 Pydantic 模型")

    executor = _import_ref(meta["executor"], field="executor", where=skill_md)
    if not callable(executor):
        raise CatalogError(f"{skill_md}: executor 必须可调用")

    renderer = str(meta.get("renderer") or "report").strip()
    if renderer not in RENDERERS:
        raise CatalogError(f"{skill_md}: 未知的 renderer {renderer!r}")

    requires = meta.get("requires") or []
    if not isinstance(requires, list):
        raise CatalogError(f"{skill_md}: requires 必须是列表")

    keywords = meta.get("keywords") or []
    if not isinstance(keywords, list):
        raise CatalogError(f"{skill_md}: keywords 必须是列表")

    try:
        credits = int(meta.get("credits") or 1)
    except (TypeError, ValueError) as exc:
        raise CatalogError(f"{skill_md}: credits 必须是整数") from exc

    return SkillSpec(
        key=key,
        name=str(meta["title"]).strip(),
        category=str(meta.get("category") or "未分类").strip(),
        summary=str(meta.get("summary") or meta["description"]).strip(),
        inputs=inputs,
        output_schema=_load_output_schema(meta.get("output_schema"), path),
        executor=executor,
        renderer=renderer,
        requires=tuple(str(item) for item in requires),
        credits=credits,
        status=str(meta.get("status") or "available").strip(),
        source="builtin",
        description=str(meta["description"]).strip(),
        keywords=tuple(str(item) for item in keywords),
        instructions=body,
        directory=str(path),
        executor_type=str(meta.get("executor_type") or "function").strip(),
    )


def load_builtin_catalog(root: Path | None = None) -> dict[str, SkillSpec]:
    """扫描目录，按目录名排序返回。找不到任何技能视为部署错误。"""
    base = root or BUILTIN_CATALOG
    if not base.is_dir():
        raise CatalogError(f"技能目录不存在：{base}")

    specs: dict[str, SkillSpec] = {}
    for path in sorted(base.iterdir()):
        if not path.is_dir() or not (path / "SKILL.md").is_file():
            continue
        spec = load_skill_dir(path)
        if spec.key in specs:
            raise CatalogError(f"技能 key 重复：{spec.key}")
        specs[spec.key] = spec
    if not specs:
        raise CatalogError(f"{base} 下没有任何 SKILL.md")
    return specs


__all__ = ["BUILTIN_CATALOG", "CatalogError", "load_builtin_catalog", "load_skill_dir"]
