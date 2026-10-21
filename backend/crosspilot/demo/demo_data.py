"""模拟数据（demo）。

**重要声明**：以下所有商品、评论、价格与关键词均为激浪团队为演示流程而
编写的虚构数据，不是真实 Amazon 商品，也不代表任何真实销量、搜索量或排名。
所有对象都带 ``is_demo=True`` 或 ``source="demo"`` 标记，接口与报告中会再次提示。
"""

from __future__ import annotations

from typing import Any

DEMO_NOTICE = (
    "⚠️ 以下全部为激浪模拟演示数据（demo）：商品名、价格、评分、评论、关键词均为虚构，"
    "不代表真实 Amazon 商品，也不含任何真实销量、搜索量或排名。仅用于演示分析流程。"
)

DEMO_KEYWORDS: list[dict[str, Any]] = [
    {
        "keyword": "insulated water bottle",
        "search_volume": None,
        "rank": None,
        "relevance": None,
        "competition": None,
        "source": "demo（无指标：演示'缺指标不编造'约束）",
    },
    {
        "keyword": "stainless steel tumbler",
        "search_volume": None,
        "rank": None,
        "relevance": None,
        "competition": None,
        "source": "demo（无指标）",
    },
    {
        "keyword": "leak proof bottle",
        "search_volume": None,
        "rank": None,
        "relevance": None,
        "competition": None,
        "source": "demo（无指标）",
    },
]

DEMO_COMPETITORS: list[dict[str, Any]] = [
    {
        "name": "AquaPeak 32oz Insulated Water Bottle",
        "brand": "AquaPeak",
        "asin": "DEMO-AQUA-001",
        "price": 25.99,
        "currency": "USD",
        "rating": 4.4,
        "review_count": 1842,
        "category": "Sports Water Bottles",
        "key_features": [
            "Double-wall vacuum insulation",
            "Leak-proof twist lid",
            "Fits standard cup holders",
            "Dishwasher safe",
        ],
        "specifications": {"容量": "32oz", "材质": "18/8 stainless steel", "颜色": "Matte Black"},
        "is_demo": True,
        "source_ref": "demo-dataset-v1",
        "reviews": [
            {"rating": 5, "title": "Keeps water cold all day", "text": "Ice was still there after 9 hours in a hot car. Great insulation.", "source": "demo"},
            {"rating": 4, "title": "Good but heavy", "text": "Works well, though it is heavier than my old plastic bottle.", "source": "demo"},
            {"rating": 2, "title": "Lid leaked", "text": "The lid leaked in my bag on day three. Water everywhere, very disappointed.", "source": "demo"},
            {"rating": 5, "title": "Easy to clean", "text": "Dishwasher safe and the wide mouth makes it easy to clean.", "source": "demo"},
            {"rating": 3, "title": "Not as described", "text": "Color is different from the pictures. Looks more grey than black.", "source": "demo"},
            {"rating": 1, "title": "Broke quickly", "text": "Stopped holding cold after two weeks and the paint flaked off.", "source": "demo"},
        ],
    },
    {
        "name": "TrailMate Stainless Steel Tumbler 20oz",
        "brand": "TrailMate",
        "asin": "DEMO-TRAIL-002",
        "price": 18.5,
        "currency": "USD",
        "rating": 4.1,
        "review_count": 963,
        "category": "Tumblers",
        "key_features": [
            "Fits most car cup holders",
            "Sweat-free exterior",
            "BPA-free lid",
        ],
        "specifications": {"容量": "20oz", "材质": "Stainless steel", "颜色": "Navy"},
        "is_demo": True,
        "source_ref": "demo-dataset-v1",
        "reviews": [
            {"rating": 5, "title": "Perfect for commuting", "text": "Fits in my cup holder and no condensation at all.", "source": "demo"},
            {"rating": 2, "title": "Cheap plastic lid", "text": "The lid feels cheap and cracked after a month. Poor quality.", "source": "demo"},
            {"rating": 4, "title": "Good value", "text": "For the price it is a good value, keeps drinks cold for a few hours.", "source": "demo"},
            {"rating": 3, "title": "Hard to clean", "text": "Hard to clean the narrow opening, coffee smell stays inside.", "source": "demo"},
            {"rating": 5, "title": "Gift for my dad", "text": "Bought it as a gift, packaging was nice.", "source": "demo"},
        ],
    },
    {
        "name": "HydraCore Leak Proof Sports Bottle 24oz",
        "brand": "HydraCore",
        "asin": "DEMO-HYDRA-003",
        "price": 31.0,
        "currency": "USD",
        "rating": 4.6,
        "review_count": 2310,
        "category": "Sports Water Bottles",
        "key_features": [
            "One-hand flip lid",
            "Leak-proof lock mechanism",
            "Fits gym bags",
            "Lifetime warranty",
        ],
        "specifications": {"容量": "24oz", "材质": "Tritan plastic", "颜色": "Clear/Blue"},
        "is_demo": True,
        "source_ref": "demo-dataset-v1",
        "reviews": [
            {"rating": 5, "title": "Leak proof indeed", "text": "Lock mechanism is solid, no leaks in my gym bag.", "source": "demo"},
            {"rating": 4, "title": "Light and portable", "text": "Lightweight and portable, easy to carry.", "source": "demo"},
            {"rating": 2, "title": "Started leaking", "text": "Started leaking after a month, the seal wore out.", "source": "demo"},
            {"rating": 3, "title": "Plastic smell", "text": "There is a strong plastic smell that did not go away.", "source": "demo"},
            {"rating": 5, "title": "Great for kids", "text": "Bought for my kids, the flip lid is easy for them to use.", "source": "demo"},
            {"rating": 4, "title": "Wish it was bigger", "text": "Great bottle but too small for long hikes.", "source": "demo"},
        ],
    },
]

