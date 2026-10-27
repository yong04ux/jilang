/* 激浪 · 任务中心（表格 + 右侧抽屉详情）
 *
 * 保留 /tasks/{id} 深链：直接打开该地址时，列表页先渲染，再把对应任务
 * 的详情抽屉展开——不用整页跳转，从抽屉里也能拿到可分享的 URL。
 */
(function () {
  "use strict";
  const U = window.CPUi;
  const A = window.CPApi;
  const AR = window.CPAsyncRun;

  const FILTERS = [
    { key: "", label: "全部" },
    { key: "running", label: "运行中" },
    { key: "awaiting_approval", label: "等待审批" },
    { key: "waiting_for_input", label: "等待补充资料" },
    { key: "waiting_for_review", label: "等待确认" },
    { key: "partial", label: "待复核" },
    { key: "succeeded", label: "已完成" },
    { key: "failed", label: "失败" },
    { key: "cancelled", label: "已取消" },
  ];

  const state = {
    status: "",
    query: "",
    activeTaskId: null,
    items: [],
    drawer: null,
    poller: null,
  };

  /* 任务类型文案统一来自 CPLabel，避免与工作台不一致 */
  const RESULT_LABEL = {
    competitor_analysis: "报告",
    listing_generation: "草稿",
    agent_workflow: "报告",
    publish_listing: "草稿",
    data_import: "批次",
  };

  const KIND_LABEL = {
    publish_listing: "发布 Listing",
  };

  function typeLabel(type) {
    return window.CPLabel.taskType(type);
  }

  function shell() {
    return (
      `<div class="view"><div class="page"><div class="page-inner">` +
      `<div class="page-head"><div><h1 class="page-title">任务中心</h1>` +
      `<p class="page-desc">所有任务都在这里统一追踪状态、步骤与错误；点击任意一行在右侧抽屉里查看详情。</p></div>` +
      `</div>` +
      `<div class="card">` +
      `<div class="card-head" style="flex-wrap:wrap;gap:12px">` +
      `<div class="chips" id="task-filters"></div>` +
      `<div class="row gap-2">` +
      `<input type="search" class="task-search" id="task-search" placeholder="搜索任务名称" aria-label="搜索任务" />` +
      `<span class="t-xs t-muted" id="task-count" style="white-space:nowrap"></span></div>` +
      `</div>` +
      `<div id="task-body"><div class="card-body">` +
      `<div class="skeleton skeleton-line"></div>` +
      `<div class="skeleton skeleton-line"></div>` +
      `<div class="skeleton skeleton-line"></div></div></div>` +
      `</div></div></div></div>`
    );
  }

  function renderFilters(root) {
    const filters = root.querySelector("#task-filters");
    if (!filters) return;
    filters.innerHTML = FILTERS.map(function (f) {
      return `<button type="button" class="chip${f.key === state.status ? " is-active" : ""}" ` +
        `data-status="${f.key}">${U.esc(f.label)}</button>`;
    }).join("");
  }

  function bind(root) {
    renderFilters(root);

    const filters = root.querySelector("#task-filters");
    filters.addEventListener("click", function (event) {
      const btn = event.target.closest("[data-status]");
      if (!btn) return;
      state.status = btn.getAttribute("data-status");
      filters.querySelectorAll("[data-status]").forEach(function (b) {
        b.classList.toggle("is-active", b.getAttribute("data-status") === state.status);
      });
      load(root);
    });

    const search = root.querySelector("#task-search");
    let timer = null;
    search.addEventListener("input", function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        state.query = search.value.trim();
        load(root);
      }, 250);
    });
  }

  function rowHtml(t) {
    const resultLabel = t.result_ref ? (RESULT_LABEL[t.type] || "记录") : "—";
    return (
      `<tr data-task-row="${U.esc(t.task_id)}" tabindex="0" style="cursor:pointer">` +
      `<td><strong>${U.esc(t.title)}</strong></td>` +
      `<td class="t-muted">${U.esc(typeLabel(t.type))}</td>` +
      `<td class="t-muted">${t.origin === "chat" ? "AI 助手" : t.origin === "seed" ? "示例数据" : "业务页面"}</td>` +
      `<td>${U.statusBadge(t.status)}</td>` +
      `<td class="t-muted num">${U.esc(U.fmtTime(t.created_at))}</td>` +
      `<td class="num t-muted">${U.esc(resultLabel)}</td>` +
      `</tr>`
    );
  }

  async function load(root) {
    const body = root.querySelector("#task-body");
    const count = root.querySelector("#task-count");
    if (!body) return;
    const params = new URLSearchParams();
    if (state.status) params.set("status", state.status);
    if (state.query) params.set("q", state.query);
    let data;
    try {
      data = await A.get("/api/tasks" + (params.toString() ? "?" + params : ""));
    } catch (err) {
      body.innerHTML = `<div class="card-body"><div class="callout callout-danger">${U.icon("alert")}` +
        `<div>加载失败：${U.esc(err.message)}</div></div></div>`;
      return;
    }
    const items = data.items || [];
    state.items = items;
    if (count) count.textContent = `共 ${items.length} 条`;

    if (!items.length) {
      const filtered = Boolean(state.status || state.query);
      body.innerHTML =
        `<div class="empty"><span class="empty-icon">${U.icon("tasks")}</span>` +
        `<p class="empty-title">${filtered ? "没有符合条件的任务" : "还没有任务"}</p>` +
        `<p class="empty-desc">${filtered
          ? "试试清除筛选，或换一个关键词。"
          : "去 AI 助手发起一个任务，或在业务页面直接执行。"}</p>` +
        `<div class="empty-actions">` +
        (filtered
          ? `<button type="button" class="btn btn-sm" id="task-reset">清除筛选</button>`
          : `<a class="btn btn-primary btn-sm" href="/workbench" data-link>发起任务</a>`) +
        `</div></div>`;
      const reset = body.querySelector("#task-reset");
      if (reset) {
        reset.addEventListener("click", function () {
          state.status = "";
          state.query = "";
          const search = root.querySelector("#task-search");
          if (search) search.value = "";
          renderFilters(root);
          load(root);
        });
      }
      window.CPIcon.hydrate(body);
      return;
    }

    body.innerHTML =
      `<div class="table-wrap"><table class="table"><thead><tr>` +
      `<th>任务</th><th>类型</th><th>来源</th><th>状态</th><th class="num">创建</th><th class="num">结果</th>` +
      `</tr></thead><tbody>` + items.map(rowHtml).join("") + `</tbody></table></div>`;
    window.CPIcon.hydrate(body);

    body.querySelectorAll("[data-task-row]").forEach(function (row) {
      const open = function () {
        openDrawer(root, row.getAttribute("data-task-row"));
      };
      row.addEventListener("click", open);
      row.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    });

    renderApprovals(root, body);
  }

  /* 待审批：admin/owner 可直接处理；其他角色只读 */
  async function renderApprovals(root, body) {
    let pending;
    let role = "";
    try {
      const results = await Promise.all([
        A.get("/api/approvals?status=pending"),
        A.get("/api/tenants/current"),
      ]);
      pending = results[0].items || [];
      role = results[1].role || "";
    } catch (err) {
      return;
    }
    if (!pending.length) return;
    const canDecide = role === "admin" || role === "owner";
    const card = document.createElement("div");
    card.className = "card card-pad mb-3";
    card.style.marginBottom = "var(--sp-4)";
    card.innerHTML =
      `<div class="row between wrap gap-2"><div><div class="card-title">待审批（${pending.length}）</div>` +
      `<div class="card-sub">发布 Listing 前需要管理员确认。通过后把内容复制到店铺后台，在那里完成发布。</div></div></div>` +
      `<div class="mt-3">` + pending.map(function (a) {
        const payload = a.payload || {};
        const title = payload.product_name || payload.listing_id || "Listing 发布请求";
        return `<div class="row between wrap gap-2" style="padding:10px 0;border-top:1px solid var(--line)">` +
          `<div><div class="t-sm">${U.esc(title)}</div>` +
          `<div class="t-xs t-muted">${U.esc(KIND_LABEL[a.kind] || "审批请求")} · ${U.esc(U.fmtTime(a.created_at))}</div></div>` +
          (canDecide
            ? `<div class="row gap-2"><button type="button" class="btn btn-sm btn-primary" data-approve="${U.esc(a.approval_id)}">通过</button>` +
              `<button type="button" class="btn btn-sm" data-reject="${U.esc(a.approval_id)}">拒绝</button></div>`
            : `<span class="t-xs t-muted">等待管理员处理</span>`) +
          `</div>`;
      }).join("") + `</div>`;
    body.prepend(card);
    card.addEventListener("click", async function (event) {
      const approve = event.target.closest("[data-approve]");
      const reject = event.target.closest("[data-reject]");
      if (!approve && !reject) return;
      const approvalId = (approve || reject).getAttribute(approve ? "data-approve" : "data-reject");
      const decision = approve ? "approved" : "rejected";
      const button = approve || reject;
      button.disabled = true;
      try {
        await A.post(`/api/approvals/${encodeURIComponent(approvalId)}/decide`, { decision: decision });
        U.toast(decision === "approved" ? "已通过，可以到店铺后台发布了" : "已拒绝", "ok");
        load(root);
      } catch (err) {
        U.toast(err.message, "danger");
        button.disabled = false;
      }
    });
  }

  /* ---------------- 详情抽屉 ---------------- */
  function closeDrawer() {
    if (state.poller) { state.poller.stop(); state.poller = null; }
    if (state.drawer) { state.drawer.remove(); state.drawer = null; }
    const scrim = document.getElementById("task-drawer-scrim");
    if (scrim) scrim.remove();
    state.activeTaskId = null;
  }

  function mountDrawer() {
    closeDrawer();
    const scrim = document.createElement("div");
    scrim.className = "drawer-scrim";
    scrim.id = "task-drawer-scrim";
    scrim.addEventListener("click", closeDrawer);
    document.body.appendChild(scrim);
    const drawer = document.createElement("aside");
    drawer.className = "drawer is-wide";
    drawer.setAttribute("role", "dialog");
    drawer.setAttribute("aria-modal", "true");
    drawer.setAttribute("aria-label", "任务详情");
    drawer.innerHTML =
      `<div class="drawer-head">` +
      `<div class="task-detail-head"><span class="t-section">任务详情</span></div>` +
      `<button type="button" class="btn-icon" id="task-drawer-close" aria-label="关闭">${U.icon("close")}</button>` +
      `</div>` +
      `<div class="drawer-body" id="task-drawer-body">` +
      `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div>` +
      `</div>`;
    document.body.appendChild(drawer);
    drawer.querySelector("#task-drawer-close").addEventListener("click", closeDrawer);
    window.CPIcon.hydrate(drawer);
    document.addEventListener("keydown", function onEsc(event) {
      if (event.key === "Escape") {
        document.removeEventListener("keydown", onEsc);
        closeDrawer();
      }
    });
    state.drawer = drawer;
    return drawer;
  }

  function detailBody(task, steps, result) {
    const canCancel = ["queued", "running", "cancelling"].includes(task.status);

    // 报告与草稿就在本页的结果区，不再往外跳
    const links = [];

    // 失败原因直接展示服务端给的中文说明；不暴露错误码与追踪号
    const errorBlock = task.error_message
      ? `<div class="callout callout-danger mt-3">${U.icon("alert")}<div>` +
        `<strong>这个任务没有完成</strong><br>${U.esc(task.error_message)}` +
        `</div></div>`
      : "";

    const approvalId = (task.output || {}).approval_id;
    const approvalBlock = task.status === "awaiting_approval" && approvalId
      ? `<div class="callout callout-warn mt-3">${U.icon("shield")}` +
        `<div><strong>等待发布审批</strong><br>通过后把内容复制到店铺后台，在那里完成发布。` +
        `<div class="row gap-2 mt-2">` +
        `<button type="button" class="btn btn-sm btn-primary" data-decide="approved">通过</button>` +
        `<button type="button" class="btn btn-sm" data-decide="rejected">拒绝</button>` +
        `</div></div></div>`
      : "";

    return (
      `<div class="row between wrap gap-3">` +
      `<div><div class="row gap-2 wrap"><span class="t-title" style="font-size:var(--fs-lg)">${U.esc(task.title)}</span>` +
      U.statusBadge(task.status) + `</div>` +
      `<div class="t-xs t-muted mt-1">` +
      `${U.esc(typeLabel(task.type))} · ${U.esc(U.fmtTime(task.created_at))}` +
      /* 如实标出这次是规则算的还是模型写的 */
      (result && result.engine ? ` · ${U.esc(result.engine.label)}` : "") +
      `</div></div>` +
      `<div class="row gap-2">${links.join("")}` +
      (canCancel ? `<button type="button" class="btn btn-sm" id="task-cancel">取消任务</button>` : "") +
      `</div></div>` +
      errorBlock + approvalBlock +
      (["queued", "running"].includes(task.status)
        ? `<div class="callout callout-info mt-3">${U.icon("info")}` +
          `<div>任务正在执行。取消会在当前步骤结束后生效，进度会自动刷新。</div></div>`
        : "") +
      (task.status === "cancelling"
        ? `<div class="callout callout-warn mt-3">${U.icon("info")}` +
          `<div>已请求取消，等待当前步骤结束。</div></div>`
        : "") +
      `<hr class="divider mt-4 mb-4" />` +
      `<div class="t-section mb-3">执行步骤</div>` +
      AR.stepList(steps, (result && result.plan) || (task.output || {}).plan || [])
    );
  }

  async function openDrawer(root, taskId) {
    state.activeTaskId = taskId;
    const drawer = mountDrawer();
    const body = drawer.querySelector("#task-drawer-body");

    // 让 URL 可分享；不触发路由重绘
    if (location.pathname !== `/tasks/${taskId}`) {
      history.replaceState({}, "", `/tasks/${taskId}`);
    }

    let data;
    try {
      data = await A.get(`/api/tasks/${encodeURIComponent(taskId)}`);
    } catch (err) {
      body.innerHTML = `<div class="callout callout-danger">${U.icon("alert")}<div>` +
        `<strong>任务加载失败</strong><br>${U.esc(err.message)}</div></div>`;
      return;
    }
    paint(drawer, data);

    if (AR.isRunning((data.task || {}).status)) {
      state.poller = AR.poller({
        taskId: taskId,
        onUpdate: function (detail) { paint(drawer, detail); },
        onDone: function (detail) {
          paint(drawer, detail);
          load(root);
        },
        onError: function () { /* 忽略单次失败，下次轮询继续 */ },
      });
    }
  }

  function paint(drawer, data) {
    const body = drawer.querySelector("#task-drawer-body");
    if (!body) return;
    const task = data.task || {};
    body.innerHTML = detailBody(task, data.steps || [], data.result || {});
    window.CPIcon.hydrate(body);

    body.querySelectorAll("[data-decide]").forEach(function (button) {
      button.addEventListener("click", async function () {
        button.disabled = true;
        const approvalId = (task.output || {}).approval_id;
        try {
          const decision = button.getAttribute("data-decide");
          await A.post(`/api/approvals/${encodeURIComponent(approvalId)}/decide`, { decision: decision });
          U.toast(decision === "approved" ? "已通过（未实际发布）" : "已拒绝", "ok");
          closeDrawer();
        } catch (err) {
          U.toast(err.message, "danger");
          button.disabled = false;
        }
      });
    });

    const cancel = body.querySelector("#task-cancel");
    if (cancel) {
      cancel.addEventListener("click", async function () {
        cancel.disabled = true;
        try {
          const resp = await A.post(`/api/tasks/${encodeURIComponent(task.task_id)}/cancel`, {});
          U.toast(resp.detail || "已请求取消", "ok");
        } catch (err) {
          U.toast(err.message, "danger");
          cancel.disabled = false;
        }
      });
    }
  }

  /* ---------------- 页面入口 ---------------- */
  async function render(root, params) {
    closeDrawer();
    root.innerHTML = shell();
    bind(root);
    await load(root);
    if (params && params.id) openDrawer(root, params.id);
  }

  /* 深链 /tasks/{id}：列表页 + 详情抽屉，而不是整页跳转 */
  function detail(root, params) {
    return render(root, params);
  }

  window.CPPageTasks = { render, detail, closeDrawer };
})();
