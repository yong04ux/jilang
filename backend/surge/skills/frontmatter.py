"""SKILL.md 头部（frontmatter）解析。

只实现 YAML 的一个受控子集，不引入 PyYAML：

- ``key: value``（字符串 / 布尔 / 数字，可加引号）
- 行内列表 ``[a, b]``
- 块列表::

      requires:
        - llm

出于安全考虑，**不支持嵌套映射**：头部只承载扁平元数据，
复杂结构（输入模型、输出 schema）用引用或独立文件表达。
"""

from __future__ import annotations

from typing import Any

_DELIMITER = "---"


class FrontmatterError(ValueError):
    """头部格式不合法。消息可以直接展示给写技能的人。"""


def split_document(text: str) -> tuple[dict[str, Any], str]:
    """把 ``---`` 包起来的头部与正文分开。"""
    if not isinstance(text, str):
        raise FrontmatterError("技能文件必须是文本")
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    if not lines or lines[0].strip() != _DELIMITER:
        raise FrontmatterError("技能文件必须以第 1 行的 --- 开头")

    end = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == _DELIMITER), None
    )
    if end is None:
        raise FrontmatterError("技能文件缺少结尾的 ---")

    meta = _parse_meta(lines[1:end])
    body = "\n".join(lines[end + 1 :]).strip()
    return meta, body


def _parse_meta(lines: list[str]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        raw = lines[index]
        line = raw.strip()
        index += 1
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            raise FrontmatterError("块列表必须跟在某个键后面")
        key, sep, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not sep or not key:
            raise FrontmatterError(f"无法解析的头部行：{raw.strip()}")
        if key in meta:
            raise FrontmatterError(f"头部字段重复：{key}")

        if value:
            meta[key] = _parse_value(value)
            continue

        items, index = _parse_block_list(lines, index)
        if items is None:
            raise FrontmatterError(f"字段 {key} 没有值")
        meta[key] = items
    return meta


def _parse_block_list(lines: list[str], index: int) -> tuple[list[Any] | None, int]:
    items: list[Any] = []
    while index < len(lines):
        line = lines[index].strip()
        if not line or line.startswith("#"):
            index += 1
            continue
        if not line.startswith("- "):
            break
        items.append(_parse_value(line[2:].strip()))
        index += 1
    return (items if items else None), index


def _parse_value(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_parse_scalar(part) for part in _split_inline(inner)] if inner else []
    return _parse_scalar(value)


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if text.lstrip("-").isdigit():
        return int(text)
    return text


def _split_inline(inner: str) -> list[str]:
    """逗号分隔，尊重引号；不处理转义（元数据里不需要）。"""
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            continue
        if char == ",":
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


__all__ = ["FrontmatterError", "split_document"]
