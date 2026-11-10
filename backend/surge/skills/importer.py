"""租户导入 SKILL.md 的解析与校验。

安全边界
========

导入内容来自用户，**绝不**参与 Python 导入：

- 头部出现 ``executor`` / ``input_model`` / ``output_schema`` 一律拒绝；
- 导入技能是「说明型能力」：可被列出、可被 Agent 按需加载正文，
  但不能通过 ``POST /api/skills/{key}/run`` 直接执行。

删除复用已有的软删接口（``DELETE /api/skills/{key}``），不另开一套。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .frontmatter import FrontmatterError, split_document

MAX_BYTES = 64 * 1024
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
RESERVED_FIELDS = ("executor", "input_model", "output_schema", "executor_type")


class SkillImportError(ValueError):
    """导入内容不合法。消息直接展示给上传者。"""


@dataclass(frozen=True)
class ImportedSkill:
    key: str
    name: str
    summary: str
    category: str
    version: str
    content: str
    instructions: str
    description: str = ""
    keywords: tuple[str, ...] = ()


def read_content(content: str) -> ImportedSkill | None:
    """宽松读取库里的原始 SKILL.md（不抛错，供列表/发现使用）。

    与 ``parse_skill_md`` 的区别：后者是**导入边界**，必须严格校验；
    这里只服务于读视图，坏数据返回 ``None``，不让整页崩。
    """
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        meta, body = split_document(content)
    except FrontmatterError:
        return None
    keywords = meta.get("keywords")
    return ImportedSkill(
        key=str(meta.get("name") or "").strip(),
        name=str(meta.get("title") or meta.get("name") or "").strip(),
        summary=str(meta.get("summary") or meta.get("description") or "").strip(),
        category=str(meta.get("category") or "").strip(),
        version=str(meta.get("version") or "").strip(),
        content=content,
        instructions=body,
        description=str(meta.get("description") or "").strip(),
        keywords=tuple(str(item) for item in keywords) if isinstance(keywords, list) else (),
    )


def parse_skill_md(content: str) -> ImportedSkill:
    if not isinstance(content, str) or not content.strip():
        raise SkillImportError("请选择一份 SKILL.md 文件")
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise SkillImportError(f"技能文件超过 {MAX_BYTES // 1024} KB，请精简后再导入")

    try:
        meta, body = split_document(content)
    except FrontmatterError as exc:
        raise SkillImportError(str(exc)) from exc

    reserved = [field for field in RESERVED_FIELDS if field in meta]
    if reserved:
        raise SkillImportError(
            "导入的技能只能包含说明，不能绑定执行器（"
            + "、".join(reserved)
            + "）"
        )

    key = str(meta.get("name") or "").strip()
    if not KEY_RE.match(key):
        raise SkillImportError("name 必须以小写字母开头，只含小写字母/数字/下划线（2–64 位）")

    description = str(meta.get("description") or "").strip()
    if not description:
        raise SkillImportError("description 不能为空：它决定 Agent 什么时候加载这个技能")
    if not body:
        raise SkillImportError("SKILL.md 正文不能为空：至少写清楚何时使用与执行边界")

    return ImportedSkill(
        key=key,
        name=str(meta.get("title") or key).strip(),
        summary=str(meta.get("summary") or description).strip(),
        category=str(meta.get("category") or "自定义").strip(),
        version=str(meta.get("version") or "1.0.0").strip(),
        content=content,
        instructions=body,
    )


__all__ = [
    "MAX_BYTES",
    "ImportedSkill",
    "SkillImportError",
    "parse_skill_md",
    "read_content",
]
