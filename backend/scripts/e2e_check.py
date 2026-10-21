"""端到端验收：注册/登录 -> 配置模型 -> 分析 -> 生成 -> 降级提示。

以真实 HTTP 打运行中的服务，覆盖多用户与每用户模型配置。
"""

from __future__ import annotations

import sys
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8160"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


with httpx.Client(base_url=BASE, timeout=90) as c:
    # 1) 匿名可访问的健康检查
    h = c.get("/api/health").json()
    check("health.ok", h.get("status") == "ok")
    check("health.has-fallback-field", "fallback_reason" in h["provider"])
    check("health.marketplaces", len(h["platforms"]) >= 1)

    # 2) 认证状态
    status = c.get("/api/auth/status").json()
    check("auth.status", isinstance(status, dict))

    # 3) 未登录时受保护接口应 401
    protected = c.get("/api/settings/model")
    check("auth.protected-401", protected.status_code in (401, 403), str(protected.status_code))

    # 4) 注册新用户
    username = f"probe_{uuid.uuid4().hex[:8]}"
    reg = c.post(
        "/api/auth/register",
        json={"username": username, "password": "Probe-Passw0rd!"},
    )
    check("auth.register", reg.status_code in (200, 201), str(reg.status_code))
    if reg.status_code not in (200, 201):
        print(reg.text[:300])

    # 5) 模型配置（每用户）
    model = c.get("/api/settings/model")
    check("settings.model-get", model.status_code == 200, str(model.status_code))
    if model.status_code == 200:
        data = model.json()
        effective = data.get("effective", {})
        check("settings.model-shape", {"provider", "model", "source"} <= set(effective))
        # 关键安全断言：任何情况下都不得回显完整 Key
        raw = str(data)
        check("settings.model-key-masked", not any(
            token in raw for token in ("sk-SECRET", "sk-live", "sk-proj")
        ))
        check("settings.model-mask-format", "****" in effective.get("api_key", "") or not effective.get("has_api_key"))

    # 6) 健康检查应带上登录用户的配置
    h2 = c.get("/api/health").json()
    check("health.authenticated", h2["provider"]["name"] in {"rule", "deepseek", "openai"})
    check("health.configured-model", "configured_model" in h2)

    # 7) 竞品分析
    demo = c.get("/api/demo/dataset").json()
    analyze = c.post("/api/analyze", json=demo["analysis_request"])
    check("analyze.ok", analyze.status_code == 200, str(analyze.status_code))
    if analyze.status_code == 200:
        report = analyze.json()["report"]
        check("analyze.evidence", all(p.get("samples") for p in report["review_insights"]["pain_points"]))
        check("analyze.no-fake-keyword-score",
              all(o.get("opportunity_score") is None for o in report["keyword_analysis"]["opportunities"]))
        report_id = report["report_id"]
        check("analyze.persisted", c.get(f"/api/reports/{report_id}").status_code == 200)
    else:
        report_id = None

    # 8) Listing 生成
    payload = dict(demo["listing_request"])
    if report_id:
        payload["analysis_report_id"] = report_id
    gen = c.post("/api/listings/generate", json=payload)
    check("listing.ok", gen.status_code == 200, str(gen.status_code))
    if gen.status_code == 200:
        listing = gen.json()["listing"]
        check("listing.has-fact-ledger", len(listing["fact_ledger"]) > 0)
        check("listing.disclaimer", "不构成合规承诺" in listing["quality_check"]["policy_disclaimer"])
        degraded = listing["engine"] == "rule-fallback"
        if degraded:
            check("listing.degrade-flagged",
                  any("降级" in r for r in listing["quality_check"]["rules_applied"]))
            check("listing.degrade-not-passed", listing["quality_check"]["passed"] is False)
            print("        （未配置 Key，已正确降级并标注）")
        else:
            check("listing.llm-engine", listing["engine"] == "deepseek")
            check("listing.bullets-5", len(listing["bullets"]) == 5, str(len(listing["bullets"])))

    # 9) 站点配置
    mk = c.get("/api/marketplaces").json()
    check("marketplaces.count", len(mk["marketplaces"]) == 9, str(len(mk["marketplaces"])))
    check("marketplaces.de-language", mk["profiles"]["DE"]["language"] == "de-DE")
    check("marketplaces.jp-language", mk["profiles"]["JP"]["language"] == "ja-JP")

    # 10) 导入
    csv_text = (
        "name,brand,price,review_text,review_rating\n"
        "Probe A,BrandA,19.99,Lid leaked,2\n"
        "Probe A,BrandA,19.99,Easy to clean,5\n"
        "Probe B,BrandB,29.5,Works well,5\n"
    )
    imp = c.post("/api/import", files={"file": ("probe.csv", csv_text.encode("utf-8"), "text/csv")})
    check("import.ok", imp.status_code == 200, str(imp.status_code))
    if imp.status_code == 200:
        body = imp.json()
        check("import.merged-duplicates", len(body["competitors"]) == 2, str(len(body["competitors"])))
        check("import.reviews-merged", sum(len(x["reviews"]) for x in body["competitors"]) == 3)

    # 11) 登出后受保护接口恢复 401
    c.post("/api/auth/logout")
    check("auth.logout-401", c.get("/api/settings/model").status_code in (401, 403))

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("ALL E2E CHECKS PASSED")
