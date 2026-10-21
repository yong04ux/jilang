"""评论主题词典（中英双语规则）。

这些规则是 CrossPilot 的**推断依据**，不是事实来源：每条命中都会回到原始
评论样本，报告中以 ``EvidenceRef`` 引用原文。词典可按业务继续扩展，扩展后
无需修改分析器。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ThemeKind = Literal["pain", "need", "concern"]


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    kind: ThemeKind
    patterns: tuple[str, ...]
    description: str


# --- 痛点（负面体验） -------------------------------------------------------
PAIN_THEMES: tuple[Theme, ...] = (
    Theme(
        key="size_fit",
        label="尺寸/容量与预期不符",
        kind="pain",
        patterns=(
            r"\btoo small\b", r"\btoo big\b", r"\bruns small\b", r"\bruns large\b",
            r"\bsmaller than\b", r"\bbigger than\b", r"\bnot true to size\b",
            r"\bsize (?:is )?(?:wrong|off)\b", r"\bdoesn'?t fit\b", r"\bdoes not fit\b",
            r"尺寸(?:偏小|偏大|不符|不对)", r"太小", r"太大", r"装不下", r"容量不足",
        ),
        description="用户反映尺寸、容量或规格与描述不一致。",
    ),
    Theme(
        key="quality",
        label="做工/材质质量",
        kind="pain",
        patterns=(
            r"\bcheap(?:ly)? (?:made|material|plastic)\b", r"\bflimsy\b", r"\bthin\b",
            r"\bflaked?\b", r"\brust(?:ed|y)?\b", r"\bbroke\b", r"\bbroken\b",
            r"\bdefective\b", r"\bpoor quality\b", r"\bbad quality\b",
            r"质量(?:差|不好|一般)", r"做工(?:差|粗糙)", r"廉价", r"生锈", r"断裂", r"破损",
        ),
        description="用户对材质、做工或耐用性给出负面评价。",
    ),
    Theme(
        key="durability",
        label="耐用性不足",
        kind="pain",
        patterns=(
            r"\b(?:stopped|quit) working\b", r"\bbroke after\b", r"\bonly lasted\b",
            r"\bdidn'?t last\b", r"\bwore out\b", r"\bworn out\b", r"\bfell apart\b",
            r"用了(?:几天|一周|一个月)就", r"不耐用", r"容易坏", r"寿命短",
        ),
        description="使用一段时间后失效或损坏。",
    ),
    Theme(
        key="assembly",
        label="安装/组装困难",
        kind="pain",
        patterns=(
            r"\bhard to (?:assemble|install|set ?up)\b", r"\bdifficult to (?:assemble|install|set ?up)\b",
            r"\binstructions?\b.{0,30}\b(?:unclear|confusing|missing|useless|bad)\b",
            r"\bno instructions\b", r"\bconfusing instructions\b",
            r"安装(?:困难|麻烦|复杂)", r"说明书(?:不清|看不懂|缺失)", r"组装(?:难|费劲)",
        ),
        description="安装说明或组装体验存在问题。",
    ),
    Theme(
        key="leak_leakage",
        label="密封/渗漏问题",
        kind="pain",
        patterns=(
            r"\bleak(?:s|ed|ing)?\b", r"\bspill(?:s|ed|ing)?\b", r"\bnot (?:water|air)tight\b",
            r"漏水", r"渗漏", r"密封(?:不好|差)", r"洒出",
        ),
        description="密封性不足导致渗漏。",
    ),
    Theme(
        key="smell",
        label="异味",
        kind="pain",
        patterns=(
            r"\b(?:bad|strong|weird|chemical) smell\b", r"\bsmells?\b", r"\bodor\b", r"\bchemical odor\b",
            r"异味", r"味道(?:大|重|刺鼻)", r"塑料味",
        ),
        description="产品存在明显或持续的异味。",
    ),
    Theme(
        key="noise",
        label="噪音过大",
        kind="pain",
        patterns=(
            r"\b(?:too |very |really )?loud\b", r"\bnoisy\b", r"\bnoise\b", r"\brattl(?:e|es|ing)\b",
            r"噪音(?:大|太响)", r"很吵", r"异响",
        ),
        description="运行噪音影响使用体验。",
    ),
    Theme(
        key="battery",
        label="续航/供电问题",
        kind="pain",
        patterns=(
            r"\bbattery (?:life )?(?:is )?(?:short|poor|bad|dies|drains)\b",
            r"\bdoesn'?t hold (?:a )?charge\b", r"\bwon'?t charge\b", r"\bbattery died\b",
            r"续航(?:差|短)", r"电池(?:不耐用|掉电快)", r"充不进电",
        ),
        description="电池续航或充电表现不达预期。",
    ),
    Theme(
        key="packaging",
        label="包装/运输损坏",
        kind="pain",
        patterns=(
            r"\barrived (?:damaged|broken|cracked|dented)\b", r"\bdamaged in (?:shipping|transit)\b",
            r"\bpackaging\b.{0,40}\b(?:damaged|poor|bad|broken)\b",
            r"包装(?:破损|简陋|不好)", r"到货(?:破损|压坏)", r"运输(?:损坏|磕碰)",
        ),
        description="到货时的包装或商品状态问题。",
    ),
    Theme(
        key="missing_parts",
        label="缺少配件/零件",
        kind="pain",
        patterns=(
            r"\bmissing (?:parts?|pieces?|screws?|accessor(?:y|ies)|pieces)\b",
            r"\bnot included\b", r"\bonly (?:received|came with) (?:one|part)\b",
            r"缺少(?:配件|零件)", r"少发", r"漏发", r"没有附带",
        ),
        description="包裹缺少配件或零件。",
    ),
    Theme(
        key="color_mismatch",
        label="颜色/外观与图片不符",
        kind="pain",
        patterns=(
            r"\b(?:color|colour) (?:is )?(?:different|off|wrong|not)\b",
            r"\blooks different\b", r"\bnot as (?:pictured|shown|described|advertised)\b",
            r"颜色(?:不符|偏差|不一样)", r"和图片(?:不一样|不符)", r"实物与描述不符",
        ),
        description="实物与详情页图片或描述存在差异。",
    ),
    Theme(
        key="usability",
        label="操作不便/设计不合理",
        kind="pain",
        patterns=(
            r"\bhard to (?:use|clean|open|close|carry)\b", r"\bdifficult to (?:use|clean|open|close|carry)\b",
            r"\bawkward\b", r"\bnot user[- ]friendly\b", r"\bclumsy\b",
            r"不好(?:用|清洗|打开)", r"设计不合理", r"操作(?:麻烦|困难)",
        ),
        description="日常使用或清洁维护不便利。",
    ),
    Theme(
        key="description_mismatch",
        label="描述与实物不一致",
        kind="pain",
        patterns=(
            r"\bnot as described\b", r"\bmisleading (?:description|ad)\b", r"\bfalse advertising\b",
            r"\bdidn'?t match the description\b",
            r"描述不符", r"虚假宣传", r"与页面不符",
        ),
        description="详情页描述与实物不一致。",
    ),
)

# --- 需求（用户希望获得什么） ----------------------------------------------
NEED_THEMES: tuple[Theme, ...] = (
    Theme(
        key="easy_clean",
        label="易清洁/可机洗",
        kind="need",
        patterns=(
            r"\beasy to clean\b", r"\bdishwasher safe\b", r"\bmachine washable\b",
            r"\bwipe clean\b", r"好清洗", r"可机洗", r"易清洁",
        ),
        description="用户重视日常清洁与维护成本。",
    ),
    Theme(
        key="space_saving",
        label="节省空间/便携",
        kind="need",
        patterns=(
            r"\bspace[- ]saving\b", r"\bcompact\b", r"\bportable\b", r"\bfoldable\b",
            r"\bfits in (?:a )?(?:drawer|bag|cabinet)\b", r"节省空间", r"便携", r"可折叠",
        ),
        description="用户关注收纳体积与携带便利性。",
    ),
    Theme(
        key="gift",
        label="送礼场景",
        kind="need",
        patterns=(
            r"\bgift\b", r"\bpresent for\b", r"\bbought (?:it )?as a gift\b", r"送人", r"礼物", r"伴手礼",
        ),
        description="送礼是常见购买场景，包装与外观会影响决策。",
    ),
    Theme(
        key="value",
        label="性价比",
        kind="need",
        patterns=(
            r"\bgood value\b", r"\bworth (?:the|it)\b", r"\bfor the price\b", r"\bbudget\b",
            r"性价比", r"划算", r"价格实惠",
        ),
        description="价格与品质的匹配度是核心决策因素。",
    ),
    Theme(
        key="multi_use",
        label="多场景适用",
        kind="need",
        patterns=(
            r"\bversatile\b", r"\bmulti[- ]?(?:purpose|use)\b", r"\bworks for\b.{0,30}\band\b",
            r"多用途", r"多种场景", r"适用(?:于|多个)",
        ),
        description="用户希望一件产品覆盖多个使用场景。",
    ),
    Theme(
        key="kids_pets",
        label="儿童/宠物家庭场景",
        kind="need",
        patterns=(
            r"\bkids?\b", r"\btoddler\b", r"\bbaby\b", r"\bpets?\b", r"\bdog\b", r"\bcat\b",
            r"儿童", r"宝宝", r"宠物", r"猫", r"狗",
        ),
        description="有孩/宠家庭对安全与耐用有额外要求。",
    ),
    Theme(
        key="fast_setup",
        label="开箱即用",
        kind="need",
        patterns=(
            r"\beasy to (?:assemble|install|set ?up)\b", r"\bno assembly\b", r"\bready to use\b",
            r"免安装", r"开箱即用", r"快速上手",
        ),
        description="用户希望减少安装与学习成本。",
    ),
)

# --- 购买顾虑 ---------------------------------------------------------------
CONCERN_THEMES: tuple[Theme, ...] = (
    Theme(
        key="quality_doubt",
        label="对质量的疑虑",
        kind="concern",
        patterns=(
            r"\bis it (?:durable|sturdy|worth)\b", r"\bhow long (?:does|will) it last\b",
            r"\bworried about\b", r"\bcheap looking\b",
            r"会不会(?:坏|不耐用)", r"质量(?:如何|怎么样)", r"担心质量",
        ),
        description="购买前对材质与耐用性存在疑虑。",
    ),
    Theme(
        key="fit_doubt",
        label="对尺寸是否合适的疑虑",
        kind="concern",
        patterns=(
            r"\bwill it fit\b", r"\bnot sure (?:about|if)\b.{0,20}\bsize\b",
            r"\bwhat size\b", r"\bmeasurements?\b",
            r"尺寸(?:会不会|是否)", r"能不能装下",
        ),
        description="购买前需要明确尺寸与适配范围。",
    ),
    Theme(
        key="compatibility",
        label="兼容性顾虑",
        kind="concern",
        patterns=(
            r"\bcompatible with\b", r"\bwork(?:s)? with\b", r"\bwill it work\b",
            r"\bfits my\b", r"兼容", r"适配", r"能不能用在",
        ),
        description="用户需要确认与自己设备的兼容性。",
    ),
    Theme(
        key="safety_doubt",
        label="安全/材质顾虑",
        kind="concern",
        patterns=(
            r"\bsafe for\b", r"\bnon[- ]?toxic\b", r"\bbpa\b", r"\bfood safe\b",
            r"安全吗", r"有毒吗", r"材质安全",
        ),
        description="用户关注材料安全与认证。",
    ),
    Theme(
        key="returns",
        label="退换货顾虑",
        kind="concern",
        patterns=(
            r"\breturn(?:s|ed|ing)?\b", r"\brefund\b", r"\bwarranty\b",
            r"退货", r"退款", r"保修",
        ),
        description="退换货与售后政策影响购买决策。",
    ),
    Theme(
        key="shipping",
        label="物流时效顾虑",
        kind="concern",
        patterns=(
            r"\bshipping\b", r"\bdelivery\b", r"\barrived late\b", r"\btook .{0,10}(?:days|weeks)\b",
            r"物流", r"发货", r"到货(?:慢|快)",
        ),
        description="配送时效与包装完整性被频繁提及。",
    ),
)

ALL_THEMES: tuple[Theme, ...] = PAIN_THEMES + NEED_THEMES + CONCERN_THEMES
THEMES_BY_KEY = {theme.key: theme for theme in ALL_THEMES}


def themes_of(kind: ThemeKind) -> tuple[Theme, ...]:
    if kind == "pain":
        return PAIN_THEMES
    if kind == "need":
        return NEED_THEMES
    return CONCERN_THEMES


__all__ = [
    "ALL_THEMES",
    "CONCERN_THEMES",
    "NEED_THEMES",
    "PAIN_THEMES",
    "THEMES_BY_KEY",
    "Theme",
    "ThemeKind",
    "themes_of",
]
