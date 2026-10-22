"""导入与校验测试：CSV 正常/异常、JSON、Excel、API 上传。"""

from __future__ import annotations

import io
import json

import pytest

from crosspilot.ingest.importers import (
    ImportValidationError,
    import_competitor_data,
    load_csv_rows,
)


VALID_CSV = """name,brand,price,rating,review_count,key_features,specifications,review_text,review_rating,is_demo
Bottle A,BrandA,19.99,4.2,120,Leak-proof lid|Dishwasher safe,容量:500ml,The lid leaked after a week.,2,true
Bottle B,BrandB,29.50,4.5,80,Insulated,容量:750ml,Keeps water cold all day.,5,true
"""


def test_csv_import_success():
    result = import_competitor_data(VALID_CSV, "competitors.csv")
    assert result.ok
    assert len(result.competitors) == 2
    first = result.competitors[0]
    assert first.name == "Bottle A"
    assert first.price == 19.99
    assert first.rating == 4.2
    assert first.key_features == ["Leak-proof lid", "Dishwasher safe"]
    assert first.specifications["容量"] == "500ml"
    assert len(first.reviews) == 1
    assert first.reviews[0].rating == 2
    assert first.is_demo is True
    # 未在文件里出现的字段保持 None，不推断
    assert first.asin is None


def test_csv_missing_required_column_raises_clear_error():
    bad = "brand,price\nBrandA,19.99\n"
    with pytest.raises(ImportValidationError) as excinfo:
        import_competitor_data(bad, "bad.csv")
    assert "name" in str(excinfo.value)
    assert "商品名称" in str(excinfo.value)


def test_csv_row_with_missing_name_reports_row_number():
    bad = "name,brand,price\n,BrandA,19.99\nBottle B,BrandB,20\n"
    result = import_competitor_data(bad, "partial.csv")
    assert len(result.competitors) == 1
    assert result.errors
    error = result.errors[0]
    assert error.row == 2
    # 解析层保留原始字段名与英文契约之外的细节，翻译只发生在接口边界
    assert error.field == "name"
    assert error.message == "缺少商品名称"


def test_csv_invalid_numeric_reports_field():
    bad = "name,price\nBottle A,not-a-number\n"
    result = import_competitor_data(bad, "bad_price.csv")
    assert result.errors
    assert result.errors[0].field == "price"
    assert "不是合法数字" in result.errors[0].message


def test_csv_negative_price_rejected():
    bad = "name,price\nBottle A,-3\n"
    result = import_competitor_data(bad, "negative.csv")
    assert result.errors[0].field == "price"
    assert "负数" in result.errors[0].message


def test_csv_out_of_range_rating_rejected():
    bad = "name,rating\nBottle A,9\n"
    result = import_competitor_data(bad, "rating.csv")
    assert result.errors[0].field == "rating"


def test_csv_utf8_bom_and_chinese_headers():
    csv_text = "\ufeff商品名称,品牌,价格,评论内容,评论星级\n竞品甲,某品牌,88,质量很好,5\n"
    result = import_competitor_data(csv_text, "cn.csv")
    assert result.ok
    assert result.competitors[0].name == "竞品甲"
    assert result.competitors[0].reviews[0].text == "质量很好"


def test_json_import_with_keywords():
    payload = {
        "competitors": [
            {"name": "J1", "price": 10, "reviews": [{"rating": 1, "text": "bad smell"}]}
        ],
        "keywords": [
            {"keyword": "bottle", "search_volume": 1000, "rank": 3},
            {"keyword": "tumbler"},
        ],
    }
    result = import_competitor_data(json.dumps(payload), "data.json")
    assert result.source_format == "json"
    assert len(result.competitors) == 1
    assert len(result.keywords) == 2
    assert result.keywords[0].search_volume == 1000
    assert result.keywords[1].has_metrics is False


