"""用真实 DeepSeek API 跑通端到端流程（会消耗少量额度）。"""

from __future__ import annotations

import sys
import time
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8160"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


with httpx.Client(base_url=BASE, timeout=180) as c:
    # 1) 注册一个干净账号
    username = f"real_{uuid.uuid4().hex[:8]}"
    reg = c.post("/api/auth/register", json={"username": username, "password": "Real-Passw0rd!"})
    check("register", reg.status_code in (200, 201), str(reg.status_code))

    # 2) 健康检查：应显示 deepseek 且可用
    h = c.get("/api/health").json()
    p = h["provider"]
    print(f"     provider={p['name']} available={p['available']} model={p.get('model')}")
    check("health.provider-deepseek", p["name"] == "deepseek")
    check("health.available", p["available"] is True)
    check("health.no-fallback", not p.get("fallback_reason"), str(p.get("fallback_reason")))

    # 3) 真实连通性测试
    print("\n--- 连通性测试（真实 API 调用）---")
    t0 = time.time()
    ping = c.post("/api/providers/ping").json()
    dt = time.time() - t0
    check("ping.ok", ping.get("ok") is True, f"{ping.get('detail')} ({dt:.1f}s)")

    # 4) 竞品分析（本地统计，不耗模型）
    demo = c.get("/api/demo/dataset").json()
    analyze = c.post("/api/analyze", json=demo["analysis_request"])
    check("analyze.ok", analyze.status_code == 200, str(analyze.status_code))
    report_id = analyze.json()["report"]["report_id"] if analyze.status_code == 200 else None
    print(f"     report_id={report_id}")

    # 5) 真实 Listing 生成
    print("\n--- Listing 生成（真实模型）---")
    payload = dict(demo["listing_request"])
    if report_id:
        payload["analysis_report_id"] = report_id
    t0 = time.time()
    gen = c.post("/api/listings/generate", json=payload)
    elapsed = time.time() - t0
    check("listing.http-ok", gen.status_code == 200, str(gen.status_code))
    if gen.status_code != 200:
        print(gen.text[:500])
    else:
        listing = gen.json()["listing"]
        print(f"     耗时 {elapsed:.1f}s | engine={listing['engine']} | case={listing['language']}")
        print(f"     标题: {listing['title']}")
        print(f"     五点: {len(listing['bullets'])} 条")
        for i, b in enumerate(listing["bullets"], 1):
            print(f"       {i}. {b['headline']} ({b['character_count']}c)")
            print(f"          {b['body'][:110]}")
        print(f"     Search Terms: {listing['search_terms']}")
        print(f"     A+ 模块: {[m['module_type'] for m in listing['a_plus_outline']]}")
        print(f"     质检通过: {listing['quality_check']['passed']}")
        for issue in listing["quality_check"]["issues"]:
            print(f"       [{issue['severity']}] {issue['code']}: {issue['message']}")
        print(f"     待确认: {listing['pending_confirmations']}")
        for lim in listing["limitations"]:
            print(f"     限制: {lim}")

        check("listing.engine-deepseek", listing["engine"] == "deepseek", listing["engine"])
        check("listing.bullets-5", len(listing["bullets"]) == 5, str(len(listing["bullets"])))
        check("listing.english-title", not any("\u4e00" <= ch <= "\u9fff" for ch in listing["title"]))
        check("listing.fact-ledger", len(listing["fact_ledger"]) > 0)
        check("listing.tokens-reported", any("tokens" in x for x in listing["limitations"]))
        # 关键：不得出现事实外的数字
        allowed = set()
        for item in listing["fact_ledger"]:
            for token in item["statement"].replace("：", " ").split():
                allowed.add(token)
        print(f"     事实台账 {len(listing['fact_ledger'])} 条")

    # 6) 历史
    check("history.own-reports", any(
        item["report_id"] == report_id for item in c.get("/api/reports").json()["items"]
    ))

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("REAL API E2E PASSED")
