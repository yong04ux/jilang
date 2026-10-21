/* 激浪 · AsyncRunPanel
 *
 * 三个异步入口（Agent 工作流 / 竞品分析 / Listing 生成）共用同一套行为：
 * 1. 提交后立即用返回的 plan 渲染"计划骨架"；
 * 2. 每 1 秒轮询 GET /api/tasks/{id}，步骤按真实 task_steps 点亮；
 * 3. 可取消（POST /api/tasks/{id}/cancel）；
 * 4. 终态后交给调用方渲染结果，并保留"查看任务"深链。
 *
 * 不伪造进度：进度条只存在于"未完成"这种不确定状态，百分比永远不出现。
 */
(function () {
  "use strict";
  const U = window.CPUi;

  const RUNNING = { queued: 1, running: 1, cancelling: 1 };
  const POLL_MS = 1000;

  const STEP_ICON = {
    succeeded: "check",
    running: "play",
    failed: "x",
    cancelled: "stop",
    skipped: "clock",
    pending: "clock",
  };

  function stepList(steps, plan) {
    if (steps && steps.length) {
      return (
        `<ul class="timeline">` +
        steps.map(function (s) {
          return (
            `<li class="timeline-item is-${U.esc(s.status)}">` +
            `<span class="timeline-dot">${U.icon(STEP_ICON[s.status] || "clock")}</span>` +
            `<div class="timeline-body"><div class="timeline-head">` +
            `<span class="timeline-name">${s.seq}. ${U.esc(s.name)}</span>` +
            U.statusBadge(s.status) +
            (s.duration_ms !== null && s.duration_ms !== undefined
              ? `<span class="timeline-meta">${U.fmtDuration(s.duration_ms)}</span>`
              : "") +
            `</div>` +
            (s.detail ? `<div class="timeline-detail">${U.esc(s.detail)}</div>` : "") +
            `</div></li>`
          );
        }).join("") +
        `</ul>`
      );
    }
    // 尚未产生真实步骤：只展示计划名称，明确标注"等待"
    const names = plan || [];
    if (!names.length) return `<p class="t-sm t-muted">等待执行器创建任务…</p>`;
    return (
      `<ul class="timeline">` +
      names
        .map(function (name, index) {
          const label = window.CPAsyncRun.planLabel(name);
          return (
            `<li class="timeline-item is-pending">` +
            `<span class="timeline-dot">${U.icon("clock")}</span>` +
            `<div class="timeline-body"><div class="timeline-head">` +
            `<span class="timeline-name">${index + 1}. ${U.esc(label)}</span>` +
            U.statusBadge("pending") +
            `</div></div></li>`
          );
        })
        .join("") +
      `</ul>`
    );
  }

  const PLAN_LABELS = {
    resolve: "解析目标",
    analyze: "竞品分析",
    integrity: "数据完整性检查",
    summary: "生成市场机会总结",
    persist: "保存报告与任务记录",
    listing: "生成 Listing",
    quality: "质量检查",
    save_listing: "保存草稿",
  };

  function planLabel(name) {
    return PLAN_LABELS[name] || name;
  }

  /**
   * 创建一个轮询器。
   * @param {object} opts
   *   taskId      任务 id
   *   onUpdate(detail) 每次拿到任务详情时回调
   *   onDone(detail)   终态回调（只触发一次）
   *   onError(err)     轮询失败回调
   */
  function poller(opts) {
    const state = { timer: null, stopped: false, done: false };
    const taskId = opts.taskId;

    function stop() {
      state.stopped = true;
      if (state.timer) {
        window.clearTimeout(state.timer);
        state.timer = null;
      }
    }

    async function tick() {
      if (state.stopped) return;
      let detail;
      try {
        detail = await window.CPApi.get(`/api/tasks/${encodeURIComponent(taskId)}`);
      } catch (err) {
        if (opts.onError) opts.onError(err);
        return;
      }
      if (state.stopped) return;
      if (opts.onUpdate) opts.onUpdate(detail);
      const status = (detail.task || {}).status || "";
      if (!RUNNING[status]) {
        if (!state.done) {
          state.done = true;
          if (opts.onDone) opts.onDone(detail);
        }
        return;
      }
      state.timer = window.setTimeout(tick, POLL_MS);
    }

    tick();
    return { stop: stop, get stopped() { return state.stopped; } };
  }

  /** 取消任务；返回后端给出的可读说明。 */
  async function cancel(taskId) {
    const resp = await window.CPApi.post(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, {});
    return (resp && resp.detail) || "已请求取消";
  }

  /**
   * 统一的结果面板骨架：步骤 / 数据 / 原始 三个 Tab。
   * pages 只需要传 renderData / renderRaw 两个函数。
   */
  function resultTabs(opts) {
    const active = opts.active || "steps";
    const tabs = [
      { key: "steps", label: "步骤" },
      { key: "data", label: "数据" },
      { key: "raw", label: "原始" },
    ];
    return (
      `<div class="res-tabs" role="tablist">` +
      tabs
        .map(function (t) {
          return (
            `<button type="button" class="res-tab${t.key === active ? " is-active" : ""}" ` +
            `data-res-tab="${t.key}" role="tab" aria-selected="${t.key === active}">${t.label}</button>`
          );
        })
        .join("") +
      `</div>`
    );
  }

  window.CPAsyncRun = {
    RUNNING,
    poller,
    cancel,
    stepList,
    planLabel,
    resultTabs,
    isRunning: (status) => Boolean(RUNNING[status]),
  };
})();
