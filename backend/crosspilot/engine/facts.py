"""事实层：把商品资料抽取成带 ID 的结构化事实，与语言解耦。

核心思想
--------
LLM 生成文案时**只允许引用 fact_id**，不允许自由发挥。这样：
- 语言与事实分离：同一批事实可以生成 en-US / de-DE / ja-JP 多个版本；
- 可审计：每条文案断言都能回溯到具体 fact；
- 可校验：生成后检查是否出现了台账之外的数字/认证/断言。

事实分类
--------
- ``attribute``  规格属性（容量、尺寸、材质……）
- ``feature``    卖点陈述
- ``certification`` 认证（必须带凭证说明）
- ``audience``   目标人群
- ``brand``      品牌信息
- ``logistics``  包装/数量等
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from ..models import OwnProduct

# 单位归一化：用于跨语言与跨度量体系展示
_UNIT_CANON = {
    "ml": "ml", "毫升": "ml",
    "l": "L", "升": "L", "liter": "L", "litre": "L",
    "oz": "oz", "盎司": "oz",
    "g": "g", "克": "g", "gram": "g", "grams": "g",
    "kg": "kg", "千克": "kg", "公斤": "kg",
    "cm": "cm", "厘米": "cm", "公分": "cm",
    "mm": "mm", "毫米": "mm",
    "inch": "in", "in": "in", "英寸": "in",
    "lb": "lb", "lbs": "lb", "磅": "lb",
    "ft": "ft", "feet": "ft", "英尺": "ft",
    "mah": "mAh",
    "w": "W", "瓦": "W",
    "v": "V", "伏": "V",
}

# 这些属性缺了会导致 Listing 无法发布（亚马逊必填项近似集合）
CRITICAL_ATTRIBUTES = {
    "size": ("尺寸", "size", "dimensions", "dimension", "长宽高", "规格"),
    "material": ("材质", "material"),
    "capacity": ("容量", "capacity", "volume", "净含量", "净重含量"),
    "color": ("颜色", "color", "colour"),
    "weight": ("重量", "weight"),
    "quantity": ("数量", "quantity", "件数", "套装", "pack", "pieces"),
}

# 允许出现在文案里的单位（用于校验数字时识别）
UNIT_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(ml|毫升|l|升|oz|盎司|g|克|kg|千克|公斤|cm|厘米|mm|毫米|inch|in|英寸|lb|lbs|磅|ft|mah|w|瓦|v|伏)?",
    re.IGNORECASE,
)


class FactKind(str, Enum):
    ATTRIBUTE = "attribute"
    FEATURE = "feature"
    CERTIFICATION = "certification"
    AUDIENCE = "audience"
    BRAND = "brand"
    LOGISTICS = "logistics"


@dataclass
class Fact:
    """一条可被引用的原子事实。"""

    fact_id: str
    kind: FactKind
    label: str
    value: str
    source: str
    numeric: bool = False
    numbers: tuple[str, ...] = ()
    units: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "kind": self.kind.value,
            "label": self.label,
            "value": self.value,
            "source": self.source,
        }

    def for_prompt(self) -> str:
        return f"[{self.fact_id}] ({self.kind.value}) {self.label}: {self.value}"

    def for_ledger(self) -> dict[str, str]:
        return {"statement": f"{self.label}：{self.value}", "source": self.source, "fact_id": self.fact_id}


@dataclass
class FactSheet:
    """一次生成可用的事实全集 + 缺失项。"""

    facts: list[Fact] = field(default_factory=list)
    missing_critical: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_id(self) -> dict[str, Fact]:
        return {f.fact_id: f for f in self.facts}

    def of_kind(self, kind: FactKind) -> list[Fact]:
        return [f for f in self.facts if f.kind is kind]

    def allowed_numbers(self) -> set[str]:
        numbers: set[str] = set()
        for fact in self.facts:
            numbers.update(fact.numbers)
        return numbers

    def prompt_block(self) -> str:
        """渲染成给模型的紧凑事实清单。"""
        return "\n".join(f.for_prompt() for f in self.facts)

    def ledger(self) -> list[dict[str, str]]:
        return [f.for_ledger() for f in self.facts]

    @property
    def count(self) -> int:
        return len(self.facts)


def _extract_numbers(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    numbers: list[str] = []
    units: list[str] = []
    for match in UNIT_PATTERN.finditer(text):
        value, unit = match.group(1), (match.group(2) or "").strip()
        if value in numbers:
            continue
        numbers.append(value)
        if unit:
            canon = _UNIT_CANON.get(unit.lower(), unit)
            if canon not in units:
                units.append(canon)
    return tuple(numbers), tuple(units)


# 单位换算表：(从单位, 到单位) -> 乘数。只允许"同一物理量的等价换算"，
# 这样模型把 750ml 写成 25.4 oz、把 26cm 写成 10.2 in 属于合规，
# 但把 750ml 改成 1000ml 仍然会被判定为编造。
UNIT_CONVERSIONS: dict[tuple[str, str], float] = {
    ("ml", "oz"): 1 / 29.5735,
    ("oz", "ml"): 29.5735,
    ("l", "oz"): 33.814,
    ("oz", "l"): 1 / 33.814,
    ("ml", "l"): 0.001,
    ("l", "ml"): 1000.0,
    ("g", "oz"): 1 / 28.3495,
    ("oz", "g"): 28.3495,
    ("kg", "lb"): 2.20462,
    ("lb", "kg"): 1 / 2.20462,
    ("g", "lb"): 1 / 453.592,
    ("lb", "g"): 453.592,
    ("cm", "in"): 1 / 2.54,
    ("in", "cm"): 2.54,
    ("mm", "in"): 1 / 25.4,
    ("in", "mm"): 25.4,
    ("cm", "mm"): 10.0,
    ("mm", "cm"): 0.1,
    ("cm", "ft"): 1 / 30.48,
    ("ft", "cm"): 30.48,
}


def convert_value(value: float, from_unit: str, to_unit: str) -> float | None:
    """在允许的换算表内换算；不支持的方向返回 None。"""
    if from_unit == to_unit:
        return value
    factor = UNIT_CONVERSIONS.get((from_unit, to_unit))
    return None if factor is None else value * factor


def allowed_numeric_equivalents(sheet: "FactSheet") -> set[str]:
    """把所有事实数值换算成其它允许单位，得到"合法数字"集合。

    返回字符串集合，调用方用它判断文案里的数字是否来自事实（含换算）。
    换算结果同时保留 1 位与 2 位小数两种写法，避免 25.4 / 25.36 这种差异误报。
    """
    allowed: set[str] = set()
    for fact in sheet.facts:
        for raw in fact.numbers:
            try:
                value = float(raw)
            except ValueError:
                continue
            allowed.add(raw)
            for unit in fact.units:
                for (src, dst), _ in UNIT_CONVERSIONS.items():
                    if src != unit:
                        continue
                    converted = convert_value(value, src, dst)
                    if converted is None:
                        continue
                    allowed.add(f"{converted:.0f}")
                    allowed.add(f"{converted:.1f}")
                    allowed.add(f"{converted:.2f}")
    return allowed


def _normalize_key(key: str) -> str:
    return re.sub(r"\s+", "", key).lower()


class FactSheetBuilder:
    """从 OwnProduct 构建事实清单，保持确定性与可追溯。"""

    def __init__(self, product: OwnProduct):
        self.product = product
        # 每类独立计数，保证 ID 可读且稳定：B01 / S01 / F01 ...
        self._counters: dict[str, int] = {}

    def _next_id(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}{self._counters[prefix]:02d}"

    def _add(
        self,
        sheet: FactSheet,
        *,
        prefix: str,
        kind: FactKind,
        label: str,
        value: str,
        source: str,
    ) -> None:
        value = (value or "").strip()
        if not value:
            return
        numbers, units = _extract_numbers(f"{label} {value}")
        sheet.facts.append(
            Fact(
                fact_id=self._next_id(prefix),
                kind=kind,
                label=label.strip(),
                value=value,
                source=source,
                numeric=bool(numbers),
                numbers=numbers,
                units=units,
            )
        )

    def build(self) -> FactSheet:
        sheet = FactSheet()
        product = self.product

        if product.brand:
            self._add(sheet, prefix="B", kind=FactKind.BRAND, label="品牌", value=product.brand, source="brand")
        if product.category:
            self._add(
                sheet, prefix="C", kind=FactKind.ATTRIBUTE, label="类目", value=product.category, source="category"
            )

        for key, value in product.specifications.items():
            self._add(
                sheet,
                prefix="S",
                kind=FactKind.ATTRIBUTE,
                label=key,
                value=value,
                source=f"specifications.{key}",
            )

        for index, feature in enumerate(product.key_features, start=1):
            self._add(
                sheet,
                prefix="F",
                kind=FactKind.FEATURE,
                label=f"卖点{index}",
                value=feature,
                source=f"key_features[{index - 1}]",
            )

        for index, material in enumerate(product.materials, start=1):
            self._add(
                sheet,
                prefix="M",
                kind=FactKind.ATTRIBUTE,
                label="材质",
                value=material,
                source=f"materials[{index - 1}]",
            )

        for index, cert in enumerate(product.certifications, start=1):
            self._add(
                sheet,
                prefix="T",
                kind=FactKind.CERTIFICATION,
                label="认证",
                value=cert,
                source=f"certifications[{index - 1}]",
            )

        if product.target_audience:
            self._add(
                sheet,
                prefix="A",
                kind=FactKind.AUDIENCE,
                label="目标人群",
                value=product.target_audience,
                source="target_audience",
            )

        # 缺失关键属性 -> 不补全，只记录
        spec_keys = {_normalize_key(k) for k in product.specifications}
        for canonical, aliases in CRITICAL_ATTRIBUTES.items():
            if any(_normalize_key(alias) in spec_keys for alias in aliases):
                continue
            sheet.missing_critical.append(canonical)

        # 认证类的额外提示：出现"食品级/抗菌/无毒"等词但无证书
        risky = [
            f.value
            for f in sheet.of_kind(FactKind.FEATURE) + sheet.of_kind(FactKind.ATTRIBUTE)
            if re.search(r"抗菌|无毒|食品级|FDA|CE|UL|BPA|认证|检测", f.value, re.IGNORECASE)
        ]
        if risky and not product.certifications:
            sheet.warnings.append(
                "输入中出现疑似认证/功效表述（" + "、".join(risky[:3]) + "），但未提供任何证书，"
                "生成时不得使用认证类断言"
            )

        if not sheet.facts:
            sheet.warnings.append("没有任何可用事实，无法生成 Listing")
        return sheet


def build_fact_sheet(product: OwnProduct) -> FactSheet:
    return FactSheetBuilder(product).build()


__all__ = [
    "CRITICAL_ATTRIBUTES",
    "Fact",
    "FactKind",
    "FactSheet",
    "FactSheetBuilder",
    "build_fact_sheet",
]
