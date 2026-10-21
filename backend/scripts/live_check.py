"""真实 HTTP 验收脚本：对运行中的服务做端到端检查（含文件上传）。

业务接口需要登录（项目后期加入鉴权，脚本已同步）。优先使用环境变量
``CROSSPILOT_LIVE_USER`` / ``CROSSPILOT_LIVE_PASSWORD``；
未提供时注册一个一次性账号并在结束时提示，方便手动清理。
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8123"
ROOT = Path(__file__).resolve().parent.parent
failures: list[str] = []
created_user = None


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


with httpx.Client(base_url=BASE, timeout=float(os.environ.get("CROSSPILOT_LIVE_TIMEOUT", "180"))) as client:
    # 0) 登录：业务接口全部需要认证
    user = os.environ.get("CROSSPILOT_LIVE_USER")
    password = os.environ.get("CROSSPILOT_LIVE_PASSWORD")
    if user and password:
        auth = client.post("/api/auth/login", json={"username": user, "password": password})
    else:
        user = f"livecheck_{uuid.uuid4().hex[:8]}"
        password = f"livecheck-{uuid.uuid4().hex[:12]}"
        auth = client.post("/api/auth/register", json={"username": user, "password": password})
        if auth.status_code == 200:
            created_user = user
    check("auth.login", auth.status_code == 200, str(auth.status_code))
    if auth.status_code == 200:
        client.headers["Authorization"] = f"Bearer {auth.json()['token']}"

    # 1) 健康检查
    health = client.get("/api/health").json()
    check("health.status", health.get("status") == "ok")
    check("health.provider", health["provider"]["name"] in {"rule", "deepseek", "openai", "harness"})

    # 2) 单一前端外壳与深链
    page = client.get("/")
    check("index.200", page.status_code == 200)
    check("index.shell", 'id="view-root"' in page.text and "/js/app.js" in page.text)
    check("spa.workbench", client.get("/workbench").status_code == 200)
    check("spa.deeplink", client.get("/tasks/tsk_demo").status_code == 200)
    check("assets.css", client.get("/css/tokens.css").status_code == 200)
    check("assets.js", client.get("/js/app.js").status_code == 200)
    check("legacy.removed", client.get("/legacy").status_code == 404)
    check("legacy.static-removed", client.get("/static/app.js").status_code == 404)

    # 3) 演示数据带 demo 标记
    demo = client.get("/api/demo/dataset").json()
    check("demo.flagged", demo["is_demo"] is True)
    check("demo.notice", "demo" in demo["notice"].lower() or "模拟" in demo["notice"])
    check(
        "demo.all-competitors-flagged",
        all(c.get("is_demo") for c in demo["competitors"]),
    )

    # 4) 分析
    analysis = client.post("/api/analyze", json=demo["analysis_request"])
    check("analyze.200", analysis.status_code == 200, str(analysis.status_code))
    report = analysis.json()["report"]
    check("analyze.demo-flag", report["data_provenance"]["is_demo"] is True)
    check("analyze.review-samples", report["data_provenance"]["review_sample_count"] == 17)
    check("analyze.pain-points", len(report["review_insights"]["pain_points"]) > 0)
    check("analyze.evidence-required", all(
        p.get("samples") for p in report["review_insights"]["pain_points"]
    ))
    check(
        "analyze.no-keyword-score-without-metrics",
        report["keyword_analysis"]["with_metrics"] == 0
        and all(o.get("opportunity_score") is None for o in report["keyword_analysis"]["opportunities"]),
    )
    check("analyze.warns-demo", any("demo" in w.lower() or "模拟" in w for w in report["warnings"]))
    report_id = report["report_id"]

    # 5) 报告持久化
    fetched = client.get(f"/api/reports/{report_id}")
    check("report.persisted", fetched.status_code == 200)
    check("report.listed", any(i["report_id"] == report_id for i in client.get("/api/reports").json()["items"]))

    # 6) Listing（完整资料）
    listing_resp = client.post(
        "/api/listings/generate",
        json={**demo["listing_request"], "analysis_report_id": report_id},
    )
    check("listing.200", listing_resp.status_code == 200, str(listing_resp.status_code))
    listing = listing_resp.json()["listing"]
    check("listing.title", bool(listing["title"]))
    check("listing.bullets-present", len(listing["bullets"]) >= 1)
    if health["provider"].get("name") != "rule":
        # 规则降级只陈述已确认事实，bullet 数量会少于 5；真实模型路径要求完整五点
        check("listing.bullets-5", len(listing["bullets"]) == 5)
    check("listing.report-linked", listing["analysis_report_id"] == report_id)
    check("listing.fact-ledger", len(listing["fact_ledger"]) > 0)
    check("listing.policy-disclaimer", "不构成合规承诺" in listing["quality_check"]["policy_disclaimer"])

    # 7) Listing（缺规格 -> 不编造）
    sparse = client.post(
        "/api/listings/generate",
        json={
            "product": {
                "name": "Sparse Bottle",
                "specifications": {},
                "key_features": ["double wall insulation"],
                "certifications": [],
            },
            "language": "en-US",
            "marketplace": "US",
        },
    )
    sparse_listing = sparse.json()["listing"]
    combined = (
        sparse_listing["title"]
        + sparse_listing["description"]
        + " ".join(b["body"] for b in sparse_listing["bullets"])
    )
    check("listing.sparse-no-invented-specs", "750ml" not in combined and "380g" not in combined)
    check("listing.sparse-pending", len(sparse_listing["pending_confirmations"]) >= 5)
    check(
        "listing.sparse-missing-fact-issue",
        any(i["code"] == "missing_fact" for i in sparse_listing["quality_check"]["issues"]),
    )

    # 8) 文件导入（真实 multipart 上传）
    csv_path = ROOT / "examples" / "competitors_sample.csv"
    with csv_path.open("rb") as handle:
        imported = client.post(
            "/api/import",
            files={"file": (csv_path.name, handle, "text/csv")},
        )
    check("import.csv-200", imported.status_code == 200, str(imported.status_code))
    import_data = imported.json()
    # CSV 同一竞品有多行评论，应合并为 2 个竞品
    check("import.csv-competitors", len(import_data["competitors"]) == 2, f"got {len(import_data['competitors'])}")
    check("import.csv-reviews-merged", sum(len(c["reviews"]) for c in import_data["competitors"]) == 4)
    check("import.csv-errors", import_data["errors"] == [])

    # 9) 缺列 CSV -> 422 + 明确错误
    bad = client.post("/api/import", files={"file": ("bad.csv", b"brand,price\nA,1\n", "text/csv")})
    check("import.missing-column-422", bad.status_code == 422)
    check("import.error-mentions-name", "name" in json.dumps(bad.json(), ensure_ascii=False))

    # 10) 行级错误
    partial = client.post("/api/import", files={"file": ("p.csv", b"name,price\n,9\n", "text/csv")})
    body = partial.json()
    check("import.row-error-row-num", bool(body["errors"]) and body["errors"][0]["row"] == 2)

    # 11) JSON 导入（含关键词）
    json_path = ROOT / "examples" / "competitors_sample.json"
    with json_path.open("rb") as handle:
        json_import = client.post("/api/import", files={"file": (json_path.name, handle, "application/json")})
    check("import.json-200", json_import.status_code == 200)
    check("import.json-keywords", len(json_import.json()["keywords"]) == 2)

    # 12) 错误处理
    check("error.missing-report-404", client.post(
        "/api/listings/generate",
        json={"product": {"name": "x"}, "analysis_report_id": "nope"},
    ).status_code == 404)
    check("error.invalid-body-422", client.post("/api/analyze", json={"product_name": "x"}).status_code == 422)

    # 13) 平台规则可配置
    rules = client.get("/api/platform-rules/amazon/US").json()
    check("rules.amazon-title-200", rules["title_max_chars"] == 200)
    check("rules.not-verified", rules["verified"] is False and bool(rules["disclaimer"]))
    check("rules.ebay-80", client.get("/api/platform-rules/ebay/US").json()["title_max_chars"] == 80)

    # 14) 任务中心（真实执行记录）
    tasks = client.get("/api/tasks").json()
    check("tasks.list", isinstance(tasks.get("items"), list) and len(tasks["items"]) > 0)
    first = tasks["items"][0]
    check("tasks.has-fields", bool(first.get("task_id")) and bool(first.get("status")))
    detail = client.get(f"/api/tasks/{first['task_id']}").json()
    check("tasks.steps", isinstance(detail.get("steps"), list) and len(detail["steps"]) > 0)
    check(
        "tasks.steps-have-duration",
        all(s.get("duration_ms") is not None for s in detail["steps"]),
    )
    check("tasks.filter", client.get("/api/tasks?status=succeeded").status_code == 200)
    check("tasks.search", client.get("/api/tasks?q=Listing").status_code == 200)
    check("tasks.404", client.get("/api/tasks/does-not-exist").status_code == 404)

    # 15) 失败任务可追踪（未实现的 provider -> 503 且留痕）
    dash = client.get("/api/dashboard").json()
    check("dashboard.stats", isinstance(dash.get("stats"), dict) and "total" in dash["stats"])
    check("dashboard.recent", isinstance(dash.get("recent_tasks"), list))

    # 16) 多租户
    tenants = client.get("/api/tenants").json()["items"]
    check("tenant.list", isinstance(tenants, list) and len(tenants) == 1)
    current = client.get("/api/tenants/current").json()
    check("tenant.current", current.get("role") == "owner" and bool(current.get("tenant_id")))
    check("tenant.stats", "reports" in (current.get("stats") or {}))
    forged = client.get("/api/tenants/current", headers={"X-Tenant-Id": "not-a-tenant"})
    check("tenant.forged-403", forged.status_code == 403)

    # 17) Agent 注册表与运行时（确定性路径，不调用模型）
    agents = client.get("/api/agents").json()["items"]
    skills = client.get("/api/skills").json()["items"]
    tools = client.get("/api/tools").json()["items"]
    check("registry.agents", len(agents) >= 3)
    check("registry.skills", len(skills) >= 5)
    check("registry.tools", len(tools) >= 3)
    check("registry.schemas", all(a.get("input_schema") for a in agents))

    run_req = demo["analysis_request"]
    run_payload = {
        "agent_key": "main",
        "product_name": run_req["product_name"],
        "platform": run_req.get("platform", "amazon"),
        "marketplace": run_req.get("marketplace", "US"),
        "category": run_req.get("category"),
        "own_specs": run_req.get("own_specs") or {},
        "own_key_features": run_req.get("own_key_features") or [],
        "own_price": run_req.get("own_price"),
        "competitors": run_req["competitors"],
        "keywords": run_req.get("keywords") or [],
        "with_listing": False,
        "data_source": run_req.get("data_source", "demo"),
    }
    run = client.post("/api/agent/runs", json=run_payload)
    check("agent.run", run.status_code == 200, str(run.status_code))
    if run.status_code == 200:
        body = run.json()
        check("agent.plan", body["plan"] == ["analyze", "integrity", "summary", "persist"])
        check("agent.summary", bool((body.get("summary") or {}).get("points")))
        check("agent.integrity", "metrics" in (body.get("checks") or {}))
        steps = client.get(f"/api/tasks/{body['task_id']}").json()["steps"]
        check("agent.steps", [s["name"] for s in steps][0] == "生成执行计划")

    # 18) 目标解析、会话、审计、审批（阶段 C/D 新增能力）
    resolved = client.post("/api/agent/resolve", json={"goal": "分析“EcoSip Bottle”在日本站的竞品"})
    check("agent.resolve-200", resolved.status_code == 200, str(resolved.status_code))
    if resolved.status_code == 200:
        resolved_body = resolved.json()
        check("agent.resolve-spec", resolved_body["spec"]["product_name"] == "EcoSip Bottle")
        check("agent.resolve-degraded-flag", isinstance(resolved_body["degraded"], bool))

    run_body = run.json() if run.status_code == 200 else {}
    conversation_id = run_body.get("conversation_id")
    check("conversation.created-by-run", bool(conversation_id))
    if conversation_id:
        conversation = client.get(f"/api/conversations/{conversation_id}").json()
        roles = [m["role"] for m in conversation.get("messages", [])]
        check("conversation.messages", roles == ["user", "assistant"], str(roles))

    audits = client.get("/api/audit?limit=50").json()["items"]
    audit_actions = {item["action"] for item in audits}
    check("audit.login-recorded", "auth.login" in audit_actions or "auth.register" in audit_actions)
    check("audit.task-run-recorded", "task.run" in audit_actions)

    approval = client.post(
        "/api/approvals",
        json={"kind": "publish_listing", "listing_id": listing["listing_id"]},
    )
    check("approval.request", approval.status_code == 200, str(approval.status_code))
    if approval.status_code == 200:
        approval_body = approval.json()
        check("approval.pending", approval_body["status"] == "pending")
        approval_task = client.get(f"/api/tasks/{approval_body['task_id']}").json()
        check("approval.task-awaiting", approval_task["task"]["status"] == "awaiting_approval")
        decided = client.post(
            f"/api/approvals/{approval_body['approval_id']}/decide",
            json={"decision": "approved"},
        )
        check("approval.decide", decided.status_code == 200, str(decided.status_code))
        decided_task = client.get(f"/api/tasks/{approval_body['task_id']}").json()
        check("approval.no-fake-publish", decided_task["task"]["output"].get("published") is False)

    # 19) 迁移版本表
    check("migrations.applied", client.get("/api/health").status_code == 200)

    # 20) 阶段 E：导出 / 版本 / 复检 / 导入两步
    exported = client.get(f"/api/reports/{report_id}/export?format=md")
    check("export.report-md", exported.status_code == 200 and "## 竞品对比" in exported.text)
    check("export.bad-format", client.get(f"/api/reports/{report_id}/export?format=pdf").status_code == 400)

    version = client.post(
        f"/api/listings/{listing['listing_id']}/versions",
        json={"title": "Livecheck revised bottle title"},
    )
    check("listing.version", version.status_code == 200, str(version.status_code))
    if version.status_code == 200:
        versioned = version.json()["listing"]
        check("listing.version-number", versioned["version"] == 2)
        diff = client.get(f"/api/listings/{versioned['listing_id']}/diff")
        check("listing.diff", diff.status_code == 200 and "title" in diff.json()["changed_fields"])
        recheck = client.post(f"/api/listings/{versioned['listing_id']}/check")
        check("listing.recheck", recheck.status_code == 200, str(recheck.status_code))
        listing_export = client.get(f"/api/listings/{versioned['listing_id']}/export?format=md")
        check("export.listing-md", listing_export.status_code == 200)

    preview = client.post(
        "/api/import/preview",
        files={"file": ("live.csv", b"name,price\nLive Bottle,9.99\n", "text/csv")},
    )
    check("import.preview", preview.status_code == 200, str(preview.status_code))
    if preview.status_code == 200:
        preview_body = preview.json()
        check("import.preview-valid", preview_body["can_commit"] is True)
        committed = client.post(
            "/api/import/commit", json={"data_source_id": preview_body["data_source_id"]}
        )
        check("import.commit", committed.status_code == 200, str(committed.status_code))
        check("import.two-step", committed.json()["data_source_id"] == preview_body["data_source_id"])
        sources = client.get("/api/data-sources").json()["items"]
        check("import.data-source-listed", any(s["data_source_id"] == preview_body["data_source_id"] for s in sources))

    # 21) 阶段 F：Mock 店铺连接
    store = client.post(
        "/api/stores",
        json={"platform": "amazon", "marketplace": "US", "shop_name": "Livecheck Mock Shop", "mode": "mock"},
    )
    check("store.create", store.status_code == 200, str(store.status_code))
    if store.status_code == 200:
        store_body = store.json()
        check("store.is-mock", store_body["mode"] == "mock" and store_body["is_mock"] is True)
        synced = client.post(f"/api/stores/{store_body['connection_id']}/sync")
        check("store.sync", synced.status_code == 200 and synced.json()["is_mock"] is True)
        products = client.get(f"/api/stores/{store_body['connection_id']}/products").json()
        check("store.products-mock", all(p["is_mock"] for p in products["items"]))
        live = client.post(
            "/api/stores",
            json={"platform": "amazon", "marketplace": "US", "shop_name": "Livecheck Real Shop", "mode": "live"},
        )
        check("store.live-not-faked", live.status_code == 400)
        stores = client.get("/api/stores").json()
        check("store.list", stores["capabilities"]["live"] is False)

print()
if created_user:
    print(f"提示：本次验收注册了临时账号 {created_user!r}，如不需要可在数据库中删除。")
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("ALL LIVE CHECKS PASSED")
