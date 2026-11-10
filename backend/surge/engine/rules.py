"""平台规则与禁用词规则的可配置加载层。

规则来源：``config/platform_rules.json`` 与 ``config/banned_terms.json``。
任何"平台字符限制 / 禁用词 / 合规要求"都从这里读取，业务代码中不硬编码，
以便未来替换为真实平台政策或按类目覆盖。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import get_settings, load_json_config
from ..models import Platform, Severity

# 平台枚举值 -> 规则文件键名（覆盖命名差异）
_PLATFORM_ALIASES = {
    "mercadolibre": "mercadolibre",
    "mercadolibre_ml": "mercadolibre",
}


def _platform_key(platform: Platform | str) -> str:
    value = platform.value if isinstance(platform, Platform) else str(platform)
    return _PLATFORM_ALIASES.get(value, value)


@dataclass(frozen=True)
class PlatformRules:
    """单个平台/站点生效的规则集合。"""

    platform: str
    marketplace: str
    title_max_chars: int
    bullet_max_chars: int
    description_max_chars: int
    search_terms_max_bytes: int
    bullet_count: int
    allow_all_caps: bool
    allow_emoji: bool
    allow_price_in_title: bool
    allow_promotional_terms: bool
    prohibited_characters: tuple[str, ...]
    max_keyword_repeat_per_100_words: int
    notes: tuple[str, ...]
    verified: bool
    disclaimer: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "marketplace": self.marketplace,
            "title_max_chars": self.title_max_chars,
            "bullet_max_chars": self.bullet_max_chars,
            "description_max_chars": self.description_max_chars,
            "search_terms_max_bytes": self.search_terms_max_bytes,
            "bullet_count": self.bullet_count,
            "allow_all_caps": self.allow_all_caps,
            "allow_emoji": self.allow_emoji,
            "allow_price_in_title": self.allow_price_in_title,
            "allow_promotional_terms": self.allow_promotional_terms,
            "prohibited_characters": list(self.prohibited_characters),
            "max_keyword_repeat_per_100_words": self.max_keyword_repeat_per_100_words,
            "verified": self.verified,
            "disclaimer": self.disclaimer,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class BannedTerm:
    term: str
    category: str
    category_label: str
    severity: Severity
    case_sensitive: bool = False


@dataclass(frozen=True)
class BannedTermRules:
    terms: tuple[BannedTerm, ...] = field(default_factory=tuple)
    universal_superlatives: tuple[str, ...] = ()
    disclaimer: str = ""

    def matches(self, text: str) -> list[BannedTerm]:
        """返回在该文本中命中的禁用词（去重、保持顺序）。"""
        hits: list[BannedTerm] = []
        seen: set[str] = set()
        lowered = text.lower()
        for term in self.terms:
            haystack = text if term.case_sensitive else lowered
            needle = term.term if term.case_sensitive else term.term.lower()
            if needle in seen:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack):
                hits.append(term)
                seen.add(needle)
        return hits


class RuleSet:
    """已加载的全部规则，供分析/生成/质检共享。"""

    def __init__(self, platform_rules: dict[str, Any], banned: dict[str, Any]):
        self._raw = platform_rules
        self._banned_raw = banned

    # -- 平台规则 ---------------------------------------------------------
    def platform_rules(self, platform: Platform | str, marketplace: str) -> PlatformRules:
        key = _platform_key(platform)
        defaults = dict(self._raw.get("defaults", {}))
        platforms = self._raw.get("platforms", {})
        site_map = platforms.get(key, {})
        site = site_map.get(marketplace.upper()) or site_map.get("US") or {}
        merged = {**defaults, **{k: v for k, v in site.items() if k != "notes"}}
        meta = self._raw.get("_meta", {})
        return PlatformRules(
            platform=key,
            marketplace=marketplace.upper(),
            title_max_chars=int(merged.get("title_max_chars", 200)),
            bullet_max_chars=int(merged.get("bullet_max_chars", 500)),
            description_max_chars=int(merged.get("description_max_chars", 2000)),
            search_terms_max_bytes=int(merged.get("search_terms_max_bytes", 250)),
            bullet_count=int(merged.get("bullet_count", 5)),
            allow_all_caps=bool(merged.get("allow_all_caps", False)),
            allow_emoji=bool(merged.get("allow_emoji", False)),
            allow_price_in_title=bool(merged.get("allow_price_in_title", False)),
            allow_promotional_terms=bool(merged.get("allow_promotional_terms", False)),
            prohibited_characters=tuple(merged.get("prohibited_characters", [])),
            max_keyword_repeat_per_100_words=int(
                merged.get("max_keyword_repeat_per_100_words", 4)
            ),
            notes=tuple(site.get("notes", [])),
            verified=bool(meta.get("verified", False)),
            disclaimer=str(meta.get("disclaimer", "")),
        )

    # -- 禁用词 -----------------------------------------------------------
    def banned_terms(self, extra_terms: list[str] | None = None) -> BannedTermRules:
        collected: list[BannedTerm] = []
        for category, payload in self._banned_raw.get("categories", {}).items():
            severity = Severity(payload.get("severity", "warning"))
            label = payload.get("label", category)
            for term in payload.get("terms", []):
                collected.append(
                    BannedTerm(
                        term=term,
                        category=category,
                        category_label=label,
                        severity=severity,
                        case_sensitive=bool(payload.get("case_sensitive", False)),
                    )
                )
        for term in extra_terms or []:
            cleaned = term.strip()
            if cleaned:
                collected.append(
                    BannedTerm(
                        term=cleaned,
                        category="custom",
                        category_label="品牌自定义禁用词",
                        severity=Severity.ERROR,
                    )
                )
        return BannedTermRules(
            terms=tuple(collected),
            universal_superlatives=tuple(self._banned_raw.get("universal_superlatives", [])),
            disclaimer=str(self._banned_raw.get("_meta", {}).get("disclaimer", "")),
        )

    def supported_platforms(self) -> dict[str, list[str]]:
        return {
            name: sorted(sites.keys())
            for name, sites in self._raw.get("platforms", {}).items()
        }


@lru_cache(maxsize=4)
def _load_rules(platform_path: str, banned_path: str, mtime: float, banned_mtime: float) -> RuleSet:
    return RuleSet(load_json_config(Path(platform_path)), load_json_config(Path(banned_path)))


def get_rules(platform_path: Path | None = None, banned_path: Path | None = None) -> RuleSet:
    """加载规则；文件修改后自动重新加载（以 mtime 作为缓存键）。"""
    settings = get_settings()
    p_path = (platform_path or settings.platform_rules_path).resolve()
    b_path = (banned_path or settings.banned_terms_path).resolve()
    return _load_rules(
        str(p_path),
        str(b_path),
        p_path.stat().st_mtime,
        b_path.stat().st_mtime,
    )


__all__ = [
    "BannedTerm",
    "BannedTermRules",
    "PlatformRules",
    "RuleSet",
    "get_rules",
]
