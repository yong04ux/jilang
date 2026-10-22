/* 激浪 · 成本与利润测算（真实计算 /api/profit/*）
 *
 * 这一页的全部数字都来自用户填报，不是模拟数据——所以页面上不出现「示例」标记。
 * 反过来，凡是页面自己算出来的结论，都必须能在「计算口径」里被手算复核。
 */
(function () {
  "use strict";
  const U = window.CPUi;
  const A = window.CPApi;

  /* 输入项定义：一处定义，表单与取值共用，避免加字段时改两处 */
  const FIELDS = [
    { key: "selling_price", label: "单件售价", req: true, step: "0.01", min: "0.01", group: "价格" },
    { key: "purchase_cost", label: "采购成本", req: true, step: "0.01", min: "0", group: "价格", help: "含税到仓单价" },
    { key: "shipping_cost", label: "头程运费", step: "0.01", min: "0", group: "价格", help: "整批总运费 ÷ 件数" },
    { key: "packaging_cost", label: "包装耗材", step: "0.01", min: "0", group: "价格" },
    { key: "fulfillment_fee", label: "履约配送费", step: "0.01", min: "0", group: "价格", help: "FBA / 海外仓每单费用" },
    { key: "ad_cost_per_order", label: "广告摊销", step: "0.01", min: "0", group: "价格", help: "每单平均广告花费" },
    { key: "other_cost", label: "其他成本", step: "0.01", min: "0", group: "价格", help: "关税 / VAT / 汇损" },
    { key: "commission_rate", label: "平台佣金率", step: "0.01", min: "0", max: "0.6", group: "比率", help: "填 0.15 表示 15%" },
    { key: "return_rate", label: "退货率", step: "0.01", min: "0", max: "1", group: "比率", help: "填 0.05 表示 5%" },
    { key: "return_handling_cost", label: "退货处理成本", step: "0.01", min: "0", group: "比率", help: "换标 / 弃置 / 回运，单件" },
    { key: "fixed_cost", label: "一次性投入", step: "1", min: "0", group: "目标", help: "开模 / 认证 / 首拍 / 首批备货" },
    { key: "target_margin", label: "目标毛利率", step: "0.01", min: "0", max: "0.9", group: "目标", help: "填 0.2 表示希望 20% 毛利" },
  ];

  const SITES = ["US", "CA", "MX", "DE", "FR", "IT", "ES", "UK", "JP", "SG", "BR"];
  const CURRENCIES = ["USD", "EUR", "GBP", "JPY", "SGD", "BRL", "CNY"];
  const FULFILLMENT = [
    { key: "fba", label: "平台仓配（FBA 类）" },
    { key: "fbm", label: "自发货（海外仓 / 直发）" },
    { key: "self", label: "自营履约（国内直发）" },
  ];

  /* 默认值只用来起算，全部会在页面上可见、可改；没有任何一项是"猜的市场数据" */
  const DEFAULTS = {
    product_name: "",
    marketplace: "US",
    currency: "USD",
    fulfillment: "fba",
    selling_price: 29.99,
    purchase_cost: 8,
    shipping_cost: 2,
    packaging_cost: 0.5,
    fulfillment_fee: 4.5,
    ad_cost_per_order: 3,
    other_cost: 0,
    commission_rate: 0.15,
    return_rate: 0.05,
    return_handling_cost: 1.5,
    fixed_cost: 3000,
    target_margin: 0.2,
  };

  let state = Object.assign({}, DEFAULTS);
  let result = null;
  let timer = null;
  let presets = null;

  function money(value, currency) {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    if (!isFinite(n)) return "—";
    const text = Math.abs(n) >= 1000
      ? n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : n.toFixed(2);
    return (currency ? currency + " " : "") + text;
  }

  function pct(value, digits) {
    if (value === null || value === undefined || value === "") return "—";
    return (Number(value) * 100).toFixed(digits === undefined ? 1 : digits) + "%";
  }

  function signedPct(value) {
    if (value === null || value === undefined) return "—";
    const n = Number(value) * 100;
    const sign = n > 0 ? "+" : "";
    return sign + n.toFixed(1) + " 个点";
  }

  function fieldHtml(item) {
    const value = state[item.key];
    const shown = value === null || value === undefined || value === "" ? "" : value;
    return (
      `<label class="field">` +
      `<span class="field-label">${U.esc(item.label)}` +
      (item.req ? ' <span class="t-danger">*</span>' : "") +
      `</span>` +
      `<input data-p="${item.key}" type="number" inputmode="decimal" ` +
      `step="${item.step}" min="${item.min || ""}" ${item.max ? `max="${item.max}"` : ""} ` +
      `value="${U.esc(shown)}" placeholder="0" />` +
      (item.help ? `<span class="field-help">${U.esc(item.help)}</span>` : "") +
      `</label>`
    );
  }

  function groupHtml(title, keys) {
    const items = FIELDS.filter(function (f) { return keys.indexOf(f.group) >= 0; });
    return (
      `<div class="card card-pad">` +
      `<div class="card-title">${U.esc(title)}</div>` +
      `<div class="grid-2 mt-3">` + items.map(fieldHtml).join("") + `</div>` +
      `</div>`
    );
  }

  function formHtml() {
    const siteOptions = SITES.map(function (s) {
      return `<option value="${s}" ${state.marketplace === s ? "selected" : ""}>${s}</option>`;
    }).join("");
    const currencyOptions = CURRENCIES.map(function (c) {
      return `<option value="${c}" ${state.currency === c ? "selected" : ""}>${c}</option>`;
    }).join("");
    const fulfillmentOptions = FULFILLMENT.map(function (f) {
      return `<option value="${f.key}" ${state.fulfillment === f.key ? "selected" : ""}>${U.esc(f.label)}</option>`;
    }).join("");

    return (
      `<div class="card card-pad">` +
      `<div class="card-title">商品与站点</div>` +
      `<div class="grid-2 mt-3">` +
      `<label class="field"><span class="field-label">商品名称</span>` +
      `<input data-p="product_name" type="text" maxlength="200" value="${U.esc(state.product_name)}" placeholder="例如：折叠收纳箱 60L" /></label>` +
      `<label class="field"><span class="field-label">目标站点</span>` +
      `<select data-p="marketplace">${siteOptions}</select></label>` +
      `<label class="field"><span class="field-label">币种</span>` +
      `<select data-p="currency">${currencyOptions}</select></label>` +
      `<label class="field"><span class="field-label">履约方式</span>` +
      `<select data-p="fulfillment">${fulfillmentOptions}</select></label>` +
      `</div></div>` +
      groupHtml("单价与成本（单件口径）", ["价格"]) +
      groupHtml("费率与退货", ["比率"]) +
      groupHtml("一次性投入与目标", ["目标"])
    );
  }

  function readForm(scope) {
    const next = Object.assign({}, state);
    scope.querySelectorAll("[data-p]").forEach(function (input) {
      const key = input.getAttribute("data-p");
      const raw = input.value;
      if (input.tagName === "SELECT" || input.type === "text") {
        next[key] = raw;
        return;
      }
      if (raw === "") {
        next[key] = key === "target_margin" ? null : 0;
        return;
      }
      const num = Number(raw);
      next[key] = isFinite(num) ? num : 0;
    });
    return next;
  }

  function buildPayload() {
    const payload = {
      product_name: state.product_name || "未命名商品",
      marketplace: state.marketplace,
      currency: state.currency,
      fulfillment: state.fulfillment,
      selling_price: Number(state.selling_price) || 0,
      purchase_cost: Number(state.purchase_cost) || 0,
      shipping_cost: Number(state.shipping_cost) || 0,
      packaging_cost: Number(state.packaging_cost) || 0,
      fulfillment_fee: Number(state.fulfillment_fee) || 0,
      other_cost: Number(state.other_cost) || 0,
      ad_cost_per_order: Number(state.ad_cost_per_order) || 0,
      commission_rate: Number(state.commission_rate) || 0,
      return_rate: Number(state.return_rate) || 0,
      return_handling_cost: Number(state.return_handling_cost) || 0,
      fixed_cost: Number(state.fixed_cost) || 0,
    };
    payload.target_margin =
      state.target_margin === null || state.target_margin === undefined || state.target_margin === ""
        ? null
        : Number(state.target_margin);
    return payload;
  }

  /* ---------------- 结果渲染 ---------------- */

  function kpiRows(r) {
    const tone = r.unit_profit < 0 ? "t-danger" : "";
    return (
      `<div class="kpi-row">` +
      `<div class="kpi"><div class="kpi-label">单件售价</div><div class="kpi-value">${money(r.selling_price, r.currency)}</div></div>` +
      `<div class="kpi"><div class="kpi-label">成本合计</div><div class="kpi-value">${money(r.total_cost, r.currency)}</div></div>` +
      `<div class="kpi"><div class="kpi-label">单件毛利</div><div class="kpi-value ${tone}">${money(r.unit_profit, r.currency)}</div>` +
      `<div class="kpi-note">投入产出比 ${r.roi === null ? "—" : r.roi.toFixed(2)}</div></div>` +
      `<div class="kpi"><div class="kpi-label">毛利率</div><div class="kpi-value ${tone}">${pct(r.margin)}</div></div>` +
      `</div>`
    );
  }

  function costTable(r) {
    const rows = r.cost_breakdown.map(function (item) {
      const flagged = item.source === "assumed"
        ? ' <span class="badge badge-warn">假设</span>'
        : "";
      return (
        `<tr>` +
        `<td><div>${U.esc(item.label)}${flagged}</div>` +
        (item.note ? `<div class="t-xs t-muted">${U.esc(item.note)}</div>` : "") +
        `</td>` +
        `<td class="num">${money(item.amount, r.currency)}</td>` +
        `<td class="num">${pct(item.ratio_to_price)}</td>` +
        `<td class="t-xs t-muted">${U.esc(item.formula)}</td>` +
        `</tr>`
      );
    }).join("");

    return (
      `<div class="table-wrap mt-3"><table class="table">` +
      `<thead><tr><th>成本项</th><th class="num">金额</th><th class="num">占售价</th><th>计算口径</th></tr></thead>` +
      `<tbody>${rows}</tbody>` +
      `<tfoot><tr><td><strong>合计</strong></td>` +
      `<td class="num"><strong>${money(r.total_cost, r.currency)}</strong></td>` +
      `<td class="num">${pct(r.total_cost / r.selling_price)}</td><td></td></tr></tfoot>` +
      `</table></div>`
    );
  }

  function breakEvenBlock(r) {
    const rows = [];
    rows.push(
      `<div class="kv"><span class="kv-k">不亏价</span>` +
      `<span class="kv-v">${r.break_even_price === null ? "—" : money(r.break_even_price, r.currency)}</span></div>` +
      `<p class="t-sm t-muted">${U.esc(r.break_even_note)}</p>`
    );
    rows.push(
      `<div class="kv mt-3"><span class="kv-k">回本销量</span>` +
      `<span class="kv-v">${r.break_even_units === null ? "—" : r.break_even_units + " 件"}</span></div>` +
      `<p class="t-sm t-muted">${U.esc(r.break_even_units_note)}</p>`
    );
    if (r.recommended_price !== null) {
      rows.push(
        `<div class="kv mt-3"><span class="kv-k">目标定价</span>` +
        `<span class="kv-v">${money(r.recommended_price, r.currency)}</span></div>` +
        `<p class="t-sm t-muted">${U.esc(r.recommended_price_note)}</p>`
      );
    } else {
      rows.push(`<p class="t-sm t-muted mt-3">${U.esc(r.recommended_price_note)}</p>`);
    }
    return rows.join("");
  }

  function sensitivityTable(r) {
    if (!r.sensitivity || !r.sensitivity.length) return "";
    const rows = r.sensitivity.map(function (row) {
      const tone = row.margin_change < 0 ? "t-danger" : "t-brand";
      return (
        `<tr>` +
        `<td>${U.esc(row.label)}</td>` +
        `<td class="num">${row.delta > 0 ? "+" : ""}${(row.delta * 100).toFixed(0)}%</td>` +
        `<td class="num">${row.variable === "return_rate" ? pct(row.new_value) : money(row.new_value, r.currency)}</td>` +
        `<td class="num">${money(row.unit_profit, r.currency)}</td>` +
        `<td class="num">${pct(row.margin)}</td>` +
        `<td class="num ${tone}">${signedPct(row.margin_change)}</td>` +
        `</tr>`
      );
    }).join("");

    return (
      `<div class="card card-pad mt-3">` +
      `<div class="card-title">变量敏感性（单个变量 ±10%）</div>` +
      `<div class="card-sub">哪一项最经得起波动、哪一项一碰就亏，看这张表。</div>` +
      `<div class="table-wrap mt-3"><table class="table">` +
      `<thead><tr><th>变量</th><th class="num">变化</th><th class="num">调整后</th>` +
      `<th class="num">单件毛利</th><th class="num">毛利率</th><th class="num">毛利率变化</th></tr></thead>` +
      `<tbody>${rows}</tbody></table></div></div>`
    );
  }

  function notesBlock(r) {
    const parts = [];
    if (r.warnings && r.warnings.length) {
      parts.push(
        `<div class="callout callout-warn mt-3">${U.icon("alert")}<div>` +
        `<strong>这些数会影响结论的可靠性</strong><ul class="limit-list">` +
        r.warnings.map(function (w) { return `<li>${U.esc(w)}</li>`; }).join("") +
        `</ul></div></div>`
      );
    }
    parts.push(
      `<div class="card card-pad mt-3">` +
      `<div class="card-title">计算口径</div>` +
      `<div class="card-sub">每一项都能手算复核，对不上说明输入有问题。</div>` +
      `<ul class="limit-list mt-3">` +
      r.derivation.map(function (d) { return `<li>${U.esc(d)}</li>`; }).join("") +
      `</ul>` +
      (r.assumptions && r.assumptions.length
        ? `<div class="t-xs t-muted mt-3">前提假设：` +
          r.assumptions.map(function (a) { return U.esc(a); }).join("；") + `</div>`
        : "") +
      `</div>`
    );
    return parts.join("");
  }

  function renderResult(scope) {
    const host = scope.querySelector("[data-result]");
    if (!host) return;
    if (!result) {
      host.innerHTML =
        `<div class="card"><div class="empty">` +
        `<span class="empty-icon">${U.icon("data")}</span>` +
        `<p class="empty-title">还没有测算结果</p>` +
        `<p class="empty-desc">左侧填好售价与各项成本，结果会即时出现在这里；「计算口径」会写清每个数字是怎么来的。</p>` +
        `</div></div>`;
      window.CPIcon.hydrate(host);
      return;
    }
    const r = result;
    host.innerHTML =
      `<div class="card card-pad">` +
      `<div class="row between"><div class="card-title">${U.esc(r.product_name)} · ${U.esc(r.marketplace)} 站</div>` +
      `<div class="t-xs t-muted">估算值 · ${U.esc(r.fulfillment_label)}</div></div>` +
      kpiRows(r) +
      costTable(r) +
      `</div>` +
      `<div class="card card-pad mt-3"><div class="card-title">盈亏平衡与定价</div>` +
      breakEvenBlock(r) + `</div>` +
      sensitivityTable(r) +
      notesBlock(r);
    window.CPIcon.hydrate(host);
  }

  /* ---------------- 交互 ---------------- */

  function runCalc(scope) {
    const payload = buildPayload();
    clearTimeout(timer);
    timer = setTimeout(function () {
      A.post("/api/profit/calc", payload)
        .then(function (data) {
          result = data;
          renderResult(scope);
        })
        .catch(function (err) {
          const host = scope.querySelector("[data-result]");
          if (host) {
            host.innerHTML = `<div class="callout callout-danger">${U.icon("alert")}` +
              `<div><strong>算不出来</strong><br>${U.esc(err.message)}</div></div>`;
            window.CPIcon.hydrate(host);
          }
        });
    }, 260);
  }

  function savePlan(scope) {
    const titleInput = scope.querySelector("[data-plan-title]");
    const title = titleInput ? titleInput.value.trim() : "";
    A.post("/api/profit/plans?title=" + encodeURIComponent(title), buildPayload())
      .then(function () {
        U.toast("方案已保存", "ok");
        loadPlans(scope);
      })
      .catch(function (err) { U.toast(err.message, "danger"); });
  }

  function loadPlans(scope) {
    const host = scope.querySelector("[data-plans]");
    if (!host) return;
    A.get("/api/profit/plans?limit=8")
      .then(function (data) {
        const items = (data && data.items) || [];
        if (!items.length) {
          host.innerHTML = `<p class="t-sm t-muted">还没有保存的方案。填好参数后点「保存方案」，以后可以回来对比不同定价。</p>`;
          return;
        }
        host.innerHTML = items.map(function (item) {
          const s = item.summary || {};
          return (
            `<div class="list-row"><div class="grow">` +
            `<div class="t-sm">${U.esc(item.title || "未命名")}</div>` +
            `<div class="t-xs t-muted">售价 ${money(s.selling_price, s.currency)} · 毛利 ${pct(s.margin)} · ${U.esc(U.fmtTime(item.created_at))}</div>` +
            `</div><button type="button" class="btn btn-sm btn-quiet" data-open="${U.esc(item.report_id)}">打开</button>` +
            `<button type="button" class="btn-icon" data-drop="${U.esc(item.report_id)}" aria-label="删除">${U.icon("close")}</button>` +
            `</div>`
          );
        }).join("");
        window.CPIcon.hydrate(host);

        host.querySelectorAll("[data-open]").forEach(function (btn) {
          btn.addEventListener("click", function () {
            A.get("/api/profit/plans/" + btn.getAttribute("data-open"))
              .then(function (row) {
                const input = row.input || {};
                Object.keys(input).forEach(function (key) {
                  if (key in state) state[key] = input[key];
                });
                const form = scope.querySelector("[data-form]");
                if (form) form.innerHTML = formHtml();
                bindForm(scope);
                result = row.payload || null;
                renderResult(scope);
                U.toast("已载入方案", "ok");
              })
              .catch(function (err) { U.toast(err.message, "danger"); });
          });
        });
        host.querySelectorAll("[data-drop]").forEach(function (btn) {
          btn.addEventListener("click", function () {
            A.del("/api/profit/plans/" + btn.getAttribute("data-drop"))
              .then(function () { U.toast("已删除", "ok"); loadPlans(scope); })
              .catch(function (err) { U.toast(err.message, "danger"); });
          });
        });
      })
      .catch(function () {
        host.innerHTML = `<p class="t-sm t-muted">方案列表暂时取不到。</p>`;
      });
  }

  function bindForm(scope) {
    scope.querySelectorAll("[data-p]").forEach(function (input) {
      const handler = function () {
        state = readForm(scope);
        runCalc(scope);
      };
      input.addEventListener("input", handler);
      input.addEventListener("change", handler);
    });
  }

  function render(container) {
    container.innerHTML =
      `<div class="view"><div class="page"><div class="page-inner">` +
      `<div class="page-head"><div>` +
      `<div class="page-title">成本与利润测算</div>` +
      `<p class="page-desc">先把账算清楚再上架。填的是你自己的成本，算出来的是单件经济模型——不亏价、回本销量、目标定价和每一项的敏感度。</p>` +
      `</div></div>` +
      `<div class="grid-2">` +
      `<div><div data-form>${formHtml()}</div>` +
      `<div class="card card-pad mt-3"><div class="card-title">保存这套方案</div>` +
      `<div class="card-sub">保存后可以回头对比不同定价与成本结构。</div>` +
      `<div class="row gap-2 mt-3">` +
      `<input data-plan-title class="grow" type="text" maxlength="120" placeholder="方案名称，例如：收纳箱 60L · 美国站" />` +
      `<button type="button" class="btn btn-primary" data-save>保存方案</button>` +
      `</div></div>` +
      `<div class="card card-pad mt-3"><div class="card-title">已保存的方案</div>` +
      `<div class="mt-3" data-plans></div></div>` +
      `</div>` +
      `<div data-result></div>` +
      `</div>` +
      `</div></div></div>`;

    bindForm(container);
    container.querySelector("[data-save]").addEventListener("click", function () {
      savePlan(container);
    });
    loadPlans(container);
    runCalc(container);
    window.CPIcon.hydrate(container);

    if (presets === null) {
      A.get("/api/profit/presets").then(function (data) { presets = data; }).catch(function () {
        presets = null;
      });
    }
  }

  window.CPPageProfit = { render };
})();
