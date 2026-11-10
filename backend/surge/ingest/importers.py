"""竞品数据导入：CSV / JSON / Excel，带字段校验与清晰错误。

设计原则：
- 校验失败返回**逐行错误**（行号、字段、原因），而不是一句 "invalid file"；
- 缺失的非必填字段保持 None，不做任何推断补全；
- 导入结果始终标记 ``is_demo``，除 CSV/JSON 中显式声明 ``is_demo=false``。
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from ..labels import humanize_message
from ..models import CompetitorProduct, KeywordMetric, ReviewSample

MAX_REVIEWS_PER_COMPETITOR = 500

# CSV 列名 -> 规范化字段（同时接受中英文表头与小写变体）
COLUMN_ALIASES: dict[str, str] = {
    "name": "name",
    "商品名称": "name",
    "竞品名称": "name",
    "product": "name",
    "product_name": "name",
    "title": "name",
    "brand": "brand",
    "品牌": "brand",
    "asin": "asin",
    "price": "price",
    "价格": "price",
    "currency": "currency",
    "币种": "currency",
    "rating": "rating",
    "评分": "rating",
    "stars": "rating",
    "review_count": "review_count",
    "评论数": "review_count",
    "reviews": "review_count",
    "category": "category",
    "类目": "category",
    "key_features": "key_features",
    "features": "key_features",
    "卖点": "key_features",
    "核心卖点": "key_features",
    "specifications": "specifications",
    "specs": "specifications",
    "规格": "specifications",
    "review_text": "review_text",
    "review": "review_text",
    "reviews_text": "review_text",
    "评论": "review_text",
    "评论内容": "review_text",
    "review_rating": "review_rating",
    "评论星级": "review_rating",
    "review_title": "review_title",
    "评论标题": "review_title",
    "review_date": "review_date",
    "评论日期": "review_date",
    "reviews": "review_list",
    "review_list": "review_list",
    "review_samples": "review_list",
    "评论列表": "review_list",
    "is_demo": "is_demo",
    "source_ref": "source_ref",
    "数据来源": "source_ref",
}

REQUIRED_FIELDS = ("name",)
NON_NEGATIVE_NUMERIC = ("price", "review_count")
RATING_RANGE = (0.0, 5.0)

KEYWORD_ALIASES: dict[str, str] = {
    "keyword": "keyword",
    "关键词": "keyword",
    "term": "keyword",
    "search_volume": "search_volume",
    "搜索量": "search_volume",
    "volume": "search_volume",
    "rank": "rank",
    "排名": "rank",
    "relevance": "relevance",
    "相关性": "relevance",
    "competition": "competition",
    "竞争度": "competition",
    "conversion_share": "conversion_share",
    "转化占比": "conversion_share",
    "source": "source",
    "来源": "source",
}


@dataclass
class RowError:
    row: int
    field: str
    message: str
    value: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {"row": self.row, "field": self.field, "message": self.message, "value": self.value}


@dataclass
class ImportResult:
    """导入结果：成功条目 + 结构化错误 + 数据来源说明。"""

    competitors: list[CompetitorProduct] = field(default_factory=list)
    keywords: list[KeywordMetric] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_format: str = ""
    source_name: str = ""
    total_rows: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.competitors) and not self.errors

    def raise_if_failed(self) -> None:
        if not self.competitors:
            detail = "；".join(
                f"第{e.row}行 {e.field}: {e.message}" for e in self.errors[:5]
            ) or "文件中没有可用数据"
            raise ImportValidationError(f"导入失败：{detail}", errors=self.errors)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "source_format": self.source_format,
            "source_name": self.source_name,
            "total_rows": self.total_rows,
            "competitors": [c.model_dump(mode="json") for c in self.competitors],
            "keywords": [k.model_dump(mode="json") for k in self.keywords],
            "errors": [e.as_dict() for e in self.errors],
            "warnings": self.warnings,
        }


class ImportValidationError(ValueError):
    def __init__(self, message: str, errors: list[RowError] | None = None):
        super().__init__(message)
        self.errors = errors or []


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _normalize_header(header: str, mapping: dict[str, str] | None = None) -> str:
    key = (header or "").strip().lower().replace(" ", "_").replace("-", "_")
    if mapping:
        normalized_mapping = {
            str(k).strip().lower().replace(" ", "_").replace("-", "_"): str(v).strip()
            for k, v in mapping.items()
            if str(v).strip()
        }
        if key in normalized_mapping:
            return normalized_mapping[key]
    return COLUMN_ALIASES.get(key, key)


def detect_file_columns(
    content: str | bytes, filename: str
) -> tuple[list[dict[str, Any]], list[RowError]]:
    """返回文件的列与识别结果，供导入预览的字段映射面板使用。

    只做识别，不校验数据；无法识别的列会保持 ``field=None``，由用户显式映射。
    """
    suffix = Path(filename).suffix.lower()
    headers: list[str] = []
    if suffix == ".csv":
        text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
        reader = csv.reader(io.StringIO(text.lstrip("\ufeff")))
        try:
            headers = [h for h in next(reader)]
        except StopIteration:
            return [], [RowError(row=1, field="file", message="文件为空")]
    elif suffix == ".json":
        text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return [], [
                RowError(
                    row=1,
                    field="file",
                    message="这个 JSON 文件格式不对，请检查括号、引号与逗号是否完整",
                )
            ]
        first: dict[str, Any] = {}
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            first = payload[0]
        elif isinstance(payload, dict):
            items = payload.get("competitors") or payload.get("products") or []
            if isinstance(items, list) and items and isinstance(items[0], dict):
                first = items[0]
        headers = list(first.keys())
    elif suffix == ".xlsx":
        try:
            from openpyxl import load_workbook  # type: ignore

            data = content if isinstance(content, bytes) else content.encode("utf-8")
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            header_row = next(workbook.active.iter_rows(values_only=True))
            headers = [str(h) if h is not None else "" for h in header_row]
        except Exception:  # noqa: BLE001 - 预览失败给出可读原因
            return [], [
                RowError(
                    row=1,
                    field="file",
                    message="这个 Excel 文件打不开。如果设了密码，请先取消保护再上传",
                )
            ]
    else:
        return [], [
            RowError(
                row=1,
                field="file",
                message=f"暂不支持 {suffix} 格式，请用 .csv / .json / .xlsx",
            )
        ]

    columns: list[dict[str, Any]] = []
    for raw in headers:
        if not (raw or "").strip():
            continue
        canonical = _normalize_header(raw)
        columns.append(
            {
                "source": raw,
                "field": canonical if canonical in set(COLUMN_ALIASES.values()) else None,
                "required": canonical == "name",
                "recognized": canonical in set(COLUMN_ALIASES.values()),
            }
        )
    return columns, []


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    text = str(value).strip().replace(",", "").replace("$", "")
    return float(text)


def _parse_int(value: Any) -> int | None:
    parsed = _parse_float(value)
    return None if parsed is None else int(parsed)


def _parse_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "是"}:
        return True
    if text in {"0", "false", "no", "n", "否"}:
        return False
    raise ValueError(f"无法解析为布尔值: {value!r}")


def _parse_specs(value: Any) -> dict[str, str]:
    """支持 ``颜色:黑色|容量:500ml``、JSON 字符串或 dict。"""
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    text = str(value).strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            pass
    specs: dict[str, str] = {}
    for chunk in text.replace("；", ";").replace("；", ";").split(";"):
        for part in [chunk]:
            if ":" in part:
                key, _, val = part.partition(":")
            elif "：" in part:
                key, _, val = part.partition("：")
            else:
                continue
            key, val = key.strip(), val.strip()
            if key and val:
                specs[key] = val
    if not specs:
        # 也允许 ``key=value|other=value`` 形式
        for part in text.split("|"):
            if "=" in part:
                key, _, val = part.partition("=")
                specs[key.strip()] = val.strip()
    return specs


def _row_to_competitor(row: dict[str, Any], row_number: int, errors: list[RowError]) -> CompetitorProduct | None:
    data: dict[str, Any] = {}
    local_errors: list[RowError] = []

    def fail(field_name: str, message: str, value: Any = None) -> None:
        local_errors.append(RowError(row=row_number, field=field_name, message=message, value=value))

    name = (row.get("name") or "").strip() if isinstance(row.get("name"), str) else row.get("name")
    if not name:
        fail("name", "缺少商品名称")
    else:
        data["name"] = name

    for field_name in ("brand", "asin", "category", "source_ref", "currency"):
        value = row.get(field_name)
        if value is not None and str(value).strip() != "":
            data[field_name] = str(value).strip()

    if "price" in row and row.get("price") not in (None, ""):
        try:
            price = _parse_float(row.get("price"))
            if price is not None and price < 0:
                fail("price", "价格不能为负数", row.get("price"))
            else:
                data["price"] = price
        except (TypeError, ValueError):
            fail("price", f"价格不是合法数字: {row.get('price')!r}", row.get("price"))

    if "rating" in row and row.get("rating") not in (None, ""):
        try:
            rating = _parse_float(row.get("rating"))
            if rating is None:
                pass
            elif not (RATING_RANGE[0] <= rating <= RATING_RANGE[1]):
                fail("rating", f"评分必须在 {RATING_RANGE[0]}-{RATING_RANGE[1]} 之间", row.get("rating"))
            else:
                data["rating"] = rating
        except (TypeError, ValueError):
            fail("rating", f"评分不是合法数字: {row.get('rating')!r}", row.get("rating"))

    if "review_count" in row and row.get("review_count") not in (None, ""):
        try:
            count = _parse_int(row.get("review_count"))
            if count is not None and count < 0:
                fail("review_count", "评论数不能为负数", row.get("review_count"))
            else:
                data["review_count"] = count
        except (TypeError, ValueError):
            fail("review_count", f"评论数不是合法整数: {row.get('review_count')!r}", row.get("review_count"))

    if "is_demo" in row and row.get("is_demo") not in (None, ""):
        try:
            parsed = _parse_bool(row.get("is_demo"))
            if parsed is not None:
                data["is_demo"] = parsed
        except ValueError as exc:
            fail("is_demo", str(exc), row.get("is_demo"))

    # 规格
    if row.get("specifications") not in (None, ""):
        try:
            data["specifications"] = _parse_specs(row.get("specifications"))
        except Exception as exc:  # pragma: no cover - 防御性
            fail("specifications", "规格没能读出来，请用「键：值」或「键=值|键=值」的写法", row.get("specifications"))

    # 卖点 / 评论：来自 load_rows 的中间表示
    features = row.get("key_features")
    if isinstance(features, list):
        data["key_features"] = [str(f).strip() for f in features if str(f).strip()]

    reviews = row.get("review_list")
    if isinstance(reviews, list):
        parsed_reviews: list[ReviewSample] = []
        for index, review in enumerate(reviews):
            if isinstance(review, str):
                text = review.strip()
                if text:
                    parsed_reviews.append(ReviewSample(text=text, source="import"))
            elif isinstance(review, dict):
                try:
                    parsed_reviews.append(ReviewSample(**review))
                except ValidationError as exc:
                    first = exc.errors()[0] if exc.errors() else {}
                    fail(
                        f"review_list[{index}]",
                        "这条评论样本填得不对：" + humanize_message(
                            str(first.get("msg") or ""), str(first.get("type") or "")
                        ),
                        review,
                    )
        if len(parsed_reviews) > MAX_REVIEWS_PER_COMPETITOR:
            local_errors.append(
                RowError(
                    row=row_number,
                    field="review_list",
                    message=f"评论样本超过上限 {MAX_REVIEWS_PER_COMPETITOR}，已截断",
                )
            )
            parsed_reviews = parsed_reviews[:MAX_REVIEWS_PER_COMPETITOR]
        data["reviews"] = parsed_reviews

    errors.extend(local_errors)
    if any(e.field == "name" for e in local_errors):
        return None
    try:
        return CompetitorProduct(**data)
    except ValidationError as exc:
        for err in exc.errors():
            field_name = ".".join(str(p) for p in err.get("loc", ())) or "row"
            errors.append(
                RowError(
                    row=row_number,
                    field=field_name,
                    message=humanize_message(err.get("msg", ""), err.get("type", "")),
                )
            )
        return None


# ---------------------------------------------------------------------------
# 格式解析
# ---------------------------------------------------------------------------


def load_csv_rows(
    content: str, column_mapping: dict[str, str] | None = None
) -> tuple[list[dict[str, Any]], list[RowError]]:
    """解析 CSV 为中间行（表头已规范化，评论列已合并）。"""
    errors: list[RowError] = []
    text = content.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ImportValidationError("CSV 文件没有表头")
    normalized = [_normalize_header(h, column_mapping) for h in reader.fieldnames]
    duplicates = {h for h in normalized if normalized.count(h) > 1}
    if "name" not in normalized:
        raise ImportValidationError(
            "CSV 缺少必需列 name（商品名称）。可用列名: "
            + ", ".join(dict.fromkeys(normalized))
        )

    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(reader, start=2):  # 第 1 行是表头
        if raw is None or all((v is None or str(v).strip() == "") for v in raw.values()):
            continue
        mapped: dict[str, Any] = {}
        features: list[str] = []
        review_texts: list[str] = []
        review_ratings: list[str] = []
        review_titles: list[str] = []
        review_dates: list[str] = []
        for original_header, normalized_key in zip(reader.fieldnames, normalized):
            value = raw.get(original_header)
            if value is None:
                continue
            value = value.strip()
            if value == "":
                continue
            if normalized_key == "key_features":
                features.extend(p.strip() for p in value.split("|") if p.strip())
            elif normalized_key == "review_text":
                review_texts.append(value)
            elif normalized_key == "review_rating":
                review_ratings.append(value)
            elif normalized_key == "review_title":
                review_titles.append(value)
            elif normalized_key == "review_date":
                review_dates.append(value)
            elif normalized_key in mapped:
                mapped[normalized_key] = f"{mapped[normalized_key]}|{value}"
            else:
                mapped[normalized_key] = value

        if features:
            mapped["key_features"] = features
        if review_texts:
            review_list: list[dict[str, Any]] = []
            for i, review_text in enumerate(review_texts):
                review: dict[str, Any] = {"text": review_text, "source": "csv_import"}
                if i < len(review_ratings) and review_ratings[i]:
                    review["rating"] = review_ratings[i]
                if i < len(review_titles) and review_titles[i]:
                    review["title"] = review_titles[i]
                if i < len(review_dates) and review_dates[i]:
                    review["date"] = review_dates[i]
                review_list.append(review)
            mapped["review_list"] = review_list
        mapped["_row"] = index
        rows.append(mapped)

    if duplicates:
        errors.append(
            RowError(row=1, field="header", message=f"存在重复列: {', '.join(sorted(duplicates))}")
        )
    if not rows:
        raise ImportValidationError("CSV 中没有数据行")
    return rows, errors


def load_json_rows(content: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[RowError]]:
    """解析 JSON，返回 (竞品行, 关键词行, 错误)。"""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ImportValidationError(
            f"这个 JSON 文件第 {exc.lineno} 行第 {exc.colno} 列格式不对，"
            "请检查那附近的括号、引号与逗号"
        ) from exc

    errors: list[RowError] = []
    if isinstance(payload, list):
        competitors_raw = payload
        keywords_raw: list[Any] = []
    elif isinstance(payload, dict):
        competitors_raw = payload.get("competitors") or payload.get("products")
        keywords_raw = payload.get("keywords") or []
        if competitors_raw is None:
            raise ImportValidationError("JSON 对象必须包含 competitors 数组（或直接使用顶层数组）")
        if not isinstance(competitors_raw, list):
            raise ImportValidationError("competitors 必须是数组")
        if not isinstance(keywords_raw, list):
            raise ImportValidationError("keywords 必须是数组")
    else:
        raise ImportValidationError("JSON 根节点必须是对象或数组")

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(competitors_raw, start=1):
        if not isinstance(item, dict):
            errors.append(RowError(row=index, field="competitor", message="每个竞品必须是 JSON 对象"))
            continue
        mapped: dict[str, Any] = {}
        for key, value in item.items():
            normalized_key = _normalize_header(key)
            if normalized_key == "reviews" or normalized_key == "review_list":
                mapped["review_list"] = value
            elif normalized_key == "key_features":
                if isinstance(value, str):
                    mapped["key_features"] = [p.strip() for p in value.split("|") if p.strip()]
                else:
                    mapped["key_features"] = value
            elif normalized_key == "specifications":
                mapped["specifications"] = value
            elif normalized_key not in mapped:
                mapped[normalized_key] = value
        mapped["_row"] = index
        rows.append(mapped)

    keyword_rows: list[dict[str, Any]] = []
    for index, item in enumerate(keywords_raw, start=1):
        if isinstance(item, str):
            keyword_rows.append({"keyword": item, "_row": index})
        elif isinstance(item, dict):
            mapped_k = {KEYWORD_ALIASES.get(str(k).strip().lower(), str(k)): v for k, v in item.items()}
            mapped_k["_row"] = index
            keyword_rows.append(mapped_k)
        else:
            errors.append(RowError(row=index, field="keywords", message="关键词必须是字符串或对象"))
    return rows, keyword_rows, errors


def load_excel_rows(
    data: bytes, column_mapping: dict[str, str] | None = None
) -> tuple[list[dict[str, Any]], list[RowError]]:
    """解析 Excel（.xlsx）。openpyxl 缺失时给出可操作的错误。"""
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError as exc:  # pragma: no cover - 取决于环境
        raise ImportValidationError(
            "Excel 导入需要 openpyxl，请执行: pip install openpyxl"
        ) from exc

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.active
    rows_iter: Iterable[tuple[Any, ...]] = sheet.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration as exc:
        raise ImportValidationError("Excel 文件为空") from exc
    headers = [
        _normalize_header(str(h), column_mapping) if h is not None else "" for h in header
    ]
    if "name" not in headers:
        raise ImportValidationError(
            "Excel 缺少必需列 name（商品名称）。可用列名: " + ", ".join(dict.fromkeys(headers))
        )
    errors: list[RowError] = []
    rows: list[dict[str, Any]] = []
    for index, values in enumerate(rows_iter, start=2):
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            continue
        mapped: dict[str, Any] = {}
        features: list[str] = []
        reviews: list[str] = []
        for header_name, value in zip(headers, values):
            if value is None or str(value).strip() == "" or not header_name:
                continue
            text = str(value).strip()
            if header_name == "key_features":
                features.extend(p.strip() for p in text.split("|") if p.strip())
            elif header_name == "review_text":
                reviews.append(text)
            elif header_name not in mapped:
                mapped[header_name] = value
        if features:
            mapped["key_features"] = features
        if reviews:
            mapped["review_list"] = [{"text": r, "source": "excel_import"} for r in reviews]
        mapped["_row"] = index
        rows.append(mapped)
    if not rows:
        raise ImportValidationError("Excel 中没有数据行")
    return rows, errors


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------


def _build_keywords(rows: list[dict[str, Any]], offset_row_base: int = 1) -> tuple[list[KeywordMetric], list[RowError]]:
    keywords: list[KeywordMetric] = []
    errors: list[RowError] = []
    for index, row in enumerate(rows, start=offset_row_base):
        row_number = int(row.pop("_row", index) or index)
        try:
            keywords.append(KeywordMetric(**row))
        except ValidationError as exc:
            for err in exc.errors():
                field_name = ".".join(str(p) for p in err.get("loc", ())) or "keyword"
                errors.append(
                    RowError(
                        row=row_number,
                        field=field_name,
                        message=humanize_message(err.get("msg", ""), err.get("type", "")),
                    )
                )
    return keywords, errors


def import_competitor_data(
    content: str | bytes,
    filename: str,
    *,
    allow_single_failed_rows: bool = True,
    column_mapping: dict[str, str] | None = None,
) -> ImportResult:
    """按扩展名分派解析。支持 .csv / .json / .xlsx。"""
    suffix = Path(filename).suffix.lower()
    result = ImportResult(source_name=filename)

    if isinstance(content, bytes):
        if suffix == ".xlsx":
            rows, errors = load_excel_rows(content, column_mapping)
            result.source_format = "xlsx"
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ImportValidationError(
                    "文件不是 UTF-8 编码，请另存为 UTF-8 后重试"
                ) from exc
            return import_competitor_data(
                text,
                filename,
                allow_single_failed_rows=allow_single_failed_rows,
                column_mapping=column_mapping,
            )
    else:
        text = content
        if suffix == ".json":
            rows, keyword_rows, errors = load_json_rows(text)
            result.source_format = "json"
            keywords, keyword_errors = _build_keywords(keyword_rows)
            result.keywords = keywords
            errors.extend(keyword_errors)
        elif suffix == ".csv":
            rows, errors = load_csv_rows(text, column_mapping)
            result.source_format = "csv"
        elif suffix == ".xlsx":
            raise ImportValidationError("Excel 文件请以二进制方式上传（endpoint 使用 UploadFile）")
        else:
            raise ImportValidationError(
                f"不支持的文件类型 {suffix or '(无扩展名)'}，仅支持 .csv / .json / .xlsx"
            )

    result.total_rows = len(rows)
    for row in rows:
        competitor = _row_to_competitor(row, int(row.get("_row", 0) or 0), result.errors)
        if competitor is not None:
            result.competitors.append(competitor)

    result.competitors = merge_duplicate_competitors(result.competitors, result.warnings)

    if not result.competitors and result.errors:
        first = result.errors[0]
        result.warnings.append(f"没有任何有效竞品行；首个错误位于第 {first.row} 行 {first.field}")
    if result.errors and allow_single_failed_rows:
        result.warnings.append(
            f"{len(result.errors)} 处数据校验错误；有效竞品 {len(result.competitors)} 个"
        )
    if result.keywords:
        without_metrics = sum(1 for k in result.keywords if not k.has_metrics)
        if without_metrics:
            result.warnings.append(
                f"{without_metrics} 个关键词没有搜索量/排名等指标，报告只列出关键词，不计算机会分"
            )
    return result


def merge_duplicate_competitors(
    competitors: list[CompetitorProduct],
    warnings: list[str] | None = None,
) -> list[CompetitorProduct]:
    """合并同名竞品。

    CSV/Excel 常用「同一个竞品写多行、每行一条评论」的方式表达多条评论，
    这里按 ``asin``（若有）或规范化名称合并：评论拼接、卖点取并集、
    其余字段保留首个非空值。合并会写入警告，避免静默改变数据形状。
    """
    merged: dict[str, CompetitorProduct] = {}
    key_order: list[str] = []
    for competitor in competitors:
        key = (competitor.asin or competitor.name).strip().lower()
        if key not in merged:
            merged[key] = competitor
            key_order.append(key)
            continue
        base = merged[key]
        features = list(dict.fromkeys(base.key_features + competitor.key_features))
        specs = {**competitor.specifications, **base.specifications}
        reviews = base.reviews + competitor.reviews
        update: dict[str, Any] = {
            "key_features": features,
            "specifications": specs,
            "reviews": reviews,
        }
        for attr in ("brand", "price", "rating", "review_count", "category", "source_ref"):
            if getattr(base, attr) is None and getattr(competitor, attr) is not None:
                update[attr] = getattr(competitor, attr)
        merged[key] = base.model_copy(update=update)

    result = [merged[key] for key in key_order]
    if warnings is not None and len(result) != len(competitors):
        result_names = "、".join(c.name for c in result)
        warnings.append(
            f"检测到同名多行记录，已按名称/ASIN 合并为 {len(result)} 个竞品（{result_names}），"
            "评论与卖点已合并"
        )
    return result


def import_result_to_request_payload(result: ImportResult) -> dict[str, Any]:
    """把导入结果转成可直接提交给分析接口的竞品字段。"""
    return {
        "competitors": [c.model_dump(mode="json") for c in result.competitors],
        "keywords": [k.model_dump(mode="json") for k in result.keywords],
    }


__all__ = [
    "COLUMN_ALIASES",
    "ImportResult",
    "ImportValidationError",
    "KEYWORD_ALIASES",
    "MAX_REVIEWS_PER_COMPETITOR",
    "REQUIRED_FIELDS",
    "RowError",
    "detect_file_columns",
    "import_competitor_data",
    "import_result_to_request_payload",
    "load_csv_rows",
    "load_excel_rows",
    "load_json_rows",
    "merge_duplicate_competitors",
]
