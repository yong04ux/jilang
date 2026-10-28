/* 激浪 · 店铺与渠道（店铺经营助手）
 *
 * 四个子页：店铺授权 / 经营看板 / 单品分析 / 经营明细。
 * 对标 https://os.linkfox.com/store-assistant 的结构，视觉走激浪品牌蓝。
 *
 * 数据纪律：
 * - 所有数字来自 /api/marketplace/*，不在前端造任何一个业绩指标；
 * - 后端没给的维度（库龄占比之外的账号表现等）就不出卡片，不摆空壳；
 * - 店铺是示例店铺时统一打「示例」徽标，别让人误当成真实经营数据。
 */
(function () {
  "use strict";

  const U = window.CPUi;
  const A = window.CPApi;
  const L = window.CPLabel;

  /* ---------------- 结构定义 ---------------- */

  const TABS = [
    { key: "authorize", label: "店铺授权", path: "/stores/authorize" },
    { key: "dashboard", label: "经营看板", path: "/stores" },
    { key: "product", label: "单品分析", path: "/stores/product" },
    { key: "ledger", label: "经营明细", path: "/stores/ledger" },
  ];

  const RANGES = [
    { key: "1d", label: "今日" },
    { key: "7d", label: "近 7 天" },
    { key: "30d", label: "近 30 天" },
  ];

  const SEGMENTS = [
    { key: "overview", label: "概览" },
    { key: "orders", label: "订单" },
    { key: "ads", label: "广告" },
    { key: "inventory", label: "库存" },
    { key: "aftersales", label: "售后" },
  ];

  const LEDGERS = [
    { key: "listing", label: "Listing" },
    { key: "orders", label: "订单列表" },
    { key: "aftersales", label: "售后订单" },
    { key: "fba", label: "库存明细" },
  ];

  const HEAD = {
    authorize: {
      title: "店铺授权",
      desc: "绑定店铺后，商品、订单与广告数据会同步过来。也可以先用示例店铺把整个流程走通。",
    },
    dashboard: {
      title: "经营看板",
      desc: "这家店最近一段时间的经营情况。每个数字都由订单与广告数据聚合得出。",
    },
    product: {
      title: "单品分析",
      desc: "挑一个商品，看它的销售走势、广告表现和库存风险。",
    },
    ledger: {
      title: "经营明细",
      desc: "按类型查看明细表，行可以展开看完整字段。",
    },
  };

  /* ---------------- 小工具 ---------------- */

  function esc(value) { return U.esc(value); }

  function money(value, currency) {
    return window.CPChart.moneyFull(Number(value) || 0, currency);
  }

  function shortMoney(value, currency) {
    return window.CPChart.money(Number(value) || 0, currency);
  }

  function num(value) {
    const n = Number(value);
    if (!isFinite(n)) return "—";
    return n.toLocaleString("zh-CN", { maximumFractionDigits: 1 });
  }

  function pctText(value) {
    const n = Number(value);
    if (!isFinite(n)) return "—";
    return n.toFixed(2) + "%";
  }

  function pill(text, tone) {
    return '<span class="st-pill st-pill--' + (tone || "muted") + '">' + esc(text) + "</span>";
  }

  /**
   * 环比涨跌。inverse=true 用于成本类指标（ACOS / CPC 降才是好事）。
   * 上一窗口没有数据时显示破折号，不写成 0%——那是在编一个不存在的对比。
   */
  function delta(value, inverse) {
    if (value === null || value === undefined || !isFinite(Number(value))) {
      return '<span class="st-metric-delta is-flat">无对比</span>';
    }
    const n = Number(value);
    if (Math.abs(n) < 0.05) return '<span class="st-metric-delta is-flat">持平</span>';
    const up = n > 0;
    const good = inverse ? !up : up;
    return (
      '<span class="st-metric-delta ' + (good ? "is-good" : "is-bad") + '">' +
      (up ? "▲" : "▼") + " " + Math.abs(n).toFixed(1) + "%<span style=\"opacity:.6\"> 环比</span></span>"
    );
  }

  function metric(label, valueHtml, deltaHtml) {
    return (
      '<div class="st-metric">' +
      '<span class="st-metric-label">' + esc(label) + "</span>" +
      '<span class="st-metric-value">' + valueHtml + "</span>" +
      (deltaHtml || "") +
      "</div>"
    );
  }

  function card(title, body, extra, opts) {
    const options = opts || {};
    return (
      '<section class="st-card">' +
      (title
        ? '<header class="st-card-head"><div class="st-card-title">' +
          esc(title) + "</div>" +
          (extra ? '<div class="st-card-extra">' + extra + "</div>" : "") +
          "</header>"
        : "") +
      '<div class="st-card-body' + (options.flush ? " st-card-body--flush" : "") + '">' +
      body +
      "</div></section>"
    );
  }

  function table(headers, rows, opts) {
    const options = opts || {};
    const head = headers.map(function (item) {
      const label = typeof item === "string" ? item : item.label;
      const align = typeof item === "string" ? "" : (item.align === "right" ? ' class="num"' : "");
      return "<th" + align + ">" + esc(label) + "</th>";
    }).join("");
    const body = rows.length
      ? rows.join("")
      : '<tr><td colspan="' + headers.length + '"><div class="cp-chart-empty" style="min-height:96px">' +
        esc(options.empty || "这个时间范围内没有数据") + "</div></td></tr>";
    return (
      '<div class="st-table-wrap"' + (options.maxHeight ? ' style="max-height:' + options.maxHeight + '"' : "") + ">" +
      '<table class="st-table"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table>" +
      "</div>"
    );
  }

  function loading(text) {
    return (
      '<div class="st-loading">' +
      '<div class="skeleton skeleton-line" style="height:44px"></div>' +
      '<div class="skeleton skeleton-line" style="height:180px"></div>' +
      '<div class="skeleton skeleton-line" style="height:120px"></div>' +
      "</div>" +
      (text ? '<p class="t-xs t-muted mt-3">' + esc(text) + "</p>" : "")
    );
  }

  function storeOptions(stores, currentId) {
    return stores.map(function (item) {
      return (
        '<option value="' + esc(item.connection_id) + '"' +
        (item.connection_id === currentId ? " selected" : "") + ">" +
        esc(item.shop_name) + " · " + esc(item.marketplace) + "</option>"
      );
    }).join("");
  }

  /* ---------------- 页面骨架 ---------------- */

  function shell(view, actions, body) {
    const head = HEAD[view] || HEAD.dashboard;
    const tabs = TABS.map(function (tab) {
      return (
        '<a class="st-tab' + (tab.key === view ? " is-active" : "") + '" href="' +
        tab.path + '" data-link' + (tab.key === view ? ' aria-current="page"' : "") + ">" +
        esc(tab.label) + "</a>"
      );
    }).join("");
    return (
      '<div class="view"><div class="page page--store"><div class="page-inner">' +
      '<div class="page-head"><div><h1 class="page-title">' + esc(head.title) + "</h1>" +
      '<p class="page-desc">' + esc(head.desc) + "</p></div>" +
      '<div class="page-actions">' + (actions || "") + "</div></div>" +
      '<nav class="st-tabs" aria-label="店铺经营助手">' + tabs + "</nav>" +
      '<div id="st-stage">' + body + "</div>" +
      "</div></div></div>"
    );
  }

  /* ---------------- 入口 ---------------- */

  /* 渲染序号：子页之间切得快时，上一页的 await 可能在新页面挂载之后才回来。
     届时 #st-stage 已被清掉（querySelector 返回 null），旧数据也会画到新页上。
     每次 render 领一个号，await 回来先对号，过号就直接放弃。 */
  let renderSeq = 0;

  async function render(root, view, query) {
    const token = (renderSeq += 1);
    const params = query || {};
    const state = {
      view: view,
      token: token,
      range: RANGES.some(function (r) { return r.key === params.range; }) ? params.range : "30d",
      segment: SEGMENTS.some(function (s) { return s.key === params.seg; }) ? params.seg : "overview",
      ledger: LEDGERS.some(function (l) { return l.key === params.kind; }) ? params.kind : "listing",
      asin: params.asin || "",
      storeId: params.store || "",
      stores: [],
      data: null,
      products: [],
    };

    const actions = view === "authorize"
      ? '<button type="button" class="btn btn-primary btn-sm" id="st-add">' +
        U.icon("plus") + "添加店铺</button>"
      : "";

    root.innerHTML = shell(view, actions, loading());

    let error = null;
    try {
      state.stores = (await A.get("/api/stores")).items || [];
    } catch (err) {
      error = err;
    }
    if (token !== renderSeq) return;
    if (!state.storeId && state.stores.length) {
      state.storeId = state.stores[0].connection_id;
    }

    const stage = root.querySelector("#st-stage");
    if (!stage) return;
    if (error) {
      stage.innerHTML =
        '<div class="callout callout-danger">' + U.icon("alert") +
        "<div>店铺列表加载失败：" + esc(error.message) + "</div></div>";
      return;
    }

    if (view === "authorize") {
      await paintAuthorize(root, stage, state);
      return;
    }
    if (!state.stores.length) {
      stage.innerHTML = unboundState();
      bindUnbound(stage);
      return;
    }

    if (view === "dashboard") await paintDashboard(root, stage, state);
    else if (view === "product") await paintProduct(root, stage, state);
    else await paintLedger(root, stage, state);
  }

  function syncUrl(state) {
    const pairs = [];
    const base = state.view === "dashboard" ? "/stores"
      : state.view === "authorize" ? "/stores/authorize"
      : state.view === "product" ? "/stores/product"
      : "/stores/ledger";
    if (state.view !== "authorize") {
      if (state.storeId) pairs.push("store=" + encodeURIComponent(state.storeId));
      pairs.push("range=" + encodeURIComponent(state.range));
    }
    if (state.view === "dashboard" && state.segment !== "overview") pairs.push("seg=" + state.segment);
    if (state.view === "ledger" && state.ledger !== "listing") pairs.push("kind=" + state.ledger);
    if (state.view === "product" && state.asin) pairs.push("asin=" + encodeURIComponent(state.asin));
    const url = pairs.length ? base + "?" + pairs.join("&") : base;
    history.replaceState(history.state, "", url);
  }

  /* ---------------- 未绑定店铺 ---------------- */

  function unboundState() {
    return (
      card(
        "还没有绑定店铺",
        '<p class="t-sm t-muted" style="margin:0 0 14px">绑定之后，这里会显示这家店真实的商品、订单、广告与库存。' +
        "现在可以先加一个示例店铺，把整个流程走一遍。</p>" +
        '<div class="row gap-2"><button type="button" class="btn btn-primary btn-sm" id="st-unbound-add">' +
        U.icon("plus") + "添加示例店铺</button>" +
        '<a class="btn btn-sm btn-secondary" href="/data" data-link>去导入商品文件</a></div>'
      ) +
      '<div class="st-steps mt-3">' +
      step(1, "选择店铺", "选平台与站点，填一个你自己认得出来的店铺名。") +
      step(2, "确认站点", "一个店铺对应一个站点；多站点请分别绑定。") +
      step(3, "开始同步", "同步完成后，商品、订单与广告数据会在这里按日汇总。") +
      "</div>"
    );
  }

  function step(index, title, desc) {
    return (
      '<div class="st-step">' +
      '<span class="st-step-no">' + index + "</span>" +
      '<p class="st-step-title">' + esc(title) + "</p>" +
      '<p class="st-step-desc">' + esc(desc) + "</p>" +
      "</div>"
    );
  }

  function bindUnbound(stage) {
    const btn = stage.querySelector("#st-unbound-add");
    if (btn) btn.addEventListener("click", function () { window.CPRouter.go("/stores/authorize"); });
  }

  /* ---------------- 子页：店铺授权 ---------------- */

  async function paintAuthorize(root, stage, state) {
    let sources = [];
    try { sources = (await A.get("/api/marketplace/sources")).items || []; } catch (err) { /* 拿不到就不显示 */ }

    const rows = state.stores.map(function (item) {
      const summary = item.last_sync_summary || {};
      const counts = [];
      if (summary.products) counts.push(summary.products + " 个商品");
      if (summary.orders) counts.push(summary.orders + " 笔订单");
      const sample = Boolean(item.is_demo) || item.mode === "mock";
      return (
        "<tr>" +
        '<td><div class="st-cell-product"><div>' +
        "<strong style=\"color:var(--foreground)\">" + esc(item.shop_name) + "</strong>" +
        "<small>" + esc(L.platform(item.platform)) + " · " + esc(L.site(item.marketplace)) + "</small>" +
        "</div></div></td>" +
        "<td>" + (sample ? pill("示例店铺", "brand") : pill("已连接", "ok")) + "</td>" +
        '<td class="t-muted">' + (item.last_sync_at ? esc(U.fmtTime(item.last_sync_at)) : "还没同步过") + "</td>" +
        '<td class="t-muted">' + esc(counts.join(" · ") || "—") + "</td>" +
        '<td class="num">' +
        '<button type="button" class="btn btn-sm" data-sync="' + esc(item.connection_id) + '">同步</button>' +
        "</td></tr>"
      );
    });

    const sourceRows = sources.map(function (item) {
      let tone = "muted";
      let label = "未设置";
      if (item.mode === "upload") { tone = "muted"; label = "你的文件"; }
      else if (item.configured && item.mode === "live") { tone = "ok"; label = "已连接"; }
      else if (item.configured) { tone = "brand"; label = "示例数据"; }
      return (
        "<tr><td>" + esc(item.label) + "</td>" +
        '<td class="t-muted">' + esc(item.detail || "") + "</td>" +
        "<td>" + pill(label, tone) + "</td>" +
        '<td class="t-muted">' + (item.last_sync_at ? esc(U.fmtTime(item.last_sync_at)) : "—") + "</td></tr>"
      );
    });

    stage.innerHTML =
      card(
        "已绑定店铺",
        table(
          [{ label: "店铺" }, { label: "状态" }, { label: "最后同步" }, { label: "同步内容" }, { label: "操作", align: "right" }],
          rows,
          { empty: "还没有绑定店铺" }
        ),
        state.stores.length ? state.stores.length + " 个店铺" : "",
        { flush: true }
      ) +
      '<div id="st-form"></div>' +
      (sourceRows.length
        ? card(
            "各数据域的数据来源",
            table([{ label: "数据域" }, { label: "说明" }, { label: "来源" }, { label: "最后同步" }], sourceRows),
            null,
            { flush: true }
          )
        : "");

    // 同步按钮
    stage.querySelectorAll("[data-sync]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const id = btn.getAttribute("data-sync");
        btn.disabled = true;
        btn.textContent = "同步中…";
        try {
          const result = await A.post("/api/stores/" + encodeURIComponent(id) + "/sync", {});
          U.toast("同步完成：" + (result.products || 0) + " 个商品 / " + (result.orders || 0) + " 笔订单", "ok");
          render(root, "authorize", {});
        } catch (err) {
          U.toast(err.message, "danger");
          btn.disabled = false;
          btn.textContent = "同步";
        }
      });
    });

    const addBtn = root.querySelector("#st-add");
    if (addBtn) addBtn.addEventListener("click", function () { openCreateForm(root, state); });
  }

  async function openCreateForm(root, state) {
    const box = root.querySelector("#st-form");
    if (!box) return;
    let catalog = [];
    let defaultPlatform = "amazon";
    try {
      const meta = await A.get("/api/platforms");
      catalog = meta.catalog || [];
      defaultPlatform = meta.default_platform || "amazon";
    } catch (err) { /* 拿不到目录就退回内置平台列表 */ }
    const platformList = catalog.length ? catalog : [
      { key: "amazon", label: "Amazon", marketplaces: ["US"] },
    ];

    box.innerHTML =
      '<form id="st-create" class="st-card" style="padding:16px;margin-top:12px">' +
      '<div class="st-card-title">添加示例店铺</div>' +
      '<p class="t-xs t-muted" style="margin:6px 0 0">示例店铺带一组固定的商品与订单，用来试用同步、看板与分析流程；' +
      "它不代表你的真实经营数据。</p>" +
      '<div class="grid-2 mt-3">' +
      '<label class="field"><span class="field-label">平台</span><select name="platform">' +
      platformList.map(function (item) {
        return '<option value="' + esc(item.key) + '"' + (item.key === defaultPlatform ? " selected" : "") + ">" +
          esc(item.label || item.key) + "</option>";
      }).join("") +
      "</select></label>" +
      '<label class="field"><span class="field-label">站点</span><select name="marketplace"></select></label>' +
      '<label class="field field-span-2"><span class="field-label">店铺名称</span>' +
      '<input name="shop_name" required placeholder="例如 我的试用店铺" /></label>' +
      "</div>" +
      '<div class="row gap-2 mt-3">' +
      '<button type="submit" class="btn btn-primary btn-sm">添加</button>' +
      '<button type="button" class="btn btn-quiet btn-sm" id="st-cancel">取消</button>' +
      "</div></form>";

    const form = box.querySelector("#st-create");
    const platformSelect = form.querySelector('[name="platform"]');
    const marketSelect = form.querySelector('[name="marketplace"]');
    const fillMarkets = function () {
      const spec = platformList.filter(function (item) { return item.key === platformSelect.value; })[0];
      const list = (spec && spec.marketplaces && spec.marketplaces.length) ? spec.marketplaces : ["US"];
      marketSelect.innerHTML = list.map(function (code) {
        return '<option value="' + esc(code) + '">' + esc(L.site(code)) + "</option>";
      }).join("");
    };
    fillMarkets();
    platformSelect.addEventListener("change", fillMarkets);
    form.querySelector("#st-cancel").addEventListener("click", function () { box.innerHTML = ""; });
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      try {
        await A.post("/api/stores", {
          platform: form.platform.value,
          marketplace: form.marketplace.value.trim().toUpperCase() || "US",
          shop_name: form.shop_name.value.trim(),
          mode: "mock",
        });
        U.toast("店铺已添加", "ok");
        window.CPRouter.go("/stores/authorize", { force: true });
      } catch (err) {
        U.toast(err.message, "danger");
      }
    });
  }

  /* ---------------- 公共工具栏 ---------------- */

  function toolbar(state, extra) {
    const rangeSeg = RANGES.map(function (item) {
      return '<button type="button" data-range="' + item.key + '"' +
        (item.key === state.range ? ' class="is-active"' : "") + ">" + esc(item.label) + "</button>";
    }).join("");
    return (
      '<div class="st-toolbar">' +
      (state.stores.length
        ? '<span class="st-select"><select id="st-store" aria-label="选择店铺">' +
          storeOptions(state.stores, state.storeId) + "</select>" + U.icon("chevronDown") + "</span>"
        : "") +
      (extra || "") +
      '<div class="st-toolbar-right"><div class="st-seg" role="group" aria-label="时间范围">' +
      rangeSeg + "</div></div></div>"
    );
  }

  function bindToolbar(stage, state, onReload) {
    const storeSelect = stage.querySelector("#st-store");
    if (storeSelect) {
      storeSelect.addEventListener("change", function () {
        state.storeId = storeSelect.value;
        syncUrl(state);
        onReload();
      });
    }
    stage.querySelectorAll("[data-range]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.range = btn.getAttribute("data-range");
        syncUrl(state);
        onReload();
      });
    });
  }

  /* ---------------- 子页：经营看板 ---------------- */

  async function paintDashboard(root, stage, state) {
    stage.innerHTML = toolbar(state) + '<div id="st-dash">' + loading() + "</div>";
    bindToolbar(stage, state, function () { paintDashboard(root, stage, state); });

    const host = stage.querySelector("#st-dash");
    if (!host) return;
    let data;
    try {
      data = await A.get(
        "/api/marketplace/dashboard?connection_id=" + encodeURIComponent(state.storeId) +
        "&range=" + encodeURIComponent(state.range)
      );
    } catch (err) {
      if (state.token === renderSeq) {
        host.innerHTML = '<div class="callout callout-danger">' + U.icon("alert") +
          "<div>" + esc(err.message) + "</div></div>";
      }
      return;
    }
    if (state.token !== renderSeq) return;
    state.data = data;
    paintDashboardBody(host, state);
  }

  function paintDashboardBody(host, state) {
    const data = state.data;
    const inventory = data.inventory || { totals: {}, items: [], agingTotals: {} };
    const returns = data.returns || [];
    const health = data.health || { items: [] };
    const pendingReturns = returns.filter(function (item) { return item.status !== "refunded"; }).length;

    const todos = [
      { label: "已断货 SKU", value: inventory.totals.outOfStock || 0, tone: "danger", seg: "inventory", note: "可售库存为 0" },
      { label: "库存偏低", value: inventory.totals.lowStock || 0, tone: "warning", seg: "inventory", note: "可售不足 15 件" },
      { label: "滞销 SKU", value: inventory.totals.slowMoving || 0, tone: "warning", seg: "inventory", note: "30 天无销量" },
      { label: "待处理售后", value: pendingReturns, tone: pendingReturns ? "warning" : "ok", seg: "aftersales", note: "等待审核或处理" },
      { label: "违规警告", value: health.warnings || 0, tone: health.warnings ? "warning" : "ok", seg: "", note: "平台账户状态" },
      { label: "政策违规", value: health.policyViolations || 0, tone: health.policyViolations ? "danger" : "ok", seg: "", note: "平台账户状态" },
    ];

    const todoHtml = todos.map(function (item) {
      const tag = item.seg ? "button" : "div";
      const attrs = item.seg
        ? ' type="button" data-seg="' + item.seg + '"'
        : "";
      return (
        "<" + tag + ' class="st-todo st-todo--' + item.tone + '"' + attrs + ">" +
        "<span>" + esc(item.label) + "</span>" +
        "<strong>" + item.value + "</strong>" +
        "<small>" + esc(item.note) + "</small>" +
        "</" + tag + ">"
      );
    }).join("");

    const segHtml = SEGMENTS.map(function (item) {
      return '<button type="button" data-seg-key="' + item.key + '"' +
        (item.key === state.segment ? ' class="is-active"' : "") + ">" + esc(item.label) + "</button>";
    }).join("");

    host.innerHTML =
      card("待处理事项", '<div class="st-todos">' + todoHtml + "</div>", "")
      + '<div class="st-toolbar" style="margin:14px 0 12px">' +
        '<div class="st-seg" role="group" aria-label="看板分区">' + segHtml + "</div>" +
        '<div class="st-toolbar-right">' + (data.store.is_demo ? pill("示例店铺", "brand") : "") + "</div></div>" +
      '<div id="st-seg-body"></div>';

    const body = host.querySelector("#st-seg-body");
    const paintSegment = function () {
      body.innerHTML = segmentBody(state, data, inventory, returns, health);
      bindSegment(state, body, paintSegment);
    };
    paintSegment();

    host.querySelectorAll("[data-seg-key]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.segment = btn.getAttribute("data-seg-key");
        host.querySelectorAll("[data-seg-key]").forEach(function (other) {
          other.classList.toggle("is-active", other === btn);
        });
        syncUrl(state);
        paintSegment();
      });
    });
    host.querySelectorAll("[data-seg]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.segment = btn.getAttribute("data-seg");
        syncUrl(state);
        host.querySelectorAll("[data-seg-key]").forEach(function (other) {
          other.classList.toggle("is-active", other.getAttribute("data-seg-key") === state.segment);
        });
        paintSegment();
        body.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    });
  }

  function segmentBody(state, data, inventory, returns, health) {
    const m = data.metrics;
    const currency = data.currency || m.currency;
    const ads = data.ads || { metrics: {}, campaigns: [], topProducts: [] };

    if (state.segment === "orders") return ordersSegment(m, currency, state, data.orders || []);
    if (state.segment === "ads") return adsSegment(ads, currency, state);
    if (state.segment === "inventory") return inventorySegment(inventory);
    if (state.segment === "aftersales") return aftersalesSegment(returns, currency);
    return overviewSegment(m, ads, currency, health, state);
  }

  function bindSegment(state, body, repaint) {
    // 业绩走势的指标切换
    body.querySelectorAll("[data-trend-key]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        body.querySelectorAll("[data-trend-key]").forEach(function (other) {
          other.classList.toggle("is-active", other === btn);
        });
        drawTrend(body, state, btn.getAttribute("data-trend-key"));
      });
    });
    const trendHost = body.querySelector("#st-trend");
    if (trendHost) drawTrend(body, state, "salesAmount");
    const hourHost = body.querySelector("#st-hours");
    if (hourHost && window.CPChart) {
      window.CPChart.bars(hourHost, {
        series: (state.data.metrics.hourDistribution || []).map(function (item) {
          return { hour: item.hour, label: item.hour + " 点", value: item.orderCount };
        }),
        format: "number",
        height: 168,
        label: "24 小时下单分布",
      });
    }
  }

  function drawTrend(body, state, key) {
    const host = body.querySelector("#st-trend");
    if (!host) return;
    const trend = (state.data.metrics.salesTrend || []).map(function (item) {
      return { date: item.date, value: item[key] };
    });
    const isMoney = key === "salesAmount";
    window.CPChart.line(host, {
      series: trend,
      format: isMoney ? "money" : "number",
      currency: state.data.currency,
      height: 232,
      label: "业绩走势",
    });
  }

  function overviewSegment(m, ads, currency, health, state) {
    const sm = m.salesMetrics || {};
    const cell = function (key, formatter, inverse) {
      const item = sm[key] || { value: 0, changePct: null };
      return metric(item.label || key, formatter(item.value), delta(item.changePct, inverse));
    };

    const core =
      cell("salesAmount", function (v) { return money(v, currency); }) +
      cell("unitCount", num) +
      cell("orderCount", num) +
      cell("aov", function (v) { return money(v, currency); }) +
      metric("广告花费", money(ads.metrics.spend || 0, currency), "") +
      metric("ACOS", pctText(ads.metrics.acos || 0), "");

    const trendSwitch = ["salesAmount", "unitCount", "orderCount"].map(function (key) {
      const labels = { salesAmount: "销售额", unitCount: "销量", orderCount: "订单量" };
      return '<button type="button" data-trend-key="' + key + '"' +
        (key === "salesAmount" ? ' class="is-active"' : "") + ">" + labels[key] + "</button>";
    }).join("");

    const daily = (m.salesTrend || []).slice().reverse().map(function (item) {
      return (
        "<tr><td>" + esc(item.date) + "</td>" +
        '<td class="num">' + money(item.salesAmount, currency) + "</td>" +
        '<td class="num">' + num(item.unitCount) + "</td>" +
        '<td class="num">' + num(item.orderCount) + "</td></tr>"
      );
    });

    const healthCells = (health.items || []).map(function (item) {
      return metric(item.label, esc(item.value), "");
    }).join("");

    return (
      card("核心指标", '<div class="st-metrics">' + core + "</div>",
        "对比上一个等长周期 · " + esc(m.range)) +
      card("业绩走势", '<div id="st-trend"></div>',
        '<div class="st-seg" role="group" aria-label="走势指标">' + trendSwitch + "</div>") +
      card("按日明细",
        table([{ label: "日期" }, { label: "销售额", align: "right" }, { label: "销量", align: "right" }, { label: "订单量", align: "right" }],
          daily, { maxHeight: "300px", empty: "这个时间范围内没有出单记录" }),
        m.days + " 天", { flush: true }) +
      (healthCells
        ? card("店铺绩效", '<div class="st-metrics st-metrics--five">' + healthCells + "</div>",
            esc(health.sourceLabel || ""))
        : "")
    );
  }

  function ordersSegment(m, currency, state, orders) {
    const regions = (m.regionDistribution || []).slice(0, 10).map(function (item) {
      return (
        "<tr><td>" + esc(L.site(item.country) || item.country) + "</td>" +
        '<td class="num">' + num(item.orderCount) + "</td>" +
        '<td class="num">' + item.share.toFixed(1) + "%</td></tr>"
      );
    });
    return (
      '<div class="st-grid-2">' +
      card("地区订单分布",
        table([{ label: "地区" }, { label: "订单量", align: "right" }, { label: "占比", align: "right" }], regions,
          { empty: "窗口内没有地区订单" }),
        "窗口内 " + num(m.orders) + " 笔", { flush: true }) +
      card("下单时段分布", '<div id="st-hours"></div>', "当地时间 0-23 点") +
      "</div>" +
      card("订单列表", ordersTable(orders, currency),
        num(m.orders) + " 笔订单" + (orders.length < m.orders ? "（展示最近 " + orders.length + " 笔）" : ""),
        { flush: true })
    );
  }

  function ordersTable(orders, currency) {
    const rows = (orders || []).map(function (order) {
      return (
        "<tr><td>" + esc(order.order_id) + "</td>" +
        "<td>" + esc(order.product_name || order.sku || "—") + "</td>" +
        '<td class="num">' + num(order.quantity) + "</td>" +
        '<td class="num">' + money(order.amount, currency) + "</td>" +
        "<td>" + pill(L.orderStatus(order.status), L.orderTone(order.status)) + "</td>" +
        '<td class="t-muted">' + esc(order.country || "—") + "</td>" +
        '<td class="t-muted">' + esc(U.fmtTime(order.created_at)) + "</td></tr>"
      );
    });
    return table(
      [{ label: "订单号" }, { label: "商品" }, { label: "数量", align: "right" },
       { label: "金额", align: "right" }, { label: "状态" }, { label: "地区" }, { label: "下单时间" }],
      rows, { maxHeight: "420px", empty: "这个时间范围内没有订单" }
    );
  }

  function adsSegment(ads, currency, state) {
    const a = ads.metrics || {};
    // 广告侧目前只出当前窗口，没有上一周期，所以一律不挂环比。
    // 不挂就是干净的；挂一排「无对比」只是噪声。
    const metrics =
      metric("广告花费", money(a.spend || 0, currency)) +
      metric("广告销售额", money(a.adSales || 0, currency)) +
      metric("ACOS", pctText(a.acos || 0)) +
      metric("ROAS", (a.roas || 0).toFixed(2)) +
      metric("曝光量", num(a.impressions || 0)) +
      metric("点击量", num(a.clicks || 0)) +
      metric("CTR", pctText(a.ctr || 0)) +
      metric("CPC", money(a.cpc || 0, currency)) +
      metric("广告订单", num(a.adOrders || 0));

    const top = (ads.topProducts || []).map(function (item) {
      return (
        "<tr><td><div class=\"st-cell-product\"><div>" +
        "<strong>" + esc(item.name) + "</strong><small>" + esc(item.asin || "—") + "</small>" +
        "</div></div></td>" +
        '<td class="num">' + money(item.spend, currency) + "</td>" +
        '<td class="num">' + money(item.sales, currency) + "</td>" +
        '<td class="num">' + pctText(item.acos) + "</td>" +
        '<td class="num">' + num(item.roas) + "</td></tr>"
      );
    });

    const campaigns = (ads.campaigns || []).map(function (item) {
      return (
        "<tr><td>" + esc(item.name) + "</td>" +
        "<td>" + (item.status === "active" ? pill("投放中", "ok") : pill("已暂停", "muted")) + "</td>" +
        '<td class="num">' + num(item.impressions) + "</td>" +
        '<td class="num">' + num(item.clicks) + "</td>" +
        '<td class="num">' + money(item.spend, currency) + "</td>" +
        '<td class="num">' + money(item.sales, currency) + "</td>" +
        '<td class="num">' + pctText(item.acos) + "</td></tr>"
      );
    });

    // 广告活动有 7 列，半宽放不下（销售列会被裁掉），所以两张表都走整宽。
    return (
      card("广告指标", '<div class="st-metrics st-metrics--ads">' + metrics + "</div>", "近 30 天")
      + '<div class="mt-3">' +
        card("广告表现最好的商品",
          table([{ label: "商品" }, { label: "花费", align: "right" }, { label: "广告销售额", align: "right" },
            { label: "ACOS", align: "right" }, { label: "ROAS", align: "right" }], top, { empty: "还没有广告活动" }),
          null, { flush: true }) +
      "</div>" +
      '<div class="mt-3">' +
        card("广告活动",
          table([{ label: "活动" }, { label: "状态" }, { label: "曝光", align: "right" },
            { label: "点击", align: "right" }, { label: "花费", align: "right" },
            { label: "销售额", align: "right" }, { label: "ACOS", align: "right" }], campaigns,
            { maxHeight: "320px", empty: "还没有广告活动" }),
          null, { flush: true }) +
      "</div>"
    );
  }

  function inventorySegment(inventory) {
    const totals = inventory.totals || {};
    const aging = inventory.agingTotals || {};
    const maxAging = Math.max.apply(null, Object.keys(aging).map(function (key) { return aging[key]; }).concat([1]));

    const rows = (inventory.items || []).map(function (item) {
      return (
        "<tr><td><div class=\"st-cell-product\"><div>" +
        "<strong>" + esc(item.name) + "</strong><small>" + esc(item.sku) + "</small>" +
        "</div></div></td>" +
        '<td class="num">' + num(item.available) + "</td>" +
        '<td class="num">' + num(item.reserved) + "</td>" +
        '<td class="num">' + num(item.inbound) + "</td>" +
        '<td class="num">' + num(item.sold30d) + "</td>" +
        '<td class="num">' + (item.turnoverDays === null ? "—" : num(item.turnoverDays)) + "</td>" +
        "<td>" + pill(item.flagLabel, item.level === "ok" ? "ok" : item.level === "danger" ? "danger" : "warning") + "</td></tr>"
      );
    });

    const agingRows = Object.keys(aging).map(function (label) {
      const value = aging[label];
      return (
        '<div class="st-breakdown-row">' +
        '<span class="st-breakdown-name">' + esc(label) + " 天</span>" +
        '<span class="st-breakdown-bar"><span style="width:' + Math.max(2, (value / maxAging) * 100) + '%"></span></span>' +
        '<span class="st-breakdown-value">' + num(value) + " 件</span>" +
        "</div>"
      );
    }).join("");

    return (
      card("库存概览",
        '<div class="st-metrics st-metrics--five">' +
        metric("可售库存", num(totals.available || 0), "") +
        metric("已预留", num(totals.reserved || 0), "") +
        metric("在途库存", num(totals.inbound || 0), "") +
        metric("断货 SKU", num(totals.outOfStock || 0), "") +
        metric("低库存 SKU", num(totals.lowStock || 0), "") +
        "</div>", "") +
      card("库龄分布", '<div class="st-breakdown">' + agingRows + "</div>", "按可售件数") +
      card("库存明细",
        table([{ label: "商品" }, { label: "可售", align: "right" }, { label: "预留", align: "right" },
          { label: "在途", align: "right" }, { label: "30 天销量", align: "right" },
          { label: "可售天数", align: "right" }, { label: "标记" }], rows,
          { maxHeight: "420px", empty: "这个店铺还没有商品" }),
        (inventory.items || []).length + " 个 SKU", { flush: true })
    );
  }

  function aftersalesSegment(returns, currency) {
    const list = returns || [];
    const refunded = list.filter(function (item) { return item.status === "refunded"; });
    const refundAmount = refunded.reduce(function (sum, item) { return sum + Number(item.refund_amount || 0); }, 0);
    const pending = list.length - refunded.length;

    const rows = list.map(function (item) {
      return (
        "<tr><td>" + esc(item.return_id) + "</td>" +
        "<td>" + esc(item.product_name || item.sku || "—") + "</td>" +
        '<td class="num">' + money(item.refund_amount, currency) + "</td>" +
        "<td>" + esc(item.reason) + "</td>" +
        "<td>" + pill(L.returnStatus(item.status), L.returnTone(item.status)) + "</td>" +
        '<td class="t-muted">' + esc(U.fmtTime(item.requested_at)) + "</td></tr>"
      );
    });

    return (
      card("售后概览",
        '<div class="st-metrics st-metrics--three">' +
        metric("售后单量", num(list.length), "") +
        metric("已退款金额", money(refundAmount, currency), "") +
        metric("待处理", num(pending), "") +
        "</div>", "近 30 天") +
      card("售后订单",
        table([{ label: "售后单号" }, { label: "商品" }, { label: "退款金额", align: "right" },
          { label: "原因" }, { label: "状态" }, { label: "申请时间" }], rows,
          { maxHeight: "420px", empty: "这段时间没有售后单" }),
        list.length + " 笔", { flush: true })
    );
  }

  /* ---------------- 子页：单品分析 ---------------- */

  async function paintProduct(root, stage, state) {
    let products = [];
    try {
      products = (await A.get(
        "/api/marketplace/products?limit=100&connection_id=" + encodeURIComponent(state.storeId)
      )).items || [];
    } catch (err) {
      if (state.token === renderSeq) {
        stage.innerHTML = '<div class="callout callout-danger">' + U.icon("alert") +
          "<div>" + esc(err.message) + "</div></div>";
      }
      return;
    }
    if (state.token !== renderSeq) return;
    state.products = products;

    const searchExtra =
      '<span class="st-select st-select--asin">' + U.icon("search") +
      '<input id="st-asin-input" list="st-asin-list" placeholder="搜索 ASIN / SKU / 商品名"' +
      ' value="' + esc(state.asin) + '" aria-label="搜索商品" />' +
      "</span>" +
      '<datalist id="st-asin-list">' +
      products.map(function (item) {
        return '<option value="' + esc(item.asin) + '">' + esc(item.name) + " · " + esc(item.sku) + "</option>";
      }).join("") +
      "</datalist>";

    stage.innerHTML = toolbar(state, searchExtra) + '<div id="st-product"></div>';
    bindToolbar(stage, state, function () { paintProduct(root, stage, state); });

    const input = stage.querySelector("#st-asin-input");
    if (input) {
      input.addEventListener("change", function () {
        state.asin = input.value.trim().toUpperCase();
        syncUrl(state);
        paintProductBody(stage.querySelector("#st-product"), state);
      });
      input.addEventListener("keydown", function (event) {
        if (event.key !== "Enter") return;
        event.preventDefault();
        state.asin = input.value.trim().toUpperCase();
        syncUrl(state);
        paintProductBody(stage.querySelector("#st-product"), state);
      });
    }

    paintProductBody(stage.querySelector("#st-product"), state);
  }

  async function paintProductBody(host, state) {
    if (!host) return;
    if (!state.asin) {
      const rows = state.products.map(function (item) {
        return (
          "<tr><td><div class=\"st-cell-product\"><div>" +
          '<a href="#" data-pick="' + esc(item.asin) + '">' + esc(item.name) + "</a>" +
          "<small>" + esc(item.asin) + " · " + esc(item.sku) + "</small>" +
          "</div></div></td>" +
          '<td class="num">' + money(item.price, item.currency) + "</td>" +
          '<td class="num">' + num(item.rating) + "</td>" +
          '<td class="num">' + num(item.review_count) + "</td>" +
          '<td class="num">' + num(item.stock) + "</td>" +
          "<td>" +
          (item.stock > 0 ? pill("在售", "ok") : pill("无库存", "danger")) +
          "</td></tr>"
        );
      });
      host.innerHTML = card(
        "选择一个商品",
        table([{ label: "商品" }, { label: "价格", align: "right" }, { label: "评分", align: "right" },
          { label: "评论", align: "right" }, { label: "库存", align: "right" }, { label: "状态" }], rows,
          { empty: "这个店铺还没有商品" }),
        state.products.length + " 个商品", { flush: true }
      );
      host.querySelectorAll("[data-pick]").forEach(function (link) {
        link.addEventListener("click", function (event) {
          event.preventDefault();
          state.asin = link.getAttribute("data-pick");
          syncUrl(state);
          const input = document.querySelector("#st-asin-input");
          if (input) input.value = state.asin;
          paintProductBody(host, state);
        });
      });
      return;
    }

    host.innerHTML = loading();
    let detail;
    try {
      detail = await A.get(
        "/api/marketplace/products/" + encodeURIComponent(state.asin) + "/detail?connection_id=" +
        encodeURIComponent(state.storeId)
      );
    } catch (err) {
      host.innerHTML = '<div class="callout callout-danger">' + U.icon("alert") +
        "<div>" + esc(err.message) + "</div></div>";
      return;
    }

    const p = detail.product || {};
    const currency = detail.currency || p.currency;
    const sm = detail.metrics || {};
    const ads = detail.adsMetrics || {};
    const inv = detail.inventory || null;

    const summary =
      '<div class="st-product">' +
      '<span class="st-product-thumb">' + esc(String(p.asin || "?").slice(0, 2)) + "</span>" +
      '<div class="st-product-main">' +
      '<div class="st-product-meta">' + pill(p.asin || "—", "brand") +
      "<span>" + esc(p.sku || "") + "</span></div>" +
      '<h2 class="st-product-title">' + esc(p.name || "") + "</h2>" +
      '<p class="st-product-sub">' + esc(L.platform((detail.store || {}).platform)) +
      (p.marketplace ? " · " + esc(L.site(p.marketplace)) : "") +
      (p.status ? " · " + (p.status === "active" ? "在售" : "已暂停") : "") + "</p>" +
      "</div>" +
      '<dl class="st-product-stats">' +
      "<div><dt>评分</dt><dd>" + num(p.rating) + "<small>/ 5</small></dd></div>" +
      "<div><dt>评论</dt><dd>" + num(p.review_count) + "</dd></div>" +
      "<div><dt>可售库存</dt><dd>" + num(p.stock) + "</dd></div>" +
      "</dl></div>";

    const metrics =
      metric("销售额", money((sm.salesAmount || {}).value, currency), delta((sm.salesAmount || {}).changePct)) +
      metric("销量", num((sm.unitCount || {}).value), delta((sm.unitCount || {}).changePct)) +
      metric("订单量", num((sm.orderCount || {}).value), delta((sm.orderCount || {}).changePct)) +
      metric("广告花费", money(ads.spend || 0, currency)) +
      metric("广告销售额", money(ads.adSales || 0, currency)) +
      metric("可售天数", inv && inv.turnoverDays !== null ? num(inv.turnoverDays) : "—");

    const warnings = (detail.warnings || []).map(function (item) {
      return '<div class="st-note' + (item.level === "danger" ? " st-note--warning" : "") + '">' +
        esc(item.text) + "</div>";
    }).join("");

    const adRows = (detail.ads || []).map(function (item) {
      return (
        "<tr><td>" + esc(item.name) + "</td>" +
        "<td>" + (item.status === "active" ? pill("投放中", "ok") : pill("已暂停", "muted")) + "</td>" +
        '<td class="num">' + num(item.clicks) + "</td>" +
        '<td class="num">' + money(item.spend, currency) + "</td>" +
        '<td class="num">' + money(item.sales, currency) + "</td>" +
        '<td class="num">' + pctText(item.acos) + "</td></tr>"
      );
    });

    host.innerHTML =
      summary +
      (warnings ? '<div class="mt-3">' + warnings + "</div>" : "") +
      card("核心指标", '<div class="st-metrics">' + metrics + "</div>",
        "近 30 天 · 对比上一个周期") +
      card("销售走势", '<div id="st-trend"></div>', "按日") +
      card("广告表现",
        adRows.length
          ? table([{ label: "活动" }, { label: "状态" }, { label: "点击", align: "right" },
            { label: "花费", align: "right" }, { label: "销售额", align: "right" },
            { label: "ACOS", align: "right" }], adRows)
          : '<p class="t-sm t-muted" style="margin:0">这个商品近 30 天没有投放广告。</p>',
        null, { flush: adRows.length > 0 });

    const trendHost = host.querySelector("#st-trend");
    if (trendHost && window.CPChart) {
      window.CPChart.line(trendHost, {
        series: (detail.trend || []).map(function (item) {
          return { date: item.date, value: item.salesAmount };
        }),
        format: "money",
        currency: currency,
        height: 232,
        label: "单品销售走势",
      });
    }
  }

  /* ---------------- 子页：经营明细 ---------------- */

  async function paintLedger(root, stage, state) {
    const ledgerSeg = LEDGERS.map(function (item) {
      return '<button type="button" data-kind="' + item.key + '"' +
        (item.key === state.ledger ? ' class="is-active"' : "") + ">" + esc(item.label) + "</button>";
    }).join("");

    stage.innerHTML =
      toolbar(state, '<div class="st-seg" role="group" aria-label="明细类型">' + ledgerSeg + "</div>") +
      '<div id="st-ledger">' + loading() + "</div>";
    bindToolbar(stage, state, function () { paintLedger(root, stage, state); });

    const host = stage.querySelector("#st-ledger");
    stage.querySelectorAll("[data-kind]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.ledger = btn.getAttribute("data-kind");
        stage.querySelectorAll("[data-kind]").forEach(function (other) {
          other.classList.toggle("is-active", other === btn);
        });
        syncUrl(state);
        loadLedger(host, state);
      });
    });
    loadLedger(host, state);
  }

  async function loadLedger(host, state) {
    if (!host) return;
    host.innerHTML = loading();
    let payload;
    try {
      payload = await A.get(
        "/api/marketplace/ledger?kind=" + encodeURIComponent(state.ledger) +
        "&connection_id=" + encodeURIComponent(state.storeId)
      );
    } catch (err) {
      host.innerHTML = '<div class="callout callout-danger">' + U.icon("alert") +
        "<div>" + esc(err.message) + "</div></div>";
      return;
    }
    const items = payload.items || [];
    const currency = (items[0] && items[0].currency) || "USD";
    const built = buildLedger(state.ledger, items, currency);
    host.innerHTML = card(built.title, built.html, built.extra || (items.length + " 行"), { flush: true });
    built.bind(host);
  }

  function buildLedger(kind, items, currency) {
    if (kind === "listing") {
      const rows = items.map(function (item, index) {
        return (
          "<tr><td><div class=\"st-cell-product\"><div>" +
          "<strong>" + esc(item.name) + "</strong>" +
          "<small>" + esc(item.asin) + " · " + esc(item.sku) + "</small>" +
          "</div></div></td>" +
          '<td class="num">' + money(item.price, item.currency || currency) + "</td>" +
          '<td class="num">' + num(item.rating) + "</td>" +
          '<td class="num">' + num(item.review_count) + "</td>" +
          '<td class="num">' + num(item.stock) + "</td>" +
          "<td>" + (item.status === "active" ? pill("在售", "ok") : pill("已暂停", "muted")) + "</td>" +
          '<td class="num"><button type="button" class="st-detail-toggle" data-expand="' + index + '">' +
          "详情" + U.icon("chevronRight") + "</button></td></tr>"
        );
      });
      return {
        title: "Listing",
        html: table([{ label: "商品" }, { label: "价格", align: "right" }, { label: "评分", align: "right" },
          { label: "评论", align: "right" }, { label: "库存", align: "right" }, { label: "状态" },
          { label: "操作", align: "right" }], rows, { maxHeight: "560px", empty: "这个店铺还没有商品" }),
        bind: function (host) {
          bindExpand(host, 7, items, function (item) {
            return detailPairs([
              ["商品 ID", item.product_id],
              ["ASIN", item.asin],
              ["SKU", item.sku],
              ["站点", L.site(item.marketplace) || item.marketplace],
              ["币种", item.currency],
              ["数据来源", item.is_demo ? "示例目录" : "同步数据"],
            ]);
          });
        },
      };
    }

    if (kind === "orders") {
      const rows = items.map(function (item, index) {
        return (
          "<tr><td>" + esc(item.order_id) + "</td>" +
          "<td>" + esc(item.product_name || item.sku || "—") + "</td>" +
          '<td class="num">' + num(item.quantity) + "</td>" +
          '<td class="num">' + money(item.amount, item.currency || currency) + "</td>" +
          "<td>" + pill(L.orderStatus(item.status), L.orderTone(item.status)) + "</td>" +
          '<td class="t-muted">' + esc(item.country || "—") + "</td>" +
          '<td class="t-muted">' + esc(U.fmtTime(item.created_at)) + "</td>" +
          '<td class="num"><button type="button" class="st-detail-toggle" data-expand="' + index + '">' +
          "详情" + U.icon("chevronRight") + "</button></td></tr>"
        );
      });
      return {
        title: "订单列表",
        html: table([{ label: "订单号" }, { label: "商品" }, { label: "数量", align: "right" },
          { label: "金额", align: "right" }, { label: "状态" }, { label: "地区" },
          { label: "下单时间" }, { label: "操作", align: "right" }], rows,
          { maxHeight: "560px", empty: "这个时间范围内没有订单" }),
        bind: function (host) {
          bindExpand(host, 8, items, function (item) {
            return detailPairs([
              ["订单号", item.order_id],
              ["ASIN", item.asin],
              ["SKU", item.sku],
              ["商品", item.product_name],
              ["数量", item.quantity],
              ["金额", money(item.amount, item.currency || currency)],
              ["履约状态", L.orderStatus(item.status)],
              ["目的国家", item.country],
            ]);
          });
        },
      };
    }

    if (kind === "aftersales") {
      const rows = items.map(function (item, index) {
        return (
          "<tr><td>" + esc(item.return_id) + "</td>" +
          "<td>" + esc(item.product_name || item.sku || "—") + "</td>" +
          '<td class="num">' + money(item.refund_amount, item.currency || currency) + "</td>" +
          "<td>" + esc(item.reason) + "</td>" +
          "<td>" + pill(L.returnStatus(item.status), L.returnTone(item.status)) + "</td>" +
          '<td class="t-muted">' + esc(U.fmtTime(item.requested_at)) + "</td>" +
          '<td class="num"><button type="button" class="st-detail-toggle" data-expand="' + index + '">' +
          "详情" + U.icon("chevronRight") + "</button></td></tr>"
        );
      });
      return {
        title: "售后订单",
        html: table([{ label: "售后单号" }, { label: "商品" }, { label: "退款金额", align: "right" },
          { label: "原因" }, { label: "状态" }, { label: "申请时间" },
          { label: "操作", align: "right" }], rows,
          { maxHeight: "560px", empty: "这段时间没有售后单" }),
        bind: function (host) {
          bindExpand(host, 7, items, function (item) {
            return detailPairs([
              ["售后单号", item.return_id],
              ["原订单号", item.order_id],
              ["ASIN", item.asin],
              ["SKU", item.sku],
              ["退款金额", money(item.refund_amount, item.currency || currency)],
              ["退款原因", item.reason],
              ["状态", L.returnStatus(item.status)],
            ]);
          });
        },
      };
    }

    const rows = items.map(function (item, index) {
      return (
        "<tr><td><div class=\"st-cell-product\"><div>" +
        "<strong>" + esc(item.name) + "</strong><small>" + esc(item.sku) + "</small>" +
        "</div></div></td>" +
        '<td class="num">' + num(item.available) + "</td>" +
        '<td class="num">' + num(item.reserved) + "</td>" +
        '<td class="num">' + num(item.inbound) + "</td>" +
        "<td>" + pill(item.flagLabel, item.level === "ok" ? "ok" : item.level === "danger" ? "danger" : "warning") + "</td>" +
        '<td class="num"><button type="button" class="st-detail-toggle" data-expand="' + index + '">' +
        "库龄" + U.icon("chevronRight") + "</button></td></tr>"
      );
    });
    return {
      title: "库存明细",
      html: table([{ label: "商品" }, { label: "可售", align: "right" }, { label: "预留", align: "right" },
        { label: "在途", align: "right" }, { label: "标记" }, { label: "操作", align: "right" }], rows,
        { maxHeight: "560px", empty: "这个店铺还没有商品" }),
      bind: function (host) {
        bindExpand(host, 6, items, function (item) {
          const aging = item.aging || {};
          const pairs = Object.keys(aging).map(function (key) {
            return [key + " 天", num(aging[key]) + " 件"];
          });
          pairs.push(["30 天销量", num(item.sold30d) + " 件"]);
          pairs.push(["可售天数", item.turnoverDays === null ? "—" : num(item.turnoverDays) + " 天"]);
          return detailPairs(pairs);
        });
      },
    };
  }

  function detailPairs(pairs) {
    return '<dl class="st-detail">' + pairs.map(function (pair) {
      return '<div class="st-detail-row-item"><dt>' + esc(pair[0]) + "</dt><dd>" +
        esc(pair[1] === null || pair[1] === undefined || pair[1] === "" ? "—" : pair[1]) + "</dd></div>";
    }).join("") + "</dl>";
  }

  function bindExpand(host, cols, items, builder) {
    host.querySelectorAll("[data-expand]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const row = btn.closest("tr");
        const next = row.nextElementSibling;
        if (next && next.classList.contains("st-detail-row")) {
          next.remove();
          return;
        }
        const index = Number(btn.getAttribute("data-expand"));
        const item = items[index];
        if (!item) return;
        const tr = document.createElement("tr");
        tr.className = "st-detail-row";
        tr.innerHTML = '<td colspan="' + cols + '">' + builder(item) + "</td>";
        row.after(tr);
      });
    });
  }

  window.CPPageStores = { render: render };
})();