DEMO_OWN_PRODUCT: dict[str, Any] = {
    "name": "EcoSip Insulated Water Bottle",
    "brand": "EcoSip",
    "category": "Sports Water Bottles",
    "specifications": {
        "容量": "750ml",
        "材质": "食品级 304 不锈钢",
        "颜色": "雾霾蓝",
        "重量": "380g",
        "尺寸": "26cm x 7.5cm",
    },
    "key_features": [
        "双层真空保温，冷饮保温 24 小时",
        "一体成型内胆，不藏污垢",
        "宽口设计，方便加冰与清洗",
        "防漏硅胶密封圈，经 500 次开合测试",
    ],
    "materials": ["304 不锈钢", "食品级硅胶"],
    "certifications": [],
    "target_platform": "amazon",
    "marketplace": "US",
    "price": 22.9,
    "currency": "USD",
    "target_audience": "通勤上班族与健身人群",
    "brand_voice": "专业、可靠、不夸大",
    "banned_terms": [],
    "differentiators": [],
}

# 用于演示"缺少商品规格"时的行为：只有名称与一条卖点
DEMO_OWN_PRODUCT_SPARSE: dict[str, Any] = {
    "name": "EcoSip Insulated Water Bottle",
    "brand": "EcoSip",
    "category": "Sports Water Bottles",
    "specifications": {},
    "key_features": ["双层真空保温"],
    "materials": [],
    "certifications": [],
    "target_platform": "amazon",
    "marketplace": "US",
    "target_audience": None,
}

DEMO_ANALYSIS_REQUEST: dict[str, Any] = {
    "product_name": "EcoSip Insulated Water Bottle",
    "platform": "amazon",
    "marketplace": "US",
    "category": "Sports Water Bottles",
    "own_specs": DEMO_OWN_PRODUCT["specifications"],
    "own_key_features": DEMO_OWN_PRODUCT["key_features"],
    "own_price": 22.9,
    "competitors": DEMO_COMPETITORS,
    "keywords": DEMO_KEYWORDS,
    "data_source": "demo",
    "locale": "zh-CN",
}

DEMO_LISTING_REQUEST: dict[str, Any] = {
    "product": DEMO_OWN_PRODUCT,
    "language": "en-US",
    "marketplace": "US",
    "keywords": DEMO_KEYWORDS,
    "tone": "专业、可靠、不夸大",
    "banned_terms": [],
    "target_length_hint": "medium",
    "data_source": "demo",
}


def get_demo_dataset() -> dict[str, Any]:
    """返回前端/接口可直接消费的完整演示数据集。"""
    return {
        "notice": DEMO_NOTICE,
        "is_demo": True,
        "analysis_request": DEMO_ANALYSIS_REQUEST,
        "listing_request": DEMO_LISTING_REQUEST,
        "own_product": DEMO_OWN_PRODUCT,
        "own_product_sparse": DEMO_OWN_PRODUCT_SPARSE,
        "competitors": DEMO_COMPETITORS,
        "keywords": DEMO_KEYWORDS,
    }


__all__ = [
    "DEMO_ANALYSIS_REQUEST",
    "DEMO_COMPETITORS",
    "DEMO_KEYWORDS",
    "DEMO_LISTING_REQUEST",
    "DEMO_NOTICE",
    "DEMO_OWN_PRODUCT",
    "DEMO_OWN_PRODUCT_SPARSE",
    "get_demo_dataset",
]