def test_json_invalid_reports_line_and_column():
    with pytest.raises(ImportValidationError) as excinfo:
        import_competitor_data("{not json", "x.json")
    assert "格式不对" in str(excinfo.value)
    assert "第 1 行" in str(excinfo.value)


def test_json_without_competitors_key_raises():
    with pytest.raises(ImportValidationError):
        import_competitor_data('{"items": []}', "x.json")


def test_unsupported_extension_raises():
    with pytest.raises(ImportValidationError) as excinfo:
        import_competitor_data("a,b", "data.txt")
    assert "不支持的文件类型" in str(excinfo.value)


def test_csv_duplicate_headers_warned():
    csv_text = "name,price,price\nBottle A,10,20\n"
    rows, errors = load_csv_rows(csv_text)
    assert errors and errors[0].field == "header"


def test_csv_multi_row_same_product_merges_reviews():
    """常见写法：同一竞品多行，每行一条评论，应合并为一个竞品。"""
    csv_text = (
        "name,brand,price,key_features,review_text,review_rating\n"
        "Bottle A,BrandA,19.99,Leak-proof lid,Lid leaked in my bag,2\n"
        "Bottle A,BrandA,19.99,Leak-proof lid,Very easy to clean,5\n"
        "Bottle A,BrandA,19.99,Insulated,Keeps water cold,4\n"
        "Bottle B,BrandB,29.50,Durable,Works well,5\n"
    )
    result = import_competitor_data(csv_text, "merged.csv")
    assert len(result.competitors) == 2
    first = result.competitors[0]
    assert first.name == "Bottle A"
    assert len(first.reviews) == 3
    assert first.key_features == ["Leak-proof lid", "Insulated"]
    assert first.price == 19.99
    assert any("合并" in w for w in result.warnings)


def test_json_duplicate_names_also_merged():
    payload = [
        {"name": "Same", "price": 10, "reviews": [{"text": "a"}]},
        {"name": "same", "reviews": [{"text": "b"}]},
    ]
    result = import_competitor_data(json.dumps(payload), "dup.json")
    assert len(result.competitors) == 1
    assert len(result.competitors[0].reviews) == 2
    # 缺失字段从第二行补齐
    assert result.competitors[0].price == 10


def test_merge_keeps_distinct_asins_apart():
    payload = [
        {"name": "Same Name", "asin": "A1", "reviews": [{"text": "a"}]},
        {"name": "Same Name", "asin": "A2", "reviews": [{"text": "b"}]},
    ]
    result = import_competitor_data(json.dumps(payload), "asin.json")
    assert len(result.competitors) == 2


def test_excel_import_roundtrip(tmp_path):
    pytest.importorskip("openpyxl")
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["name", "brand", "price", "key_features", "review_text"])
    sheet.append(["XLSX Bottle", "BrandX", 12.5, "Durable|Leak-proof", "Works great"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    result = import_competitor_data(buffer.getvalue(), "data.xlsx")
    assert result.ok
    assert result.competitors[0].name == "XLSX Bottle"
    assert result.competitors[0].key_features == ["Durable", "Leak-proof"]
    assert result.competitors[0].reviews[0].text == "Works great"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_import_endpoint(auth_client):
    response = auth_client.post(
        "/api/import",
        files={"file": ("competitors.csv", VALID_CSV.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["competitors"]) == 2
    assert data["source_format"] == "csv"


def test_api_import_endpoint_returns_structured_errors(auth_client):
    bad = "name,price\n,19.99\n"
    response = auth_client.post(
        "/api/import",
        files={"file": ("bad.csv", bad.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["errors"]
    assert data["errors"][0]["field"] == "商品名称"


def test_api_import_missing_column_returns_422(auth_client):
    response = auth_client.post(
        "/api/import",
        files={"file": ("bad.csv", b"brand,price\nA,1\n", "text/csv")},
    )
    assert response.status_code == 422
    assert "商品名称" in json.dumps(response.json(), ensure_ascii=False)
