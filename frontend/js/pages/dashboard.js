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

  /* 近 14 天任务趋势：内联 SVG 面积图，无第三方库 */
  function trendChart(daily) {
    const series = daily && daily.length ? daily : [];
    const width = 640;
    const height = 148;
    const padL = 8;
    const padR = 8;
    const padT = 12;
    const padB = 22;
    if (!series.length) {
      return `<div class="empty" style="padding:var(--sp-5) 0">` +
        `<p class="t-sm t-muted">还没有任务数据，趋势图会在第一个任务完成后出现。</p></div>`;
    }
    const values = series.map(function (d) { return Number(d.count) || 0; });
    const max = Math.max.apply(null, values.concat([1]));
    const innerW = width - padL - padR;
    const innerH = height - padT - padB;
    const stepX = series.length > 1 ? innerW / (series.length - 1) : 0;

    const points = series.map(function (d, i) {
      const x = padL + stepX * i;
      const ratio = (Number(d.count) || 0) / max;
      const y = padT + innerH - ratio * innerH;
      return { x: x, y: y, value: Number(d.count) || 0, label: d.date || "" };
    });

    const line = points.map(function (p, i) {
      return `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    }).join(" ");
    const area = line +
      ` L${points[points.length - 1].x.toFixed(1)},${(padT + innerH).toFixed(1)}` +
      ` L${points[0].x.toFixed(1)},${(padT + innerH).toFixed(1)} Z`;

    const gridLines = [0, 0.5, 1].map(function (ratio) {
      const y = padT + innerH - ratio * innerH;
      return `<line class="trend-grid" x1="${padL}" y1="${y.toFixed(1)}" x2="${(width - padR).toFixed(1)}" y2="${y.toFixed(1)}" />`;
    }).join("");

    const dots = points.map(function (p) {
      return `<circle class="trend-point" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.6">` +
        `<title>${U.esc(p.label)} · ${p.value} 个任务</title></circle>`;
    }).join("");

    const first = points[0];
    const last = points[points.length - 1];
    const axis = `<text class="trend-axis" x="${padL}" y="${height - 4}">${U.esc(first.label)}</text>` +
      `<text class="trend-axis" x="${(width - padR).toFixed(1)}" y="${height - 4}" text-anchor="end">${U.esc(last.label)}</text>` +
      `<text class="trend-axis" x="${padL}" y="${(padT - 2).toFixed(1)}">最多 ${max}</text>`;

    return (
      `<svg class="trend" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" ` +
      `aria-label="近 ${series.length} 天任务数量趋势">` +
      `<defs><linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">` +
      `<stop offset="0" stop-color="#1B6EF3" stop-opacity="0.18"/>` +
      `<stop offset="1" stop-color="#1B6EF3" stop-opacity="0"/>` +
      `</linearGradient></defs>` +
      gridLines +
      `<path class="trend-area" d="${area}" />` +
      `<path class="trend-line" d="${line}" />` +
      dots + axis +
      `</svg>`
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
    const providerInfo = await A.get("/api/settings/providers").catch(function () { return null; });
    const health = await A.get("/api/health").catch(function () { return null; });
    const needsKey = Boolean(providerInfo) &&
      !providerInfo.active_config_id &&
      !(health && health.requires_api_key === false);
    const keyNotice = needsKey
      ? `<div class="callout callout-warn mt-4">${U.icon("alert")}` +
        `<span><strong>还差一步：配置你自己的 API Key。</strong>` +
        `激浪不提供模型额度，竞品分析与 Listing 生成都用你自己的 Key。` +
        `Key 加密保存，只用于你的账号，随时可以删除。` +
        `<a href="/settings" data-link>去「设置 → 模型与密钥」</a> 配置后回到这里发起第一个任务。` +
        `想先看效果？<a href="/competitors" data-link>用示例数据跑一次竞品分析</a>。</span></div>`
      : "";

    const stats = data.stats || {};
    const tasks = data.recent_tasks || [];
    const reports = data.recent_reports || [];
    const listings = data.recent_listings || [];
    const daily = data.daily_tasks || [];
    const sources = data.data_sources || [];

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
        `<p class="empty-desc">在 AI 助手描述一个业务目标，或在竞品分析页手动填写参数。</p>` +
        `<div class="empty-actions">` +
        `<a class="btn btn-primary btn-sm" href="/workbench" data-link>发起第一个任务</a>` +
        `<a class="btn btn-sm" href="/competitors" data-link>手动分析竞品</a>` +
        `</div></div>`;

    const reportList = reports.length
      ? reports.map(function (r) {
          return (
            `<a class="list-row" href="/competitors?report=${U.esc(r.report_id)}" data-link>` +
            `<span class="grow"><span class="t-sm">${U.esc(r.product_name)}</span>` +
            `<span class="t-xs">${U.esc(window.CPLabel.platform(r.platform))} · ${U.esc(window.CPLabel.site(r.marketplace))}</span></span>` +
            (r.is_demo ? U.mockFlag() : "") +
            `<span class="t-xs t-faint">${U.esc(U.fmtTime(r.created_at))}</span></a>`
          );
        }).join("")
      : `<div class="empty" style="padding:var(--sp-5)"><span class="empty-icon">${U.icon("file")}</span>` +
        `<p class="empty-title">还没有报告</p>` +
        `<p class="empty-desc">生成第一份竞品分析后，报告会出现在这里。</p></div>`;

    const listingList = listings.length
      ? listings.map(function (l) {
          return (
            `<a class="list-row" href="/listings?listing=${U.esc(l.listing_id)}" data-link>` +
            `<span class="grow"><span class="t-sm">${U.esc(l.product_name)}</span>` +
            `<span class="t-xs">${U.esc(window.CPLabel.site(l.marketplace))} · ${U.esc(window.CPLabel.language(l.language))}</span></span>` +
            `<span class="t-xs t-faint">${U.esc(U.fmtTime(l.created_at))}</span></a>`
          );
        }).join("")
      : `<div class="empty" style="padding:var(--sp-5)"><span class="empty-icon">${U.icon("listing")}</span>` +
        `<p class="empty-title">还没有 Listing 草稿</p>` +
        `<p class="empty-desc">基于已确认的商品事实生成，并自动做事实对齐质检。</p>` +
        `<div class="empty-actions"><a class="btn btn-sm" href="/listings" data-link>去生成</a></div></div>`;

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

      `<div class="dash-grid">` +
      `<div class="card"><div class="card-head"><div><div class="card-title">任务趋势</div>` +
      `<div class="card-sub">近 14 天每天新建的任务数</div></div>` +
      `<a class="btn btn-quiet btn-sm" href="/tasks" data-link>查看全部</a></div>` +
      `<div class="card-body">${trendChart(daily)}</div></div>` +

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
  }

  window.CPPageDashboard = { render };
})();
