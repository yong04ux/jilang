"""把内部字段名与校验消息转成业务语言。

为什么单独一模块：

- 字段名（``own_key_features`` / ``review_list[0].rating``）和 Pydantic 的
  英文原句（``Input should be a valid number``）都是实现细节。它们一旦进到
  响应体，前端就只能把代码变量原样印在界面上——用户看不懂，也不知道该改哪。
- 转换必须放在**接口边界**，而不是解析逻辑里：解析层保持原样，测试与内部
  调用方继续按字段名比较，只有出门给别人看的那一份才是中文。

用法：凡是把 ``field`` / ``message`` 拼进响应的地方，都先过一遍这里。
"""

from __future__ import annotations

import re
from typing import Any

# 字段 → 用户能看懂的名字。键既包括模型字段，也包括接口入参。
FIELD_LABELS: dict[str, str] = {
    # 竞品 / 商品
    "name": "商品名称",
    "product_name": "商品名称",
    "brand": "品牌",
    "asin": "ASIN",
    "price": "价格",
    "currency": "币种",
    "rating": "评分",
    "review_count": "评论数",
    "category": "类目",
    "key_features": "核心卖点",
    "specifications": "规格",
    "materials": "材质",
    "certifications": "认证",
    "source_ref": "外部商品编号",
    "source": "来源",
    "is_demo": "是否示例数据",
    "reviews": "评论样本",
    "review_list": "评论样本",
    "review_text": "评论内容",
    "text": "评论内容",
    "date": "日期",
    "language": "语言",
    "verified_purchase": "是否验证购买",
    # 关键词
    "keyword": "关键词",
    "keywords": "关键词",
    "search_volume": "搜索量",
    "rank": "排名",
    "relevance": "相关度",
    "competition": "竞争度",
    "conversion_share": "转化占比",
    # 目标 / 运行参数
    "goal": "业务目标",
    "competitor": "竞品",
    "competitors": "竞品",
    "platform": "平台",
    "target_platform": "平台",
    "marketplace": "站点",
    "own_specs": "你的规格",
    "own_key_features": "你的卖点",
    "own_price": "你的价格",
    "target_audience": "目标人群",
    "brand_voice": "品牌语气",
    "banned_terms": "禁用词",
    "differentiators": "差异化卖点",
    "with_listing": "同时生成 Listing",
    "listing_language": "Listing 语言",
    "data_source": "数据来源",
    "async_run": "后台执行",
    "conversation_id": "会话",
    "agent_key": "Agent",
    "skill_keys": "技能",
    # Listing
    "title": "标题",
    "bullets": "五点描述",
    "description": "描述",
    "search_terms": "Search Terms",
    "product": "商品",
    "analysis_report": "分析报告",
    "analysis_report_id": "分析报告",
    "report": "分析报告",
    "report_id": "分析报告",
    "listing": "Listing 草稿",
    "listing_id": "Listing 草稿",
    "tone": "语气",
    "locale": "站点语言",
    "target_length_hint": "篇幅要求",
    # 能力（技能）入参
    "filename": "文件名",
    "content_base64": "文件",
    "allow_partial_rows": "允许部分行出错",
    "import_batch_id": "数据批次",
    "batch_id": "数据批次",
    # 成本与利润
    "fulfillment": "履约方式",
    "selling_price": "单件售价",
    "purchase_cost": "采购成本",
    "shipping_cost": "头程运费",
    "packaging_cost": "包装耗材",
    "fulfillment_fee": "履约配送费",
    "other_cost": "其他成本",
    "ad_cost_per_order": "广告摊销（每单）",
    "commission_rate": "平台佣金率",
    "return_rate": "退货率",
    "return_handling_cost": "退货处理成本",
    "fixed_cost": "一次性投入",
    "target_margin": "目标毛利率",
    # 模型配置
    "provider": "服务商",
    "api_key": "API Key",
    "base_url": "接口地址",
    "model": "模型名",
    "label": "配置标签",
    "allow_custom": "自定义接口地址确认",
    # 账号 / 团队
    "username": "账号",
    "password": "密码",
    "display_name": "显示名",
    "role": "角色",
    "email": "邮箱",
    # 其他入参
    "reason": "理由",
    "note": "备注",
    "memo": "备注",
    "file": "文件",
    "row": "行",
    "rows": "行数",
    "limit": "条数",
    "offset": "起始位置",
    "status": "状态",
    "priority": "优先级",
    "quantity": "数量",
    "decision": "决定",
    "comment": "意见",
    "against": "对比版本",
}

# Pydantic v2 的 type → 用户能看懂的一句话。用 {limit} 承接 ctx 里的阈值。
TYPE_TEMPLATES: dict[str, str] = {
    "missing": "必填，不能为空",
    "string_type": "需要填写文字",
    "string_too_short": "至少 {limit} 个字",
    "string_too_long": "最多 {limit} 个字",
    "string_pattern_mismatch": "格式不正确",
    "string_unicode": "含有无法识别的字符",
    "int_type": "需要整数",
    "int_parsing": "需要整数",
    "int_from_float": "需要整数",
    "float_type": "需要数字",
    "float_parsing": "需要数字",
    "decimal_type": "需要数字",
    "decimal_parsing": "需要数字",
    "decimal_max_digits": "小数位数过多",
    "bool_type": "只能是是或否",
    "bool_parsing": "只能是是或否",
    "list_type": "需要是一个列表",
    "dict_type": "需要是键值对格式",
    "tuple_type": "需要是一个列表",
    "set_type": "需要是一个列表",
    "greater_than": "需要大于 {limit}",
    "greater_than_equal": "不能小于 {limit}",
    "less_than": "需要小于 {limit}",
    "less_than_equal": "不能大于 {limit}",
    "too_short": "至少需要 {limit} 项",
    "too_long": "最多 {limit} 项",
    "enum": "取值不在可选范围内",
    "literal_error": "取值不在可选范围内",
    "url_parsing": "地址格式不正确",
    "url_scheme": "地址要以 http:// 或 https:// 开头",
    "url_type": "地址格式不正确",
    "datetime_parsing": "时间格式不正确",
    "datetime_type": "时间格式不正确",
    "date_parsing": "日期格式不正确",
    "json_invalid": "格式不正确",
    "json_type": "格式不正确",
    "model_type": "结构不正确",
    "model_attributes_type": "结构不正确",
    "extra_forbidden": "这一项不用填，删掉即可",
}

