/* 激浪 · 工作台（真实数据）
 *
 * 版式：KPI 行（任务/报告/Listing/店铺/待审批）+ 任务趋势图 + 最近任务 + 最近报告。
 * 所有数字来自 /api/dashboard；没有数据时保持空态，不显示推测性指标。
 */
(function () {
  "use strict";
  const U = window.CPUi;
  const A = window.CPApi;

  function kpi(label, value, note, first) {
    return (
      `<div class="kpi">` +
      `<div class="kpi-label">${U.esc(label)}</div>` +
      `<div class="kpi-value">${U.esc(value)}</div>` +
      (note ? `<div class="kpi-note">${U.esc(note)}</div>` : "") +
      `</div>`
    );
  }

  /* 图表统一走 js/charts.js 的 CPChart，页面里不再各写一份 SVG 拼装 */

  /* 经营概览：4 个核心指标 + 近 30 天销售额走势，点进去是完整经营看板 */
  function shopOverview(m) {
    const sm = m.salesMetrics || {};
    const currency = m.currency || "USD";
    const money = window.CPChart.moneyFull;

    function deltaTag(value) {
      if (value === null || value === undefined || !isFinite(Number(value))) {
        return `<span class="st-metric-delta is-flat">无对比</span>`;
      }
      const n = Number(value);
      if (Math.abs(n) < 0.05) return `<span class="st-metric-delta is-flat">持平</span>`;
      return `<span class="st-metric-delta ${n > 0 ? "is-good" : "is-bad"}">` +
        `${n > 0 ? "▲" : "▼"} ${Math.abs(n).toFixed(1)}%<span style="opacity:.6"> 环比</span></span>`;
    }

    function cell(key, label, format) {
      const item = sm[key] || { value: 0, changePct: null };
      return (
        `<div class="st-metric">` +
        `<span class="st-metric-label">${U.esc(item.label || label)}</span>` +
        `<span class="st-metric-value">${format(item.value)}</span>` +
        deltaTag(item.changePct) +
        `</div>`
      );
    }

    return (
      `<div class="card" style="margin-top:var(--sp-4)">` +
      `<div class="card-head"><div><div class="card-title">经营概览</div>` +
      `<div class="card-sub">这家店近 ${m.days || 30} 天的销售情况，与上一个等长周期对比</div></div>` +
      `<a class="btn btn-quiet btn-sm" href="/stores" data-link>经营看板</a></div>` +
      `<div class="card-body">` +
      `<div class="st-metrics">` +
      cell("salesAmount", "销售额", function (v) { return money(v, currency); }) +
      cell("unitCount", "销量", function (v) { return window.CPChart.num(v); }) +
      cell("orderCount", "订单量", function (v) { return window.CPChart.num(v); }) +
      cell("aov", "客单价", function (v) { return money(v, currency); }) +
      `</div></div></div>`
    );
  }

  function taskRow(task) {
    return (
      `<tr>` +
      `<td><a href="/tasks/${U.esc(task.task_id)}" data-link><strong>${U.esc(task.title)}</strong></a></td>` +
      `<td class="t-muted">${U.esc(window.CPLabel.taskType(task.type))}</td>` +
      `<td>${U.statusBadge(task.status)}</td>` +
      `<td class="t-muted num">${U.esc(U.fmtTime(task.created_at))}</td>` +
      `</tr>`
    );
  }

  function errorBlock(err) {
    return (
      `<div class="callout callout-danger">${U.icon("alert")}<div>` +
      `<strong>加载失败</strong><br>${U.esc(err.message || String(err))}` +
      `<div class="mt-2"><button type="button" class="btn btn-sm" data-retry>重试</button></div>` +
      `</div></div>`
    );
  }

  async function render(root) {
    root.innerHTML = `<div class="view"><div class="page"><div class="page-inner">` +
      `<div class="skeleton" style="height:92px;margin-bottom:24px"></div>` +
      `<div class="skeleton" style="height:220px;margin-bottom:24px"></div>` +
      `</div></div></div>`;

    // 三个请求互不依赖：一起发出，别串成瀑布。
    // 健康状态与顶栏共用 CPShell.getHealth() 的缓存，首屏只发一次。
    const healthPromise = (window.CPShell && window.CPShell.getHealth)
      ? window.CPShell.getHealth().catch(function () { return null; })
      : A.get("/api/health").catch(function () { return null; });
    const providerPromise = A.get("/api/settings/providers").catch(function () { return null; });

    let data;
    try {
      data = await A.get("/api/dashboard");
    } catch (err) {
      root.innerHTML = `<div class="view"><div class="page"><div class="page-inner">` +
        `<div class="page-head"><div><h1 class="page-title">工作台</h1></div></div>` +
        errorBlock(err) + `</div></div></div>`;
      const retry = root.querySelector("[data-retry]");
      if (retry) retry.addEventListener("click", function () { render(root); });
      return;
    }

    // 进站第一屏就要说清「还差一步：配自己的 Key」，
    // 否则访客看到全空的报告/任务，不知道下一步该做什么。
    const providerInfo = await providerPromise;
    const health = await healthPromise;
    const needsKey = Boolean(providerInfo) &&
      !providerInfo.active_config_id &&
      !(health && health.requires_api_key === false);
    const keyNotice = needsKey
      ? `<div class="callout callout-warn mt-4">${U.icon("alert")}` +
        `<span><strong>还差一步：配置你自己的 API Key。</strong>` +
        `激浪不提供模型额度，竞品分析与 Listing 生成都用你自己的 Key。` +
        `Key 加密保存，只用于你的账号，随时可以删除。` +
        `<a href="/settings" data-link>去「设置 → 模型与密钥」</a> 配置后回到这里发起第一个任务。` +
        `想先看效果？<a href="/workbench" data-link>去 AI 助手用示例数据跑一次</a>。</span></div>`
      : "";

    const stats = data.stats || {};
    const tasks = data.recent_tasks || [];
    const reports = data.recent_reports || [];
    const listings = data.recent_listings || [];
    const daily = data.daily_tasks || [];
    const sources = data.data_sources || [];

    // 经营概览：和「店铺与渠道 → 经营看板」同一套数据，近 30 天
    let shop = null;
    try { shop = await A.get("/api/marketplace/metrics?range=30d"); } catch (err) { shop = null; }
    const shopBlock = shop ? shopOverview(shop) : "";

    const kpis =
      kpi("任务总数", stats.total || 0, "含全部状态", true) +
      kpi("进行中", stats.running || 0, "运行中与排队中") +
      kpi("报告", stats.reports || 0, "竞品分析结果") +
      kpi("Listing", stats.listings || 0, "草稿与版本") +
      kpi("待审批", stats.awaiting_approval || 0, "需要人工确认");

    const taskTable = tasks.length
      ? `<div class="table-wrap"><table class="table"><thead><tr>` +
        `<th>任务</th><th>类型</th><th>状态</th><th class="num">创建</th>` +
        `</tr></thead><tbody>${tasks.map(taskRow).join("")}</tbody></table></div>`
      : `<div class="empty"><span class="empty-icon">${U.icon("tasks")}</span>` +
        `<p class="empty-title">还没有任务</p>` +
        `<p class="empty-desc">在 AI 助手描述一个业务目标，Agent 会依次完成竞品分析、数据核对与 Listing 生成。</p>` +
        `<div class="empty-actions">` +
        `<a class="btn btn-primary btn-sm" href="/workbench" data-link>发起第一个任务</a>` +
        `<a class="btn btn-sm" href="/workbench" data-link>去 AI 助手描述目标</a>` +
        `</div></div>`;

    /* 报告没有独立页面了，点进产出它的那条任务看结果 */
    const reportList = reports.length
      ? reports.map(function (r) {
          const tag = r.task_id ? "a" : "div";
          const link = r.task_id ? ` href="/tasks/${U.esc(r.task_id)}" data-link` : "";
          return (
            `<${tag} class="list-row"${link}>` +
            `<span class="grow"><span class="t-sm">${U.esc(r.product_name)}</span>` +
            `<span class="t-xs">${U.esc(window.CPLabel.platform(r.platform))} · ${U.esc(window.CPLabel.site(r.marketplace))}</span></span>` +
            (r.is_demo ? U.mockFlag() : "") +
            `<span class="t-xs t-faint">${U.esc(U.fmtTime(r.created_at))}</span></${tag}>`
          );
        }).join("")
      : `<div class="empty" style="padding:var(--sp-5)"><span class="empty-icon">${U.icon("file")}</span>` +
        `<p class="empty-title">还没有报告</p>` +
        `<p class="empty-desc">生成第一份竞品分析后，报告会出现在这里。</p></div>`;

    const listingList = listings.length
      ? listings.map(function (l) {
          const tag = l.task_id ? "a" : "div";
          const link = l.task_id ? ` href="/tasks/${U.esc(l.task_id)}" data-link` : "";
          return (
            `<${tag} class="list-row"${link}>` +
            `<span class="grow"><span class="t-sm">${U.esc(l.product_name)}</span>` +
            `<span class="t-xs">${U.esc(window.CPLabel.site(l.marketplace))} · ${U.esc(window.CPLabel.language(l.language))}</span></span>` +
            `<span class="t-xs t-faint">${U.esc(U.fmtTime(l.created_at))}</span></${tag}>`
          );
        }).join("")
      : `<div class="empty" style="padding:var(--sp-5)"><span class="empty-icon">${U.icon("listing")}</span>` +
        `<p class="empty-title">还没有 Listing 草稿</p>` +
        `<p class="empty-desc">基于已确认的商品事实生成，并自动做事实对齐质检。</p>` +
        `<div class="empty-actions"><a class="btn btn-sm" href="/workbench" data-link>去生成</a></div></div>`;

    const sourceRows = sources.length
      ? sources.map(function (s) {
          let badge;
          if (s.mode === "upload") badge = `<span class="badge">你的文件</span>`;
          else if (s.configured && s.mode === "live") badge = `<span class="badge badge-ok">已连接</span>`;
          else if (s.configured) badge = `<span class="badge">示例数据</span>`;
          else badge = `<span class="badge">未设置</span>`;
          return (
            `<div class="src-row"><span class="grow">` +
            `<span class="src-name">${U.esc(s.label)}</span>` +
            `<span class="src-desc">${U.esc(s.detail || "")}</span></span>` +
            `<span class="src-flags">${badge}</span>` +
            `</div>`
          );
        }).join("")
      : "";

    root.innerHTML = `<div class="view"><div class="page"><div class="page-inner">` +
      `<div class="page-head"><div><h1 class="page-title">工作台</h1>` +
      `<p class="page-desc">你的任务、报告与数据生成情况。还没有数据的模块会保持空态。</p></div>` +
      `<div class="page-actions">` +
      `<a class="btn btn-secondary btn-sm" href="/workbench" data-link>${U.icon("sparkles")}去 AI 助手</a>` +
      `</div></div>` +

      keyNotice +

      `<div class="card dash-kpi"><div class="kpi-row">${kpis}</div></div>` +

      shopBlock +

      `<div class="dash-grid">` +
      `<div class="card"><div class="card-head"><div><div class="card-title">任务趋势</div>` +
      `<div class="card-sub">近 14 天每天新建的任务数</div></div>` +
      `<a class="btn btn-quiet btn-sm" href="/tasks" data-link>查看全部</a></div>` +
      `<div class="card-body"><div id="dash-trend"></div></div></div>` +

      `<div class="card"><div class="card-head"><div><div class="card-title">最近报告</div>` +
      `<div class="card-sub">竞品分析结果</div></div></div>` +
      `<div class="list">${reportList}</div></div>` +
      `</div>` +

      `<div class="dash-grid mt-4" style="margin-top:var(--sp-5)">` +
      `<div class="card"><div class="card-head"><div><div class="card-title">近期任务</div>` +
      `<div class="card-sub">最近的执行记录</div></div>` +
      (tasks.length ? `<a class="btn btn-quiet btn-sm" href="/tasks" data-link>查看全部</a>` : "") +
      `</div>${taskTable}</div>` +

      `<div class="col gap-4">` +
      `<div class="card"><div class="card-head"><div class="card-title">最近 Listing</div></div>` +
      `<div class="list">${listingList}</div></div>` +
      `</div></div>` +

      (sourceRows
        ? `<div class="card mt-4" style="margin-top:var(--sp-5)">` +
          `<div class="card-head"><div><div class="card-title">数据源状态</div>` +
          `<div class="card-sub">每个数据域现在用的是哪一份数据</div></div>` +
          `<a class="btn btn-quiet btn-sm" href="/settings#data" data-link>数据源设置</a></div>` +
          `<div class="card-body">${sourceRows}</div></div>`
        : "") +

      `</div></div></div>`;
    window.CPIcon.hydrate(root);

    // 任务趋势图：数据拿到后再画，容器宽度才能实测
    // 全 0 时不要画一条贴底的零线——那是一张「空壳图」，什么信息都没给。
    const trendHost = root.querySelector("#dash-trend");
    if (trendHost && window.CPChart) {
      const hasTrend = daily.some(function (d) { return Number(d.count) > 0; });
      if (!hasTrend) {
        trendHost.innerHTML = '<div class="cp-chart-empty">这 14 天还没有新建任务</div>';
      } else {
        window.CPChart.line(trendHost, {
          series: daily.map(function (d) { return { date: d.date, value: d.count }; }),
          format: "number",
          height: 148,
          label: "近 " + daily.length + " 天任务数量趋势",
        });
      }
    }
  }

  window.CPPageDashboard = { render };
})();
