---
name: crosspilot-listing
description: 'Use when the user asks for Amazon/eBay listing copy, competitor analysis, review pain-point mining, or keyword opportunity work for a cross-border e-commerce product. Calls the local CrossPilot service (fastapi) over HTTP to produce an evidence-graded competitor report and a fact-grounded listing, and returns the structured result without inventing specs, certifications, search volume, or rankings.'
---

# CrossPilot：跨境电商竞品分析与 Listing 生成

本 Skill 把用户请求转成对 **本地 CrossPilot 服务**的调用。CrossPilot 是独立 Python
服务，默认运行在 `http://127.0.0.1:8123`，业务逻辑不依赖 Harness 内核。

## 硬性约束（不可违反）

1. **不得编造商品事实**。文案中的规格、材质、认证、尺寸、容量只能来自用户提供的资料；
   缺失项必须保留为「待确认」，不得自行补全成具体数值。
2. **不得编造关键词指标**。没有搜索量/排名数据时，只说"无数据"，不估算、不填充数字。
3. **所有模拟数据必须标注 demo**。若用户使用内置示例，最终回答必须明确说明这是
   虚构演示数据，不是真实 Amazon 商品、销量或排名。
4. **不得声称已完全合规**。平台规则来自可配置示例文件，未经最新政策核验。
5. 结论要区分事实、统计、推断；引用评论时尽量附原文片段。

## 前置检查

1. 确认服务在线：

   ```powershell
   Invoke-RestMethod http://127.0.0.1:8123/api/health
   ```

   若失败，先在工作区 `backend` 目录启动（`$env:PYTHONPATH='.'; python -m crosspilot serve --port 8123`），
   或询问用户是否允许启动。**不要**改成在 Harness 安装目录里找代码。

2. 取演示数据（仅在用户没有提供真实数据时使用）：

   ```powershell
   Invoke-RestMethod http://127.0.0.1:8123/api/demo/dataset
   ```

## 流程 A：竞品分析

1. 向用户收集：商品名称、平台/站点、类目、自有规格、自有卖点、自有价格、竞品
   （名称/价格/评分/卖点/评论）、以及可选关键词。
2. 若用户提供 CSV/JSON/Excel 文件：

   ```powershell
   curl.exe -s -X POST http://127.0.0.1:8123/api/import -F "file=@competitors.csv"
   ```

   返回中的 `errors[]` 含行号与字段，**逐条转述给用户**，不要吞掉。
3. 组装请求体并 POST `/api/analyze`。请求体字段见下节。
4. 把返回的 `report` 用中文总结，保留 `evidence_kind`（fact/statistic/inference/assumption）
   与评论原文引用；同时复述 `warnings` 与 `limitations`。

## 流程 B：Listing 生成

1. 收集真实商品资料：名称、品牌、平台/站点、语言、规格、卖点、认证（有证书才填）、
   目标用户、禁用词。
2. 可直接传完整报告对象，或先存报告再传 `analysis_report_id`。
3. POST `/api/listings/generate`。
4. 输出时必须附上：
   - `quality_check.passed` 与所有 error 级问题；
   - `pending_confirmations`（待确认项）；
   - `quality_check.policy_disclaimer`（合规免责声明）。

## 请求体速查

`POST /api/analyze`

```json
{
  "product_name": "EcoSip Insulated Water Bottle",
  "platform": "amazon",
  "marketplace": "US",
  "category": "Sports Water Bottles",
  "own_specs": {"容量": "750ml"},
  "own_key_features": ["双层真空保温"],
  "own_price": 22.9,
  "competitors": [
    {
      "name": "Comp A", "price": 25.99, "rating": 4.4, "review_count": 1842,
      "key_features": ["Leak-proof lid"],
      "specifications": {"容量": "32oz"},
      "reviews": [{"rating": 2, "text": "The lid leaked in my bag."}],
      "is_demo": false
    }
  ],
  "keywords": [{"keyword": "insulated bottle", "search_volume": null, "rank": null}],
  "data_source": "user_input",
  "locale": "zh-CN"
}
```

`POST /api/listings/generate`

```json
{
  "product": {
    "name": "EcoSip Insulated Water Bottle",
    "brand": "EcoSip",
    "specifications": {"容量": "750ml", "材质": "304 不锈钢"},
    "key_features": ["双层真空保温"],
    "certifications": [],
    "target_platform": "amazon",
    "marketplace": "US",
    "price": 22.9,
    "target_audience": "通勤上班族",
    "banned_terms": []
  },
  "language": "en-US",
  "marketplace": "US",
  "analysis_report_id": "<上一步返回的 report_id>",
  "keywords": [],
  "data_source": "manual"
}
```

## 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| 422 + `detail.errors[]` | 缺少必填字段或类型不对 | 按 `field` 逐项补齐后重试 |
| 404 `分析报告不存在` | `analysis_report_id` 过期（换了数据目录） | 重新分析，或直接传 `analysis_report` |
| 503 `Provider` | 配置了未实现的 provider | 改回 `CROSSPILOT_PROVIDER=rule` |
| 导入返回 `errors` 但无 `competitors` | 表头缺 `name` 或全部行无效 | 提示用户修正表头/数据 |

## 输出格式建议

用四段式回答：

1. **数据来源与样本量**（含是否为 demo）
2. **关键发现**（每条标注证据性质，附评论原文）
3. **可执行建议**
4. **限制与待确认项**
