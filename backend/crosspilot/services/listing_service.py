"""Listing 服务（阶段 E2/E4/E5/E3）。

- ``generate``：包装 Provider，并保留商品事实快照（供后续复检）；
- ``create_version``：派生新版本，记录 parent/version；
- ``diff``：结构化字段差异 + 标题/描述的统一 diff；
- ``recheck``：复用 ``listing.run_quality_check``，不重新实现规则；
- ``export_listing``：Markdown / JSON / TXT。

不做的事情：不在这里写文案算法，也不直接访问 HTTP。
"""

from __future__ import annotations

import copy
import difflib
import json
import uuid
from typing import Any

from ..persistence.db import Database
from ..engine.listing import run_quality_check
from ..models import ListingDraft, ListingGenerationRequest, OwnProduct
from ..engine.rules import get_rules
from ..tenancy import TenantContext
from ..engine.textutils import char_len


class ListingError(ValueError):
    """Listing 操作的可预期错误。"""


class ListingNotFound(ListingError):
    pass


class ListingSnapshotMissing(ListingError):
    """历史草稿没有商品事实快照，无法重跑事实对齐质检。"""


def generate(
    provider, request: ListingGenerationRequest, report_payload: dict[str, Any] | None
) -> ListingDraft:
    return provider.generate(request, report_payload)


def dump_for_storage(
    listing: ListingDraft, request: ListingGenerationRequest | None = None
) -> dict[str, Any]:
    """模型输出 + 商品事实快照。快照只用于复检，不参与对外展示。"""
    payload = listing.model_dump(mode="json")
    if request is not None:
        payload["product_snapshot"] = request.product.model_dump(mode="json")
    return payload


def _load(db: Database, ctx: TenantContext, listing_id: str) -> dict[str, Any]:
    payload = db.get_listing(
        listing_id, user_id=ctx.user_id, tenant_id=ctx.tenant_id
    )
    if payload is None:
        raise ListingNotFound("Listing 不存在")
    return payload


def _quality(product: OwnProduct, draft: ListingDraft) -> dict[str, Any]:
    ruleset = get_rules()
    rules = ruleset.platform_rules(product.target_platform, product.marketplace)
    banned = ruleset.banned_terms(product.banned_terms)
    return run_quality_check(draft, product, rules, banned).model_dump(mode="json")


def recheck(
    db: Database, ctx: TenantContext, listing_id: str
) -> dict[str, Any]:
    """重新执行事实对齐质检，并把结果写回草稿。"""
    payload = _load(db, ctx, listing_id)
    snapshot = payload.get("product_snapshot")
    if not snapshot:
        raise ListingSnapshotMissing(
            "该草稿生成于阶段 E 之前，没有保存商品事实快照，无法重新质检；"
            "请重新生成或等待历史数据补齐"
        )
    try:
        product = OwnProduct(**snapshot)
        draft = ListingDraft(**payload)
    except Exception as exc:  # noqa: BLE001 - 老数据可能字段不全
        raise ListingSnapshotMissing(f"草稿数据不完整，无法复检：{exc}") from exc
    quality = _quality(product, draft)
    db.update_listing_quality(listing_id, quality)
    return quality


