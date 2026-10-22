/* 激浪 · 其余页面（Agent 市场 / 技能库 / 店铺与渠道）
 *
 * 展示约定：页面上只出现用户能理解的概念——
 * 能力名称、要不要准备什么、会得到什么、现在能不能用。
 * 内部标识（key / version / schema / 子系统名）一律不进入 DOM。
 */
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

  /* ---------------- Agent 市场 ---------------- */
  async function agents(root) {
    root.innerHTML = `<div class="view">${pageShell(
      "Agent 市场",
      "选一个 Agent 来执行你的目标。它会调用合适的能力，过程会写进任务记录。", "",
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
      // 只展示中文能力名；目录里没有的（历史遗留 key）直接不出现
      const skillTags = (a.skill_keys || [])
        .map(function (k) { return C.SKILL_NAME[k]; })
        .filter(Boolean)
        .map(function (n) { return `<span class="tag">${U.esc(n)}</span>`; })
        .join("");
      return (
        `<div class="card card-pad">` +
        `<div class="row between gap-2">` +
        `<div class="row gap-2">` +
        `<span class="skill-icon">${U.esc((a.name || "?").slice(0, 1))}</span>` +
        `<span class="t-section">${U.esc(a.name)}</span></div>` +
        `<button type="button" class="btn btn-sm" data-agent-run="${U.esc(a.agent_key)}">用此 Agent 运行</button>` +
        `</div>` +
        `<p class="t-sm t-soft mt-3">${U.esc(a.summary)}</p>` +
        (a.description ? `<p class="t-xs t-muted mt-2">${U.esc(a.description)}</p>` : "") +
        (skillTags ? `<div class="skill-tags mt-3">${skillTags}</div>` : "") +
        `</div>`
      );
    }).join("");

    root.innerHTML = `<div class="view">${pageShell(
      "Agent 市场",
      "选一个 Agent 来执行你的目标。它会调用合适的能力，过程会写进任务记录。",
      `<a class="btn btn-sm" href="/workbench" data-link>去 AI 助手</a>`,
      `<div class="card-grid-3">${cards || '<p class="t-sm t-muted">暂没有可用的 Agent</p>'}</div>`
    )}</div>`;
    window.CPIcon.hydrate(root);

    root.querySelectorAll("[data-agent-run]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const key = btn.getAttribute("data-agent-run");
        window.CPRouter.go(`/workbench?agent=${encodeURIComponent(key)}`);
      });
    });
  }

  /* ---------------- 技能库 ---------------- */
  async function skills(root) {
    root.innerHTML = `<div class="view">${pageShell(
      "Skills 技能库",
      "激浪能完成的任务。每个能力都可以单独使用，也会在 AI 助手对话里根据你的目标自动调用。", "",
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

    const usable = items.filter(function (s) { return s.status === "available"; });
    const rows = usable.map(function (s) {
      const def = C.SKILLS.filter(function (x) { return x.key === s.skill_key; })[0] || {};
      return (
        `<tr><td><strong>${U.esc(s.name)}</strong>` +
        `<div class="t-xs t-muted">${U.esc(s.summary)}</div></td>` +
        `<td class="t-xs t-soft">${U.esc(def.input || "—")}</td>` +
        `<td class="t-xs t-soft">${U.esc(def.output || "—")}</td></tr>`
      );
    }).join("");

    root.innerHTML = `<div class="view">${pageShell(
      "Skills 技能库",
      "激浪能完成的任务。每个能力都可以单独使用，也会在 AI 助手对话里根据你的目标自动调用。", "",
      `<div class="card"><div class="table-wrap"><table class="table"><thead><tr>` +
      `<th>能做什么</th><th>你需要准备</th><th>你会得到</th>` +
      `</tr></thead><tbody>` +
      (rows || '<tr><td colspan="3" class="t-muted">暂没有可用的技能</td></tr>') +
      `</tbody></table></div></div>`
    )}</div>`;
    window.CPIcon.hydrate(root);
  }

  /* ---------------- 店铺与渠道 ---------------- */
  async function stores(root) {
    root.innerHTML = `<div class="view">${pageShell(
      "店铺与渠道",
      "添加店铺后可同步商品与订单；也可以先添加一个示例店铺，把整个流程走通。", "",
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
    } catch (err) { /* 拿不到目录就退回内置平台列表 */ }
    try { sources = (await A.get("/api/marketplace/sources")).items || []; } catch (err) { /* 忽略 */ }
    if (connections.some(function (c) { return c.mode === "mock" || c.is_demo; })) {
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
      const counts = [];
      if (summary.products) counts.push(`商品 ${summary.products}`);
      if (summary.orders) counts.push(`订单 ${summary.orders}`);
      const sample = Boolean(c.is_demo) || c.mode === "mock";
      return (
        `<div class="src-row"><span class="grow">` +
        `<span class="src-name">${U.esc(c.shop_name)} ` +
        `<span class="t-xs t-muted">${U.esc(platformLabel)} · ${U.esc(c.marketplace)}</span></span>` +
        `<span class="src-desc">` +
        (c.last_sync_at ? `最后同步 ${U.esc(U.fmtTime(c.last_sync_at))}` : "还没同步过") +
        (counts.length ? ` · ${counts.join(" · ")}` : "") +
        (c.last_sync_error
          ? ` · <span class="t-danger">上次同步失败：${U.esc(c.last_sync_error)}</span>`
          : "") +
        `</span></span>` +
        `<span class="src-flags">` +
        (sample ? `<span class="badge">示例店铺</span>` : `<span class="badge badge-ok">已连接</span>`) +
        (!c.platform_known ? `<span class="badge">自定义平台</span>` : "") +
        `</span>` +
        `<button type="button" class="btn btn-sm" data-sync="${U.esc(c.connection_id)}">同步</button>` +
        `</div>`
      );
    }).join("");

    const sourceRows = sources.map(function (s) {
      let badge;
      if (s.mode === "upload") badge = `<span class="badge">你的文件</span>`;
      else if (s.configured && s.mode === "live") badge = `<span class="badge badge-ok">已连接</span>`;
      else if (s.configured) badge = `<span class="badge">示例数据</span>`;
      else badge = `<span class="badge">未设置</span>`;
      return (
        `<div class="src-row"><span class="grow">` +
        `<span class="src-name">${U.esc(s.label)}</span>` +
        `<span class="src-desc">${U.esc(s.detail)}` +
        (s.last_sync_at ? ` · 最后同步 ${U.esc(U.fmtTime(s.last_sync_at))}` : "") +
        `</span></span>` +
        `<span class="src-flags">${badge}</span>` +
        `</div>`
      );
    }).join("");

    let productTable = "";
    if (overview) {
      const rows = (overview.products || []).map(function (p) {
        return `<tr><td><strong>${U.esc(p.name)}</strong></td>` +
          `<td class="num">$${Number(p.price).toFixed(2)}</td>` +
          `<td class="num">${Number(p.rating).toFixed(1)}</td>` +
          `<td class="num">${p.review_count}</td>` +
          `<td class="num">${p.stock}</td></tr>`;
      }).join("");
      productTable =
        `<div class="card mt-4"><div class="card-head"><div>` +
        `<div class="card-title">示例店铺的商品</div>` +
        `<div class="card-sub">用来试用同步与分析流程，不是你店铺里的商品</div></div></div>` +
        `<div class="card-body">` +
        (rows
          ? `<div class="table-wrap"><table class="table"><thead><tr>` +
            `<th>商品</th><th class="num">价格</th><th class="num">评分</th>` +
            `<th class="num">评论</th><th class="num">库存</th>` +
            `</tr></thead><tbody>${rows}</tbody></table></div>`
          : `<p class="t-sm t-muted">还没有拉取到商品，点上面的「同步」试试。</p>`) +
        `</div></div>`;
    }

    root.innerHTML = `<div class="view">${pageShell(
      "店铺与渠道",
      "添加店铺后可同步商品与订单；也可以先添加一个示例店铺，把整个流程走通。",
      `<button type="button" class="btn btn-primary btn-sm" id="store-new">${U.icon("plus")}添加店铺</button>`,
      `<div class="card"><div class="card-head"><div><div class="card-title">店铺连接</div>` +
      `<div class="card-sub">${connections.length ? `${connections.length} 个店铺` : "还没有添加店铺"}</div></div></div>` +
      `<div class="card-body">` +
      (connRows || `<div class="empty"><span class="empty-icon">${U.icon("stores")}</span>` +
        `<p class="empty-title">还没有添加店铺</p>` +
        `<p class="empty-desc">添加一个示例店铺就能看到同步商品与订单的完整流程；` +
        `也可以直接去「数据资产」导入你自己的商品文件。</p>` +
        `<div class="empty-actions">` +
        `<button type="button" class="btn btn-sm btn-primary" id="store-new-empty">添加示例店铺</button>` +
        `<a class="btn btn-sm" href="/data" data-link>去导入文件</a>` +
        `</div></div>`) +
      `<div id="store-form"></div>` +
      `</div></div>` +

      (sourceRows
        ? `<div class="card mt-4"><div class="card-head"><div>` +
          `<div class="card-title">各数据域的数据来源</div>` +
          `<div class="card-sub">每个数据域现在用的是哪一份数据</div></div></div>` +
          `<div class="card-body">${sourceRows}</div></div>`
        : "") +
      productTable
    )}</div>`;
    window.CPIcon.hydrate(root);

    const newBtns = root.querySelectorAll("#store-new, #store-new-empty");
    if (newBtns.length) {
      // 平台与站点来自后端的平台目录：新增平台不用改前端
      const platformList = catalog.length ? catalog : [
        { key: "amazon", label: "Amazon", marketplaces: ["US"] },
        { key: "ebay", label: "eBay", marketplaces: ["EBAY_US"] },
        { key: "walmart", label: "Walmart Marketplace", marketplaces: ["US"] },
        { key: "shopee", label: "Shopee", marketplaces: ["SG"] },
      ];
      newBtns.forEach(function (newBtn) {
        newBtn.addEventListener("click", function () {
          const box = root.querySelector("#store-form");
          box.innerHTML =
            `<form id="store-create" class="card card-pad mt-4">` +
            `<div class="card-title">添加示例店铺</div>` +
            `<div class="card-sub">示例店铺带一组固定的示例商品，用来试用同步、竞品分析与 Listing 生成。</div>` +
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
            `<input name="shop_name" required placeholder="例如 我的试用店铺" /></label>` +
            `</div>` +
            `<div class="row gap-2 mt-3">` +
            `<button type="submit" class="btn btn-primary btn-sm">添加</button>` +
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
              U.toast("示例店铺已添加", "ok");
              stores(root);
            } catch (err) {
              U.toast(err.message, "danger");
            }
          });
        });
      });
    }

    root.querySelectorAll("[data-sync]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        btn.textContent = "同步中…";
        try {
          const result = await A.post(`/api/stores/${encodeURIComponent(btn.getAttribute("data-sync"))}/sync`, {});
          U.toast(`同步完成：${result.products || 0} 个商品 / ${result.orders || 0} 个订单`, "ok");
          stores(root);
        } catch (err) {
          U.toast(err.message, "danger");
          btn.disabled = false;
          btn.textContent = "同步";
        }
      });
    });
  }

  function notFound(root) {
    root.innerHTML = `<div class="view">${pageShell(
      "页面不存在",
      "这个地址没有对应的页面，可能是链接过期，或者地址输错了。",
      `<a class="btn btn-secondary btn-sm" href="/dashboard" data-link>回到工作台</a>`,
      `<div class="card"><div class="empty"><span class="empty-icon">${U.icon("search")}</span>` +
      `<p class="empty-title">没有找到这个页面</p>` +
      `<p class="empty-desc">可以从左侧导航重新进入，或者回到工作台继续。</p></div></div>`
    )}</div>`;
  }

  window.CPPages = { agents, skills, stores, notFound, pageShell };
})();