_INDEX_RE = re.compile(r"\[(\d+)\]")

# 生成方式：engine 是内部标识（rule / rule-fallback / deepseek…），界面只说人话
ENGINE_LABELS: dict[str, str] = {
    "rule": "规则生成",
    "rule-fallback": "规则生成",
    "deepseek": "AI 模型生成",
    "openai": "AI 模型生成",
}

# 目标语言 code → 中文名，用于「与目标语言不符」这类提示
LANGUAGE_LABELS: dict[str, str] = {
    "en": "英文",
    "de": "德文",
    "fr": "法文",
    "es": "西班牙文",
    "it": "意大利文",
    "ja": "日文",
    "zh": "中文",
}


def engine_label(engine: str | None) -> str:
    if not engine:
        return "未配置"
    return ENGINE_LABELS.get(engine, "AI 模型生成")


# 数据来源：接口与报表里传的是 manual / csv / json / demo，界面不该出现这些词
DATA_SOURCE_LABELS: dict[str, str] = {
    "manual": "手工填写",
    "user_input": "手工填写",
    "csv": "CSV 文件",
    "json": "JSON 文件",
    "xlsx": "Excel 文件",
    "excel": "Excel 文件",
    "demo": "示例数据",
    "mock": "示例数据",
    "live": "店铺接口",
    "store": "店铺接口",
}


def data_source_label(source: str | None) -> str:
    if not source:
        return "未记录"
    return DATA_SOURCE_LABELS.get(source.lower(), source)


def language_label(code: str | None) -> str:
    """``en-US`` → ``英文``；认不出的原样返回。"""
    if not code:
        return ""
    base = code.replace("_", "-").split("-")[0].lower()
    return LANGUAGE_LABELS.get(base, code)


def _limit_from(ctx: dict[str, Any]) -> str | None:
    for key in ("gt", "ge", "lt", "le", "min_length", "max_length"):
        value = ctx.get(key)
        if value is None:
            continue
        if key == "min_length" and isinstance(value, int):
            return str(value)
        return str(value)
    return None


def humanize_message(message: str, error_type: str = "", ctx: dict[str, Any] | None = None) -> str:
    """把 Pydantic 的英文原句换成中文；认不出的原样保留，不吞掉细节。"""
    template = TYPE_TEMPLATES.get(error_type or "")
    if template:
        if "{limit}" in template:
            limit = _limit_from(ctx or {})
            if limit is None:
                return re.sub(r"\s*\{limit\}", "", template).rstrip() or "超出允许范围"
            return template.replace("{limit}", limit)
        return template

    text = (message or "").strip()
    # Pydantic 自定义校验器抛 ValueError 时统一带这个前缀，后面的内容是中文
    for prefix in ("Value error, ", "Assertion failed, "):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text or "填写内容不符合要求"


def humanize_field(path: str) -> str:
    """``body.competitors[0].own_price`` → ``竞品 · 第 1 项 · 价格``。"""
    raw = (path or "").strip()
    if not raw:
        return ""

    parts: list[str] = []
    for chunk in raw.split("."):
        if not chunk or chunk in ("body", "query", "path", "header", "cookie"):
            continue
        # FastAPI 的 loc 用 "competitors.0.price"，Pydantic 直调用 "competitors[0].price"
        if chunk.isdigit():
            parts.append(f"第 {int(chunk) + 1} 项")
            continue
        base = _INDEX_RE.sub("", chunk)
        indexes = _INDEX_RE.findall(chunk)
        if base:
            parts.append(FIELD_LABELS.get(base, base))
        for index in indexes:
            parts.append(f"第 {int(index) + 1} 项")

    if not parts:
        return "请求内容"
    return " · ".join(parts)


def humanize_error(error: dict[str, Any]) -> dict[str, Any]:
    """把单条校验错误整条转成中文，其余键（row / value）保持不动。

    ``ctx`` 只用来拼阈值，转完就丢掉——它含原始输入值，不该出现在响应里。
    """
    result = dict(error)
    code = str(error.get("type") or "")
    ctx = result.pop("ctx", None)
    ctx = ctx if isinstance(ctx, dict) else {}
    if "field" in result:
        result["field"] = humanize_field(str(result.get("field") or ""))
    if "message" in result:
        result["message"] = humanize_message(str(result.get("message") or ""), code, ctx)
    return result


def humanize_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [humanize_error(error) for error in errors]


__all__ = [
    "ENGINE_LABELS",
    "FIELD_LABELS",
    "DATA_SOURCE_LABELS",
    "LANGUAGE_LABELS",
    "TYPE_TEMPLATES",
    "data_source_label",
    "engine_label",
    "humanize_error",
    "humanize_errors",
    "humanize_field",
    "humanize_message",
    "language_label",
]