def create_version(
    db: Database,
    ctx: TenantContext,
    listing_id: str,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """基于已有草稿派生新版本。

    只允许修改文案字段；商品事实快照、关联报告与事实台账保持不变，
    修改后重新执行质检——编辑不能让"不实声明"绕过质检。
    """
    base = _load(db, ctx, listing_id)
    new_payload = copy.deepcopy(base)
    new_id = uuid.uuid4().hex
    new_payload["listing_id"] = new_id
    new_payload["parent_listing_id"] = listing_id
    new_payload["version"] = int(base.get("version") or 1) + 1

    allowed = {
        "title",
        "bullets",
        "description",
        "search_terms",
        "a_plus_outline",
        "pending_confirmations",
    }
    unknown = set(overrides) - allowed
    if unknown:
        raise ListingError(f"不支持修改的字段：{', '.join(sorted(unknown))}")

    changed = False
    for field in allowed & set(overrides):
        value = overrides[field]
        if field == "title":
            if not str(value or "").strip():
                raise ListingError("标题不能为空")
            value = str(value).strip()
        if field == "bullets":
            if not isinstance(value, list) or not value:
                raise ListingError("bullets 必须是非空数组")
            normalized = []
            for index, bullet in enumerate(value, start=1):
                if not isinstance(bullet, dict) or not bullet.get("headline"):
                    raise ListingError(f"第 {index} 条五点缺少 headline")
                headline = str(bullet.get("headline") or "").strip()
                body = str(bullet.get("body") or "").strip()
                normalized.append(
                    {
                        "headline": headline,
                        "body": body,
                        "character_count": char_len(headline + body),
                        "supporting_facts": bullet.get("supporting_facts") or [],
                    }
                )
            value = normalized
        if new_payload.get(field) != value:
            changed = True
        new_payload[field] = value

    if not changed:
        raise ListingError("没有实际修改，未派生新版本")

    new_payload["edited_after_generation"] = True
    snapshot = new_payload.get("product_snapshot")
    if snapshot:
        product = OwnProduct(**snapshot)
        draft = ListingDraft(**new_payload)
        new_payload["quality_check"] = _quality(product, draft)

    db.save_listing(
        new_payload,
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        version=new_payload["version"],
        parent_listing_id=listing_id,
    )
    return new_payload


def _text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def diff(
    db: Database, ctx: TenantContext, listing_id: str, against_id: str | None = None
) -> dict[str, Any]:
    target = _load(db, ctx, listing_id)
    base_id = against_id or target.get("parent_listing_id")
    if not base_id:
        raise ListingError("该草稿没有父版本，无法比较；请指定 against")
    base = _load(db, ctx, str(base_id))

    fields = [
        ("title", "标题"),
        ("bullets", "五点"),
        ("description", "描述"),
        ("search_terms", "Search Terms"),
    ]
    changes: list[dict[str, Any]] = []
    for key, label in fields:
        old_text = _text_of(base.get(key))
        new_text = _text_of(target.get(key))
        changes.append(
            {
                "field": key,
                "label": label,
                "changed": old_text != new_text,
                "old": base.get(key),
                "new": target.get(key),
            }
        )
    unified = difflib.unified_diff(
        _text_of(base).splitlines(),
        _text_of(target).splitlines(),
        fromfile=f"v{base.get('version', 1)}",
        tofile=f"v{target.get('version', 1)}",
        lineterm="",
    )
    return {
        "base": {
            "listing_id": base.get("listing_id"),
            "version": base.get("version", 1),
            "title": base.get("title", ""),
        },
        "target": {
            "listing_id": target.get("listing_id"),
            "version": target.get("version", 1),
            "title": target.get("title", ""),
        },
        "fields": changes,
        "unified_diff": list(unified),
        "changed_fields": [c["field"] for c in changes if c["changed"]],
    }


def export_listing(
    listing: dict[str, Any], fmt: str = "md"
) -> tuple[str, str, str]:
    normalized = (fmt or "md").lower()
    stem = (listing.get("product_name") or "listing").replace("/", "-")[:40]
    filename = f"{stem}-{listing.get('listing_id') or 'listing'}.{normalized}"
    if normalized in {"json"}:
        return filename, json.dumps(listing, ensure_ascii=False, indent=2), "application/json; charset=utf-8"
    if normalized in {"md", "markdown"}:
        return filename, _listing_markdown(listing), "text/markdown; charset=utf-8"
    if normalized in {"txt", "text"}:
        return filename, _listing_text(listing), "text/plain; charset=utf-8"
    raise ListingError(f"不支持的导出格式：{fmt}（可选 md / json / txt）")


def _listing_markdown(listing: dict[str, Any]) -> str:
    lines = [f"# {listing.get('title') or listing.get('product_name') or 'Listing'}", ""]
    lines.append(f"- 商品：{listing.get('product_name', '—')}")
    lines.append(
        f"- 平台/站点/语言：{listing.get('platform', '—')} / "
        f"{listing.get('marketplace', '—')} / {listing.get('language', '—')}"
    )
    lines.append(f"- 版本：v{listing.get('version', 1)}")
    lines.append(f"- 引擎：{listing.get('engine', '—')}")
    lines.append(f"- 关联报告：{listing.get('analysis_report_id') or '—'}")
    lines.append("")
    lines.append("## 五点描述")
    lines.append("")
    for index, bullet in enumerate(listing.get("bullets") or [], start=1):
        lines.append(f"{index}. **{bullet.get('headline', '')}** — {bullet.get('body', '')}")
    lines.append("")
    lines.append("## 描述")
    lines.append("")
    lines.append(listing.get("description") or "—")
    lines.append("")
    lines.append("## Search Terms")
    lines.append("")
    lines.append(listing.get("search_terms") or "—")
    lines.append("")
    quality = listing.get("quality_check") or {}
    lines.append("## 质检")
    lines.append("")
    lines.append(f"通过：{'是' if quality.get('passed') else '否'}")
    for issue in quality.get("issues") or []:
        lines.append(
            f"- [{issue.get('severity')}] {issue.get('code')}: {issue.get('message')}"
        )
    pending = listing.get("pending_confirmations") or []
    if pending:
        lines.append("")
        lines.append("## 待确认")
        lines.append("")
        for item in pending:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _listing_text(listing: dict[str, Any]) -> str:
    lines = [listing.get("title") or ""]
    for bullet in listing.get("bullets") or []:
        lines.append(f"{bullet.get('headline', '')} - {bullet.get('body', '')}")
    lines.append("")
    lines.append(listing.get("description") or "")
    lines.append("")
    lines.append(f"Search Terms: {listing.get('search_terms') or ''}")
    return "\n".join(lines)


__all__ = [
    "ListingError",
    "ListingNotFound",
    "ListingSnapshotMissing",
    "create_version",
    "diff",
    "dump_for_storage",
    "export_listing",
    "generate",
    "recheck",
]
