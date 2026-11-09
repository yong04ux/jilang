"""技能发现：先把「有哪些能力」给 Agent，命中后才加载正文。

渐进披露三层
============

1. **目录**（``catalog``）：只给 ``key + name + description``，不读正文；
2. **正文**（``load_instructions``）：选中某个技能后才读它的 SKILL.md；
3. **执行**（``POST /api/skills/{key}/run``）：真正跑，和本模块无关。

为什么选择要交给模型
====================

技能越来越多时，关键词表永远补不全（「帮我写个能过审的标题」不会出现
「Listing」四个字）。所以主路径是让模型从目录里挑；模型不可用或返回不合规时
才退回确定性匹配，并且 ``degraded=True`` + 一句人话说明——**不静默降级**。

本模块只读：不写库、不动执行图、不影响 ``/api/agent/runs`` 的计划。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .importer import read_content
from .registry import SKILL_REGISTRY

#: 一次最多返回几个技能。选太多等于没选。
DEFAULT_LIMIT = 5

#: 确定性兜底：命中召回词才入选；没有召回词时，描述重叠至少 4 个二元组。
#: 阈值不能低：「分析」「定位」这类通用词会让所有技能都像命中。
_MIN_OVERLAP = 4

_CATALOG_SCHEMA = '{"skill_keys": ["从目录中选择的技能 key，按需要程度排序"]}'

_SELECT_SYSTEM = (
    "你是电商运营助手的技能路由器。只从下面给出的技能目录里选择"
    "「完成这次目标真正需要」的技能；没有合适的就返回空数组。"
    "不要编造目录里没有的 key，不要因为名字相近就选。"
)


@dataclass(frozen=True)
class CatalogEntry:
    key: str
    name: str
    description: str
    category: str
    source: str
    runnable: bool
    keywords: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill_key": self.key,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "source": self.source,
            "runnable": self.runnable,
        }


@dataclass(frozen=True)
class DiscoveredSkill:
    entry: CatalogEntry
    instructions: str = ""
    matched: tuple[str, ...] = ()

    def as_dict(self, *, with_body: bool) -> dict[str, Any]:
        data = self.entry.as_dict()
        data["matched"] = list(self.matched)
        if with_body:
            data["instructions"] = self.instructions
        return data


@dataclass(frozen=True)
class DiscoveryResult:
    goal: str
    items: tuple[DiscoveredSkill, ...]
    degraded: bool = False
    reason: str = ""

    def as_dict(self, *, with_body: bool) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "degraded": self.degraded,
            "reason": self.reason,
            "items": [item.as_dict(with_body=with_body) for item in self.items],
        }


# ---------------------------------------------------------------------------
# 目录（第一层）
# ---------------------------------------------------------------------------


def catalog(db: Any, tenant_id: str) -> list[CatalogEntry]:
    """内置 + 租户导入，全部只带轻量描述。已删除的不出现。"""
    entries: list[CatalogEntry] = [
        CatalogEntry(
            key=spec.key,
            name=spec.name,
            description=spec.description or spec.summary,
            category=spec.category,
            source="builtin",
            runnable=spec.executable,
            keywords=spec.keywords,
        )
        for spec in SKILL_REGISTRY.values()
    ]
    if db is not None:
        for row in db.list_skill_definitions(tenant_id):
            if row.get("tenant_id") == "" or row.get("status") == "disabled":
                continue
            parsed = read_content(row.get("content") or "")
            entries.append(
                CatalogEntry(
                    key=str(row.get("skill_key") or ""),
                    name=str(row.get("name") or row.get("skill_key") or ""),
                    description=(
                        (parsed.description if parsed else "")
                        or str(row.get("summary") or "")
                    ),
                    category=(parsed.category if parsed else "") or "自定义",
                    source="imported",
                    runnable=False,
                    keywords=parsed.keywords if parsed else (),
                )
            )
    return [entry for entry in entries if entry.key]


# ---------------------------------------------------------------------------
# 正文（第二层）
# ---------------------------------------------------------------------------


def load_instructions(db: Any, tenant_id: str, key: str) -> str | None:
    """按 key 懒加载 SKILL.md 正文。找不到返回 ``None``，不构造空壳。"""
    spec = SKILL_REGISTRY.get(key)
    if spec is not None:
        return spec.instructions
    if db is None:
        return None
    row = db.get_skill_definition(key, tenant_id)
    if row is None and tenant_id:
        row = db.get_skill_definition(key, "")
    if row is None or row.get("tenant_id") == "":
        return None
    parsed = read_content(row.get("content") or "")
    return parsed.instructions if parsed else None


# ---------------------------------------------------------------------------
# 选择（模型优先，确定性兜底）
# ---------------------------------------------------------------------------


def _catalog_text(entries: list[CatalogEntry]) -> str:
    return "\n".join(
        f"- {entry.key}｜{entry.name}：{entry.description}" for entry in entries
    )


def _clean(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", (text or "").lower())


def _bigrams(text: str) -> set[str]:
    cleaned = _clean(text)
    return {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}


def _match(goal: str, entries: list[CatalogEntry], limit: int) -> list[DiscoveredSkill]:
    """确定性匹配：召回词是硬条件，描述重叠只用来排序与兜底。

    早期版本把「描述里重合几个二元组」也当成入选条件，结果一句
    「分析这批竞品的价格定位」能同时选中数据校验、市场总结、评论挖掘——
    它们只是共享了「分析」「定位」这种通用词。命中召回词才算数。
    """
    text = (goal or "").lower()
    goal_grams = _bigrams(goal)
    by_hits: list[tuple[float, DiscoveredSkill]] = []
    by_overlap: list[tuple[float, DiscoveredSkill]] = []
    for entry in entries:
        hits = [word for word in entry.keywords if word.lower() in text]
        if entry.name and entry.name.lower() in text and entry.name not in hits:
            hits.append(entry.name)
        overlap = goal_grams & _bigrams(f"{entry.name}{entry.description}")
        if hits:
            # 命中词数量为主，重叠只做同分排序
            by_hits.append(
                (
                    2.0 * len(hits) + 0.1 * len(overlap),
                    DiscoveredSkill(entry=entry, matched=tuple(dict.fromkeys(hits))),
                )
            )
        elif len(overlap) >= _MIN_OVERLAP:
            # 没有召回词的技能（例如用户导入、没写 keywords）才看描述重叠
            by_overlap.append(
                (0.5 * len(overlap), DiscoveredSkill(entry=entry, matched=()))
            )

    # 有召回词命中时不再看描述重叠：否则「导入的数据」这种公共短语会把
    # 竞品分析也拉进来，和目标真正需要的技能并列。
    scored = by_hits or by_overlap
    scored.sort(key=lambda pair: (-pair[0], pair[1].entry.key))
    return [item for _, item in scored[:limit]]


def _llm_select(
    goal: str,
    entries: list[CatalogEntry],
    client: Any,
    limit: int,
) -> list[str]:
    messages = [
        {"role": "system", "content": _SELECT_SYSTEM},
        {
            "role": "user",
            "content": f"技能目录：\n{_catalog_text(entries)}\n\n本次目标：{goal}",
        },
    ]
    data, _result = client.chat_json(
        messages, schema_hint=_CATALOG_SCHEMA, temperature=0.0
    )
    keys = data.get("skill_keys") if isinstance(data, dict) else None
    if not isinstance(keys, list):
        raise TypeError("模型没有返回 skill_keys 数组")
    known = {entry.key for entry in entries}
    picked: list[str] = []
    for key in keys:
        text = str(key).strip()
        if text in known and text not in picked:
            picked.append(text)
    return picked[:limit]


def discover(
    goal: str,
    *,
    entries: list[CatalogEntry],
    client: Any = None,
    db: Any = None,
    tenant_id: str = "",
    load_body: bool = True,
    limit: int = DEFAULT_LIMIT,
) -> DiscoveryResult:
    """按目标选择技能；``load_body`` 为真时只加载选中技能的正文。"""
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("goal 不能为空")
    limited = max(1, min(int(limit or DEFAULT_LIMIT), 10))

    degraded = False
    reason = ""
    picked: list[DiscoveredSkill] = []

    if client is not None:
        try:
            keys = _llm_select(goal, entries, client, limited)
            by_key = {entry.key: entry for entry in entries}
            picked = [DiscoveredSkill(entry=by_key[key]) for key in keys]
        except Exception:  # noqa: BLE001 - 发现失败不能反过来让请求失败
            degraded = True
            reason = "没读懂这次目标要哪些能力，先按关键词匹配，结果请核对。"
    else:
        degraded = True
        reason = "当前没有可用的模型，先按关键词匹配能力，结果请核对。"

    if not picked and (client is None or degraded):
        # 模型可用且明确返回空数组时尊重模型；只有模型缺失/失败才关键词兜底
        picked = _match(goal, entries, limited)

    items = tuple(
        DiscoveredSkill(
            entry=item.entry,
            matched=item.matched,
            instructions=(
                (load_instructions(db, tenant_id, item.entry.key) or "")
                if load_body
                else ""
            ),
        )
        for item in picked
    )
    return DiscoveryResult(
        goal=goal, items=items, degraded=degraded, reason=reason
    )


__all__ = [
    "DEFAULT_LIMIT",
    "CatalogEntry",
    "DiscoveredSkill",
    "DiscoveryResult",
    "catalog",
    "discover",
    "load_instructions",
]
