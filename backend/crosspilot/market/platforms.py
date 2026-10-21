"""跨境平台目录：把各平台的差异集中描述，为真实接入留好位置。

**本期不实现任何真实调用。** 这里只做三件事：

1. **平台清单**：字段名、站点、能力、认证方式一次说清，避免各处硬编码 ``"amazon"``；
2. **授权 URL 拼装**：``build_authorize_url()`` 是纯函数，可测；真正换 token 的部分显式
   抛 ``PlatformNotConnected``，不伪造授权结果；
3. **能力声明**：前端/后端据此决定哪些按钮可用（没有 ``ads`` 能力的平台不显示广告入口）。

设计边界：

- 平台 key 用小写、无空格（``amazon`` / ``tiktok`` / ``shopee``）；
- **未知平台不报错**：历史数据与用户自建的 mock 店铺可能带任意 ``platform``，
  读取时标 ``known=False`` 即可，拒绝会让旧数据变成"坏数据"；
- 新增平台只改这个文件，不动 ``services/connectors.py`` 与 API。

真实接入时要补的（每平台一份）：

- ``PlatformSpec.oauth`` 填真实端点与 scope；
- 实现 ``exchange_code()`` / ``refresh()``：调用平台 token 接口并落到
  ``store_credentials``（密文，只在服务端解密）；
- 实现字段映射：平台的商品/订单字段 → 本项目统一的 ``list_products`` / ``list_orders`` 契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

# 能力标签。没有的能力不要在前端露入口，否则点了必然 501。
CAP_PRODUCTS = "products"
CAP_ORDERS = "orders"
CAP_ADS = "ads"
CAP_METRICS = "metrics"
CAP_FEES = "fees"
ALL_CAPABILITIES = (CAP_PRODUCTS, CAP_ORDERS, CAP_ADS, CAP_METRICS, CAP_FEES)


class PlatformError(RuntimeError):
    """平台层错误（消息可直接展示）。"""


class PlatformNotConnected(PlatformError):
    """平台真实接入未完成 / 未授权。"""


class UnknownPlatform(PlatformError):
    """平台不在目录里（仅用于需要显式拒绝的场景，如创建真实连接）。"""


@dataclass(frozen=True)
class PlatformOAuth:
    """授权端点声明。**端点是真的，流程未实现**——只用来拼 URL。"""

    authorize_endpoint: str
    token_endpoint: str
    scopes: tuple[str, ...] = ()
    #: 平台特有的固定参数（如 Amazon 的 version=beta）
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    label: str
    region: str
    marketplaces: tuple[str, ...]
    #: 商品主键在该平台的叫法：ASIN / goods_id / item_id / sku
    product_id_field: str
    capabilities: frozenset[str]
    auth: str
    live_status: str
    docs_url: str
    oauth: PlatformOAuth | None = None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "region": self.region,
            "marketplaces": list(self.marketplaces),
            "product_id_field": self.product_id_field,
            "capabilities": [cap for cap in ALL_CAPABILITIES if cap in self.capabilities],
            "auth": self.auth,
            "live_status": self.live_status,
            "docs_url": self.docs_url,
            "note": self.note,
        }


#: 真实接入状态。目前所有平台都是 ``not_configured``：
#: 应用未注册 / 卖家未授权 / 平台未审核，一律不伪造数据。
LIVE_NOT_CONFIGURED = "not_configured"
LIVE_PENDING_REVIEW = "pending_review"
LIVE_AVAILABLE = "available"

_COMMERCE_CAPS = frozenset({CAP_PRODUCTS, CAP_ORDERS, CAP_METRICS})
_FULL_CAPS = frozenset({CAP_PRODUCTS, CAP_ORDERS, CAP_METRICS, CAP_ADS, CAP_FEES})


PLATFORMS: tuple[PlatformSpec, ...] = (
    PlatformSpec(
        key="amazon",
        label="Amazon",
        region="北美 / 欧洲 / 日本 / 澳洲",
        marketplaces=("US", "CA", "MX", "UK", "DE", "FR", "IT", "ES", "JP", "AU", "SG", "AE"),
        product_id_field="asin",
        capabilities=_FULL_CAPS,
        auth="oauth2",
        live_status=LIVE_NOT_CONFIGURED,
        docs_url="https://developer-docs.amazon.com/sp-api/",
        oauth=PlatformOAuth(
            authorize_endpoint="https://sellercentral.amazon.com/apps/authorize/consent",
            token_endpoint="https://api.amazon.com/auth/o2/token",
            scopes=("sellingpartnerapi::migration",),
            extra={"version": "beta"},
        ),
        note="SP-API：需要 Seller Central 开发者账号 + 应用审核 + 卖家授权。",
    ),
    PlatformSpec(
        key="temu",
        label="Temu",
        region="北美 / 欧洲 / 澳洲 / 日韩",
        marketplaces=("US", "CA", "UK", "DE", "FR", "IT", "ES", "AU", "NZ", "JP", "KR"),
        product_id_field="goods_id",
        capabilities=_COMMERCE_CAPS,
        auth="app_secret",
        live_status=LIVE_NOT_CONFIGURED,
        docs_url="https://seller.temu.com/",
        note="Temu 开放平台走应用签名（app_key + app_secret），非 OAuth。",
    ),
    PlatformSpec(
        key="tiktok",
        label="TikTok Shop",
        region="美国 / 英国 / 东南亚",
        marketplaces=("US", "UK", "ID", "TH", "VN", "MY", "PH", "SG"),
        product_id_field="product_id",
        capabilities=frozenset({CAP_PRODUCTS, CAP_ORDERS, CAP_ADS, CAP_METRICS}),
        auth="oauth2",
        live_status=LIVE_NOT_CONFIGURED,
        docs_url="https://partner.tiktokshop.com/doc",
        oauth=PlatformOAuth(
            authorize_endpoint="https://auth.tiktok-shops.com/oauth/authorize",
            token_endpoint="https://auth.tiktok-shops.com/api/v2/token/get",
            scopes=("seller.product.read", "seller.order.read", "seller.analytics.read"),
        ),
        note="TikTok Shop Partner Center 需要应用审核。",
    ),
    PlatformSpec(
        key="shopee",
        label="Shopee",
        region="东南亚 / 台湾 / 拉美",
        marketplaces=("SG", "MY", "TH", "ID", "VN", "PH", "TW", "BR", "MX"),
        product_id_field="item_id",
        capabilities=_COMMERCE_CAPS | {CAP_ADS},
        auth="oauth2",
        live_status=LIVE_NOT_CONFIGURED,
        docs_url="https://open.shopee.com/",
        oauth=PlatformOAuth(
            authorize_endpoint="https://partner.shopeemobile.com/api/v2/shop/auth_partner",
            token_endpoint="https://partner.shopeemobile.com/api/v2/auth/access_token/get",
        ),
    ),
    PlatformSpec(
        key="ebay",
        label="eBay",
        region="北美 / 欧洲 / 澳洲",
        marketplaces=("EBAY_US", "EBAY_GB", "EBAY_DE", "EBAY_AU"),
        product_id_field="item_id",
        capabilities=_FULL_CAPS,
        auth="oauth2",
        live_status=LIVE_NOT_CONFIGURED,
        docs_url="https://developer.ebay.com/api-docs/",
        oauth=PlatformOAuth(
            authorize_endpoint="https://auth.ebay.com/oauth2/authorize",
            token_endpoint="https://api.ebay.com/identity/v1/oauth2/token",
            scopes=(
                "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
                "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
            ),
        ),
    ),
    PlatformSpec(
        key="walmart",
        label="Walmart Marketplace",
        region="美国 / 加拿大 / 墨西哥",
        marketplaces=("US", "CA", "MX"),
        product_id_field="sku",
        capabilities=frozenset({CAP_PRODUCTS, CAP_ORDERS, CAP_METRICS}),
        auth="client_credentials",
        live_status=LIVE_NOT_CONFIGURED,
        docs_url="https://developer.walmart.com/",
        oauth=PlatformOAuth(
            authorize_endpoint="",  # client_credentials 没有用户授权跳转
            token_endpoint="https://marketplace.walmartapis.com/v3/token",
        ),
        note="Walmart 用 client_credentials 换 token，没有用户授权跳转。",
    ),
    PlatformSpec(
        key="aliexpress",
        label="AliExpress",
        region="全球",
        marketplaces=("GLOBAL",),
        product_id_field="product_id",
        capabilities=_COMMERCE_CAPS | {CAP_ADS},
        auth="oauth2",
        live_status=LIVE_NOT_CONFIGURED,
        docs_url="https://open.aliexpress.com/",
        oauth=PlatformOAuth(
            authorize_endpoint="https://api-sg.aliexpress.com/oauth/authorize",
            token_endpoint="https://api-sg.aliexpress.com/sync",
        ),
    ),
    PlatformSpec(
        key="shopify",
        label="Shopify（独立站）",
        region="全球",
        marketplaces=("GLOBAL",),
        product_id_field="product_id",
        capabilities=_FULL_CAPS,
        auth="oauth2",
        live_status=LIVE_NOT_CONFIGURED,
        docs_url="https://shopify.dev/docs/api/admin",
        oauth=PlatformOAuth(
            authorize_endpoint="https://{shop}/admin/oauth/authorize",
            token_endpoint="https://{shop}/admin/oauth/access_token",
            scopes=("read_products", "read_orders", "read_analytics"),
        ),
        note="授权端点按店铺域名拼装，{shop} 由调用方替换。",
    ),
    PlatformSpec(
        key="custom",
        label="自定义 / 自建站",
        region="—",
        marketplaces=("GLOBAL",),
        product_id_field="product_id",
        capabilities=_COMMERCE_CAPS,
        auth="custom",
        live_status=LIVE_NOT_CONFIGURED,
        docs_url="",
        note="走自己的接口，凭据由部署方提供；本项目不内置任何 endpoint。",
    ),
)

PLATFORM_BY_KEY: dict[str, PlatformSpec] = {spec.key: spec for spec in PLATFORMS}

DEFAULT_PLATFORM = "amazon"


def platform_spec(key: str | None) -> PlatformSpec | None:
    """按 key 找平台；未知返回 ``None``（**不抛错**，见模块说明）。"""
    if not key:
        return None
    return PLATFORM_BY_KEY.get(key.strip().lower())


def is_known(key: str | None) -> bool:
    return platform_spec(key) is not None


def list_platforms() -> list[dict[str, Any]]:
    """给前端"新建店铺"下拉用的清单。"""
    return [spec.as_dict() for spec in PLATFORMS]


def build_authorize_url(
    key: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    shop: str = "",
) -> str:
    """拼授权跳转 URL（纯函数，不发起请求）。

    缺应用凭据时抛 ``PlatformNotConnected``——宁可明确报"未接入"，
    也不要拼一个用户点了 404 的链接。
    """
    spec = platform_spec(key)
    if spec is None:
        raise UnknownPlatform(f"未知平台：{key}")
    if spec.oauth is None:
        raise PlatformNotConnected(
            f"{spec.label} 不支持授权跳转（认证方式：{spec.auth}），"
            "请改用应用密钥方式配置"
        )
    if not client_id or not redirect_uri or not state:
        raise PlatformNotConnected(
            f"{spec.label} 的真实接入尚未配置：需要 {spec.auth} 应用凭据"
            "（client_id / redirect_uri / state）"
        )

    endpoint = spec.oauth.authorize_endpoint
    if not endpoint:
        raise PlatformNotConnected(
            f"{spec.label} 走 {spec.auth}，没有用户授权跳转；"
            "请在服务端用应用凭据直接换 token"
        )
    if "{shop}" in endpoint:
        if not shop:
            raise PlatformNotConnected(f"{spec.label} 需要先填写店铺域名（shop）")
        endpoint = endpoint.replace("{shop}", shop.strip())

    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        **spec.oauth.extra,
    }
    if spec.oauth.scopes:
        joiner = "," if spec.key in {"shopify", "tiktok"} else " "
        params["scope"] = joiner.join(spec.oauth.scopes)
    return f"{endpoint}?{urlencode(params)}"


def exchange_code(key: str, *, code: str) -> dict[str, Any]:
    """用授权码换 token：**未实现**，显式报错。

    真实实现要做：调用 ``oauth.token_endpoint``、校验签名/证书、
    把 token 加密写进 ``store_credentials``，并返回不含明文的引用。
    """
    spec = platform_spec(key)
    label = spec.label if spec else key
    raise PlatformNotConnected(
        f"{label} 的授权换 token 尚未接入（本期只预留接口与 URL 拼装）；"
        "当前不会伪造任何授权结果"
    )


__all__ = [
    "ALL_CAPABILITIES",
    "CAP_ADS",
    "CAP_FEES",
    "CAP_METRICS",
    "CAP_ORDERS",
    "CAP_PRODUCTS",
    "DEFAULT_PLATFORM",
    "LIVE_AVAILABLE",
    "LIVE_NOT_CONFIGURED",
    "LIVE_PENDING_REVIEW",
    "PLATFORMS",
    "PLATFORM_BY_KEY",
    "PlatformError",
    "PlatformNotConnected",
    "PlatformOAuth",
    "PlatformSpec",
    "UnknownPlatform",
    "build_authorize_url",
    "exchange_code",
    "is_known",
    "list_platforms",
    "platform_spec",
]
