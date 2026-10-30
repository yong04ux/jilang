"""竞品数据 Provider：把「竞品从哪来」从图节点里隔出来。

现状与决定
==========

竞品数据只有两条来源：调用方显式传入的行，或导入批次。它们目前散在
``agent/tools.read_data_asset`` 与 ``api/agents.py`` 里，再加一条来源
（真实平台接口）就得改工作流，所以统一收在这里：

1. **先支持用户导入数据**——``ImportedCompetitorProvider`` 是唯一可用的实现；
2. **真实数据源通过接口预留，不虚构已接入的能力**——``LiveCompetitorProvider``
   存在，但只会抛 ``ProviderNotConfigured``，**绝不返回导入数据冒充真实数据**。

与 ``marketplace_provider.py`` 的关系
====================================

那个模块管的是**店铺经营数据**（stores / products / orders / ads / metrics），
和「竞品分析用的竞品列表」不是一回事。两者都是 Provider，但数据域不同，
刻意分开，避免一个类既管订单又管竞品。

纪律
====

- 每条结果都带 ``source`` 与 ``is_demo``，来源不会在路上丢失；
- 拿不到数据就返回空 + 说明，**不编造竞品**；
- Live 未配置 → 抛异常。-8：禁止静默回退。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

MODE_IMPORTED = "imported"
MODE_LIVE = "live"

#: 来源标签（进报告 provenance 与前端徽章）
SOURCE_MANUAL = "manual"
SOURCE_IMPORT = "import"
SOURCE_LIVE = "live"


class CompetitorProviderError(RuntimeError):
    """竞品数据 Provider 的失败。"""


class ProviderNotConfigured(CompetitorProviderError):
    """真实数据源未配置 / 未接入。**不是**可以回退到导入数据的信号。"""


@dataclass
class CompetitorQuery:
    """一次竞品数据请求。字段刻意与 ``CompetitorAnalysisRequest`` 对齐。"""

    product_name: str
    platform: str = "amazon"
    marketplace: str = "US"
    category: str | None = None
    limit: int = 50
    #: 导入批次 id（用户导入的数据）
    batch_id: str | None = None
    #: 调用方直接给的行（表单 / 工作台参数确认）
    rows: list[dict[str, Any]] | None = None


@dataclass
class CompetitorData:
    """竞品数据 + 来源元信息。"""

    rows: list[dict[str, Any]] = field(default_factory=list)
    source: str = SOURCE_MANUAL
    is_demo: bool = False
    fetched_at: str = ""
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).isoformat()

    @property
    def empty(self) -> bool:
        return not self.rows

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "count": len(self.rows),
            "source": self.source,
            "is_demo": self.is_demo,
            "fetched_at": self.fetched_at,
            "notes": self.notes,
        }


@runtime_checkable
class CompetitorProvider(Protocol):
    name: str
    mode: str

    def fetch(self, query: CompetitorQuery) -> CompetitorData: ...


# ---------------------------------------------------------------------------
# 唯一可用实现：用户导入的数据
# ---------------------------------------------------------------------------


class ImportedCompetitorProvider:
    """从「显式传入的行」或「本租户的导入批次」读竞品。

    优先级：显式行 > 导入批次。批次必须属于当前租户，否则当作不存在——
    这层校验放在 Provider 里，调用方就不会因为忘记带 tenant_id 而串数据。
    """

    name = "imported"
    mode = MODE_IMPORTED

    def __init__(self, db: Any = None, tenant_id: str = "") -> None:
        self.db = db
        self.tenant_id = tenant_id

    def fetch(self, query: CompetitorQuery) -> CompetitorData:
        if query.rows:
            return CompetitorData(
                rows=[dict(row) for row in query.rows],
                source=SOURCE_MANUAL,
                is_demo=_looks_like_demo(query.rows),
            )
        if not query.batch_id:
            return CompetitorData(
                notes=["没有提供竞品行，也没有指定导入批次"],
            )
        if self.db is None:
            raise CompetitorProviderError("读取导入批次需要数据库连接")
        batch = self.db.get_import_batch(query.batch_id, self.tenant_id)
        if batch is None:
            # 不存在与不属于本租户**不区分**：区分等于泄露别的租户有没有这个 id
            return CompetitorData(
                notes=["导入批次不存在或不属于当前空间"],
            )
        rows = batch.get("competitors")
        if not isinstance(rows, list):
            # 兼容旧批次结构：payload 直接是行数组
            rows = batch if isinstance(batch, list) else []
        return CompetitorData(
            rows=rows,
            source=SOURCE_IMPORT,
            is_demo=_looks_like_demo(rows),
            notes=[f"来自导入批次，共 {len(rows)} 条"],
        )


# ---------------------------------------------------------------------------
# 预留：真实数据源（未接入，不得假装可用）
# ---------------------------------------------------------------------------


class LiveCompetitorProvider:
    """真实竞品数据源。**当前没有接入任何平台，因此永远抛异常。**

    刻意不实现「拿到凭据就返回点什么」：没有真实接口时返回任何数据都是错的，
    而返回导入数据冒充 live 是错得更彻底的一种。
    """

    name = "live"
    mode = MODE_LIVE

    def __init__(self, db: Any = None, tenant_id: str = "", connection: dict[str, Any] | None = None):
        self.db = db
        self.tenant_id = tenant_id
        self.connection = connection or {}

    @property
    def configured(self) -> bool:
        """是否已配置凭据。当前即便配了也不可用，这里只用于给出不同的提示。"""
        return bool(self.connection.get("credentials"))

    def fetch(self, query: CompetitorQuery) -> CompetitorData:
        if not self.configured:
            raise ProviderNotConfigured(
                "还没有接入真实竞品数据源；当前请通过导入 CSV/JSON 提供竞品数据"
            )
        raise ProviderNotConfigured(
            "真实竞品数据源正在接入，当前不可用；请在接入完成前使用导入的数据"
        )


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------


def build_competitor_provider(
    mode: str = MODE_IMPORTED,
    *,
    db: Any = None,
    tenant_id: str = "",
    connection: dict[str, Any] | None = None,
) -> Any:
    """按模式构造 Provider。未知模式直接报错，不猜。"""
    normalized = (mode or MODE_IMPORTED).strip().lower()
    if normalized == MODE_IMPORTED:
        return ImportedCompetitorProvider(db, tenant_id)
    if normalized == MODE_LIVE:
        return LiveCompetitorProvider(db, tenant_id, connection)
    raise CompetitorProviderError(f"未知的数据源模式：{mode}")


def _looks_like_demo(rows: list[dict[str, Any]] | None) -> bool:
    """任意一条被标成示例数据，整批就按示例数据处理。"""
    for row in rows or []:
        if isinstance(row, dict) and row.get("is_demo") is True:
            return True
    return False


__all__ = [
    "MODE_IMPORTED",
    "MODE_LIVE",
    "SOURCE_IMPORT",
    "SOURCE_LIVE",
    "SOURCE_MANUAL",
    "CompetitorData",
    "CompetitorProvider",
    "CompetitorProviderError",
    "CompetitorQuery",
    "ImportedCompetitorProvider",
    "LiveCompetitorProvider",
    "ProviderNotConfigured",
    "build_competitor_provider",
]
