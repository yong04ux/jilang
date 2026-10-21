/* 激浪 · 其余页面（Agent / Skills / 店铺与渠道 / 开发中占位） */
(function () {
  "use strict";
  const U = window.CPUi;
  const A = window.CPApi;
  const C = window.CPCatalog;

  function pageShell(title, desc, actions, body) {
    return (
      `<div class="page"><div class="page-inner">` +
      `<div class="page-head"><div><h1 class="page-title">${U.esc(title)}</h1>` +
      `<p class="page-desc">${desc}</p></div>` +
      `<div class="page-actions">${actions || ""}</div></div>` +
      body + `</div></div>`
    );
  }

  function soonPage(title, desc, stage, alternatives) {
    const alts = alternatives.map(function (a) {
      return `<a class="btn btn-sm" href="${a.path}" data-link>${U.esc(a.label)}</a>`;
    }).join("");
    return pageShell(
      title, desc, "",
      `<div class="card card-pad"><div class="empty">` +
      `<span class="empty-icon">${U.icon("clock")}</span>` +
      `<p class="empty-title">该能力正在开发中</p>` +
      `<p class="empty-desc">计划在<strong>${U.esc(stage)}</strong>实现。在此之前，你可以先使用已接入的替代路径。</p>` +
      `<div class="empty-actions">${alts}</div></div></div>`
    );
  }

  /* ---------------- Agent（读注册表） ---------------- */
  async function agents(root) {
    root.innerHTML = `<div class="view">${pageShell(
      "Agent 市场",
      "Agent 定义来自注册表（agent_definitions），不是前端硬编码。", "",
      `<div class="skeleton skeleton-line" style="height:160px"></div>`
    )}</div>`;

    let items = [];
    let error = null;
    try {
      items = (await A.get("/api/agents")).items || [];
    } catch (err) {
      error = err;
    }

    if (error) {
      root.innerHTML = `<div class="view">${pageShell("Agent 市场", "", "",
        `<div class="callout callout-danger">${U.icon("alert")}<div>加载失败：${U.esc(error.message)}</div></div>`
      )}</div>`;
      return;
    }

    const cards = items.map(function (a) {
      const beta = a.status === "beta";
      const skillList = (a.skill_keys || []).map(function (s) {
        return `<span class="tag">${U.esc(s)}</span>`;
      }).join("");
      return (
        `<div class="card card-pad">` +
        `<div class="row between"><div class="row gap-2">` +
        `<span class="skill-icon">${U.esc((a.name || a.agent_key).slice(0, 1))}</span>` +
        `<div><div class="t-section">${U.esc(a.name)}</div>` +
        `<div class="t-xs t-muted t-mono">${U.esc(a.agent_key)} · v${U.esc(a.version)}</div></div></div>` +
        `<span class="badge ${beta ? "badge-warn" : "badge-ok"}">${beta ? "Beta" : "可用"}</span></div>` +
        `<p class="t-sm t-soft mt-3">${U.esc(a.summary)}</p>` +
        (a.description ? `<p class="t-xs t-muted mt-2">${U.esc(a.description)}</p>` : "") +
        (skillList ? `<div class="skill-tags mt-3">${skillList}</div>` : "") +
        `<div class="row gap-2 mt-3">` +
        `<button type="button" class="btn btn-sm" data-agent-run="${U.esc(a.agent_key)}">用此 Agent 运行</button>` +
        `</div></div>`
      );
    }).join("");

    root.innerHTML = `<div class="view">${pageShell(
      "Agent 市场",
      "定义来自注册表；运行由 LangGraph 编排，步骤会写入任务记录。",
      `<a class="btn btn-sm" href="/workbench" data-link>去 AI 助手</a>`,
      `<div class="card-grid-3">${cards || '<p class="t-sm t-muted">注册表为空</p>'}</div>` +
      `<div class="callout callout-info mt-4">${U.icon("info")}` +
      `<span>可视化编排器（DAG 编辑）仍未实现；当前是固定工作流 + 确定性计划。</span></div>`
    )}</div>`;
    window.CPIcon.hydrate(root);

    root.querySelectorAll("[data-agent-run]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const key = btn.getAttribute("data-agent-run");
        window.CPRouter.go(`/workbench?agent=${encodeURIComponent(key)}`);
      });
    });
  }

  /* ---------------- Skills（读注册表） ---------------- */
  async function skills(root) {
    root.innerHTML = `<div class="view">${pageShell(
      "Skills 技能库", "每个技能对应一个可复用能力，被 Agent 调用，也被独立页面调用。", "",
      `<div class="skeleton skeleton-line" style="height:140px"></div>`
    )}</div>`;

    let items = [];
    try {
      items = (await A.get("/api/skills")).items || [];
    } catch (err) {
      root.innerHTML = `<div class="view">${pageShell("Skills 技能库", "", "",
        `<div class="callout callout-danger">${U.icon("alert")}<div>加载失败：${U.esc(err.message)}</div></div>`
      )}</div>`;
      return;
    }

    const rows = items.map(function (s) {
      return `<tr><td><strong>${U.esc(s.name)}</strong>` +
        `<div class="t-xs t-muted">${U.esc(s.summary)}</div>` +
        `<div class="t-xs t-faint t-mono">${U.esc(s.skill_key)}</div></td>` +
        `<td class="t-mono" style="white-space:nowrap">v${U.esc(s.version)}</td>` +
        `<td>${s.status === "available"
          ? '<span class="badge badge-ok">可用</span>'
          : '<span class="badge">开发中</span>'}</td></tr>`;
    }).join("");

    root.innerHTML = `<div class="view">${pageShell(
      "Skills 技能库",
      "定义来自注册表（skill_definitions）；输入输出 schema 可在详情接口查看。", "",
      `<div class="card"><div class="table-wrap"><table class="table"><thead><tr>` +
      `<th>技能</th><th>版本</th><th>状态</th>` +
      `</tr></thead><tbody>${rows || '<tr><td colspan="3" class="t-muted">注册表为空</td></tr>'}</tbody></table></div></div>` +
      `<div class="callout callout-info mt-4">${U.icon("info")}` +
      `<span>「可用」的技能可在 Agent 工作流中真实调用；自定义技能与租户级覆盖尚未实现。</span></div>`
    )}</div>`;
    window.CPIcon.hydrate(root);
  }

  /* ---------------- 店铺与渠道（真实 API + Mock 徽章） ---------------- */
  async function stores(root) {
    root.innerHTML = `<div class="view">${pageShell(
      "店铺与渠道",
      "展示连接状态、数据源模式与同步状态。Mock 模式与真实 API 必须明确区分。", "",
      `<div class="skeleton skeleton-line" style="height:160px"></div>`
    )}</div>`;

    let connections = [];
    let sources = [];
    let overview = null;
    let catalog = [];
    let defaultPlatform = "amazon";
    let error = null;
    try {
      const data = await A.get("/api/stores");
      connections = data.items || [];
    } catch (err) { error = err; }
    try {
      const meta = await A.get("/api/platforms");
      catalog = meta.catalog || [];
      defaultPlatform = meta.default_platform || "amazon";
    } catch (err) { /* 目录拿不到就退回内置列表 */ }
    try { sources = (await A.get("/api/marketplace/sources")).items || []; } catch (err) { /* 忽略 */ }
    if (connections.some(function (c) { return c.mode === "mock"; })) {
      try { overview = await A.get("/api/marketplace/overview"); } catch (err) { /* 忽略 */ }
    }

    if (error) {
      root.innerHTML = `<div class="view">${pageShell("店铺与渠道", "", "",
        `<div class="callout callout-danger">${U.icon("alert")}<div>加载失败：${U.esc(error.message)}</div></div>`
      )}</div>`;
      return;
    }

    const connRows = connections.map(function (c) {
      const summary = c.last_sync_summary || {};
      const platformLabel = c.platform_label || c.platform;
      const summaryLine = summary.products
        ? ` · 商品 ${summary.products} · 订单 ${summary.orders || 0}` +
          ` · 收入 $${Number(summary.revenue || 0).toFixed(2)}` +
          (summary.avg_order_value ? ` · 客单价 $${Number(summary.avg_order_value).toFixed(2)}` : "")
        : "";
      return (
        `<div class="src-row"><span class="grow">` +
        `<span class="src-name">${U.esc(c.shop_name)} <span class="t-mono t-xs t-faint">${U.esc(platformLabel)} · ${U.esc(c.marketplace)}</span></span>` +
        `<span class="src-desc">状态 ${U.esc(c.status)}` +
        (c.last_sync_at ? ` · 最后同步 ${U.esc(U.fmtTime(c.last_sync_at))}` : " · 尚未同步") +
        summaryLine +
        (c.last_sync_error ? ` · <span class="t-danger">${U.esc(c.last_sync_error)}</span>` : "") +
        `</span></span>` +
        `<span class="src-mode">${U.esc(c.mode)}</span>` +
        (c.is_demo ? `<span class="badge">示例店铺</span>` : "") +
        (!c.platform_known ? `<span class="badge">自定义平台</span>` : "") +
        (c.mode === "mock" ? `<span class="badge badge-mock">Mock</span>`
          : `<span class="badge">未接入 · 待审核</span>`) +
        `<button type="button" class="btn btn-sm" data-sync="${U.esc(c.connection_id)}">同步</button>` +
        `</div>`
      );
    }).join("");

    const sourceRows = sources.map(function (s) {
      const mock = s.mode === "mock";
      return (
        `<div class="src-row"><span class="grow">` +
        `<span class="src-name">${U.esc(s.label)}</span>` +
        `<span class="src-desc">${U.esc(s.detail)}</span></span>` +
        `<span class="src-mode">${U.esc(s.mode)}</span>` +
        (mock && s.configured ? `<span class="badge badge-mock">Mock</span>`
          : s.mode === "upload" ? `<span class="badge">用户上传</span>`
          : `<span class="badge">未接入</span>`) +
        `</div>`
      );
    }).join("");

    let productTable = "";
    if (overview) {
      const rows = (overview.products || []).map(function (p) {
        return `<tr><td><strong>${U.esc(p.name)}</strong>` +
          `<div class="t-xs t-faint t-mono">${U.esc(p.asin)}</div></td>` +
          `<td class="num">$${Number(p.price).toFixed(2)}</td>` +
          `<td class="num">${Number(p.rating).toFixed(1)}</td>` +
          `<td class="num">${p.review_count}</td>` +
          `<td class="num">${p.stock}</td>` +
          `<td>${p.is_mock ? U.mockFlag() : ""}</td></tr>`;
      }).join("");
      const metrics = overview.metrics || {};
      productTable =
        `<div class="card mt-4"><div class="card-head"><div>` +
        `<div class="card-title">商品与经营指标</div>` +
        `<div class="card-sub">数据来自 ${U.esc((overview.provider || {}).name || "Provider")}` +
        `${metrics.is_mock ? " · 全部为模拟数据" : ""}</div></div>` +
        `<span class="badge badge-mock">Mock</span></div>` +
        `<div class="card-body">` +
        `<div class="metric-grid mb-4">` +
        `<div class="metric-cell"><div class="metric-label">订单</div><div class="metric-value">${U.esc(metrics.orders || 0)}</div><div class="metric-note">近 ${U.esc(metrics.days || 30)} 天</div></div>` +
        `<div class="metric-cell"><div class="metric-label">销量</div><div class="metric-value">${U.esc(metrics.units || 0)}</div><div class="metric-note">件</div></div>` +
        `<div class="metric-cell"><div class="metric-label">收入</div><div class="metric-value">$${U.esc(Number(metrics.revenue || 0).toFixed(2))}</div><div class="metric-note">${U.esc(metrics.currency || "USD")}</div></div>` +
        `<div class="metric-cell"><div class="metric-label">客单价</div><div class="metric-value">$${U.esc(Number(metrics.aov || 0).toFixed(2))}</div><div class="metric-note">平均</div></div>` +
        `</div>` +
        (rows
          ? `<div class="table-wrap"><table class="table"><thead><tr>` +
            `<th>商品</th><th class="num">价格</th><th class="num">评分</th>` +
            `<th class="num">评论</th><th class="num">库存</th><th>来源</th>` +
            `</tr></thead><tbody>${rows}</tbody></table></div>`
          : `<p class="t-sm t-muted">没有商品数据。</p>`) +
        `<p class="t-xs t-muted mt-3">${U.esc(metrics.note || "")}</p>` +
        `</div></div>`;
    }

    root.innerHTML = `<div class="view">${pageShell(
      "店铺与渠道",
      "展示连接状态、数据源模式与同步状态。Mock 模式与真实 API 必须明确区分。",
      `<button type="button" class="btn btn-sm" id="store-new">${U.icon("plus")}新建 Mock 连接</button>`,
      `<div class="card"><div class="card-head"><div><div class="card-title">店铺连接</div>` +
      `<div class="card-sub">${connections.length ? `${connections.length} 个连接` : "当前没有任何真实店铺授权"}</div></div></div>` +
      `<div class="card-body">` +
      (connRows || `<div class="empty"><span class="empty-icon">${U.icon("stores")}</span>` +
        `<p class="empty-title">还没有连接</p>` +
        `<p class="empty-desc">可以创建一个 Mock 连接来体验商品/订单/指标接口；真实平台授权需要应用审核，本期未接入。</p></div>`) +
      `<div id="store-form"></div>` +
      `</div></div>` +

      (sourceRows
        ? `<div class="card mt-4"><div class="card-head"><div>` +
          `<div class="card-title">各数据域的数据源</div>` +
          `<div class="card-sub">「数据可以模拟，标记必须真实」</div></div></div>` +
          `<div class="card-body">${sourceRows}</div></div>`
        : "") +
      productTable +
      `<div class="callout callout-warn mt-4">${U.icon("alert")}` +
      `<span><strong>当前未接入真实 SP-API。</strong>页面不会显示"已连接 Amazon"之类文案；` +
      `Mock 连接产生的数据全部带 <code>Mock</code> 徽章，不代表真实经营数据。` +
      (catalog.length
        ? `平台目录已声明 ${catalog.length} 个平台的字段名、站点与能力（<code>/api/platforms</code>），` +
          `但授权与取数均未实现，标「示例店铺」的是内置演示目录数据。`
        : "") +
      `</span></div>`
    )}</div>`;
    window.CPIcon.hydrate(root);

    const newBtn = root.querySelector("#store-new");
    if (newBtn) {
      // 平台与站点都来自后端目录（/api/platforms 的 catalog）：新增平台不用改前端
      const platformList = catalog.length ? catalog : [
        { key: "amazon", label: "Amazon", marketplaces: ["US"] },
        { key: "ebay", label: "eBay", marketplaces: ["EBAY_US"] },
        { key: "walmart", label: "Walmart Marketplace", marketplaces: ["US"] },
        { key: "shopee", label: "Shopee", marketplaces: ["SG"] },
      ];
      newBtn.addEventListener("click", function () {
        const box = root.querySelector("#store-form");
        box.innerHTML =
          `<form id="store-create" class="card card-pad mt-4">` +
          `<div class="card-title">新建 Mock 连接</div>` +
          `<div class="card-sub">Mock 连接用固定种子生成确定性数据，全部带 is_mock 标记</div>` +
          `<div class="grid-2 mt-3">` +
          `<label class="field"><span class="field-label">平台</span>` +
          `<select name="platform">` +
          platformList.map(function (p) {
            return `<option value="${U.esc(p.key)}"` +
              (p.key === defaultPlatform ? " selected" : "") +
              `>${U.esc(p.label || p.key)}</option>`;
          }).join("") + `</select></label>` +
          `<label class="field"><span class="field-label">站点</span>` +
          `<select name="marketplace"></select></label>` +
          `<label class="field field-span-2"><span class="field-label">店铺名称 <span class="t-danger">*</span></span>` +
          `<input name="shop_name" required placeholder="例如 Demo Store" /></label>` +
          `</div>` +
          `<div class="row gap-2 mt-3">` +
          `<button type="submit" class="btn btn-primary btn-sm">创建</button>` +
          `<button type="button" class="btn btn-quiet btn-sm" id="store-cancel">取消</button>` +
          `</div></form>`;
        window.CPIcon.hydrate(box);
        const platformSelect = box.querySelector('[name="platform"]');
        const marketSelect = box.querySelector('[name="marketplace"]');
        const fillMarkets = function () {
          const spec = platformList.filter(function (p) {
            return p.key === platformSelect.value;
          })[0];
          const list = (spec && spec.marketplaces && spec.marketplaces.length)
            ? spec.marketplaces : ["US"];
          marketSelect.innerHTML = list.map(function (m) {
            return `<option value="${U.esc(m)}">${U.esc(m)}</option>`;
          }).join("");
        };
        fillMarkets();
        platformSelect.addEventListener("change", fillMarkets);
        const cancel = box.querySelector("#store-cancel");
        if (cancel) cancel.addEventListener("click", function () { box.innerHTML = ""; });
        box.querySelector("#store-create").addEventListener("submit", async function (event) {
          event.preventDefault();
          const form = event.target;
          try {
            await A.post("/api/stores", {
              platform: form.platform.value,
              marketplace: form.marketplace.value.trim().toUpperCase() || "US",
              shop_name: form.shop_name.value.trim(),
              mode: "mock",
            });
            U.toast("Mock 连接已创建（数据带 Mock 标记）", "ok");
            stores(root);
          } catch (err) {
            U.toast(err.message, "danger");
          }
        });
      });
    }

    root.querySelectorAll("[data-sync]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        btn.textContent = "同步中…";
        try {
          const result = await A.post(`/api/stores/${encodeURIComponent(btn.getAttribute("data-sync"))}/sync`, {});
          U.toast(`同步完成：${result.products || 0} 个商品 / ${result.orders || 0} 个订单（Mock）`, "ok");
          stores(root);
        } catch (err) {
          U.toast(err.message, "danger");
          btn.disabled = false;
          btn.textContent = "同步";
        }
      });
    });
  }

  function notFound(root, path) {
    root.innerHTML = `<div class="view">${pageShell(
      "页面不存在",
      `路径 <code>${U.esc(path)}</code> 没有对应页面。`,
      `<a class="btn btn-secondary btn-sm" href="/dashboard" data-link>回到工作台</a>`,
      `<div class="card"><div class="empty"><span class="empty-icon">${U.icon("search")}</span>` +
      `<p class="empty-title">404</p><p class="empty-desc">检查地址是否正确，或从侧栏重新进入。</p></div></div>`
    )}</div>`;
  }

  window.CPPages = { agents, skills, stores, notFound, soonPage, pageShell };
})();
