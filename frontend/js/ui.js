/* 激浪 · 轻量 UI 工具（转义、Toast、格式化、DOM 助手） */
(function () {
  "use strict";

  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function el(html) {
    const tpl = document.createElement("template");
    tpl.innerHTML = html.trim();
    return tpl.content.firstElementChild;
  }

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  /* ---- Toast ---- */
  let toastHost = null;
  function toast(message, tone) {
    if (!toastHost) {
      toastHost = document.createElement("div");
      toastHost.className = "toast-host";
      toastHost.setAttribute("aria-live", "polite");
      document.body.appendChild(toastHost);
    }
    const icon = tone === "danger" ? "alert" : tone === "ok" ? "check" : "info";
    const node = el(
      `<div class="toast ${tone === "danger" ? "toast-danger" : tone === "ok" ? "toast-ok" : ""}" role="status">` +
      `<span data-icon="${icon}"></span><span>${esc(message)}</span></div>`
    );
    if (window.CPIcon) window.CPIcon.hydrate(node);
    toastHost.appendChild(node);
    window.setTimeout(function () {
      node.style.opacity = "0";
      node.style.transition = "opacity 160ms";
      window.setTimeout(function () { node.remove(); }, 180);
    }, 3200);
  }

  /* ---- 复制 ---- */
  async function copy(text, label) {
    try {
      await navigator.clipboard.writeText(text);
      toast((label || "内容") + "已复制", "ok");
    } catch (err) {
      toast("复制失败，请手动选择文本", "danger");
    }
  }

  /* ---- 格式化 ---- */
  function fmtMs(ms) {
    if (ms === null || ms === undefined) return "—";
    if (ms < 1000) return ms + " ms";
    const s = ms / 1000;
    return (s >= 10 ? s.toFixed(0) : s.toFixed(1)) + " s";
  }

  function fmtBytes(bytes) { return bytes + " / 250"; }

  function byteLen(text) {
    try {
      return new TextEncoder().encode(String(text || "")).length;
    } catch (err) {
      return String(text || "").length;
    }
  }

  function fmtTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function fmtDuration(ms) {
    if (ms === null || ms === undefined) return "—";
    return ms < 1000 ? ms + " ms" : (ms / 1000).toFixed(1) + " s";
  }

  /* ---- 状态徽章 ---- */
  const STATUS = {
    queued:            { label: "排队中",   cls: "badge" },
    running:           { label: "运行中",   cls: "badge badge-running" },
    awaiting_approval: { label: "等待审批", cls: "badge badge-warn" },
    succeeded:         { label: "已完成",   cls: "badge badge-ok" },
    failed:            { label: "失败",     cls: "badge badge-danger" },
    cancelling:        { label: "正在取消", cls: "badge badge-warn" },
    cancelled:         { label: "已取消",   cls: "badge" },
    pending:           { label: "等待中",   cls: "badge" },
    skipped:           { label: "已跳过",   cls: "badge" },
  };

  function statusBadge(status) {
    const meta = STATUS[status] || STATUS.queued;
    return `<span class="${meta.cls}">${esc(meta.label)}</span>`;
  }

  function statusLabel(status) {
    return (STATUS[status] || STATUS.queued).label;
  }

  /* ---- 图标 ---- */
  function icon(name, cls) {
    return window.CPIcon ? window.CPIcon.svg(name, null, cls) : "";
  }

  /* ---- 示例数据标记 ---- */
  function mockFlag() {
    return '<span class="mock-flag" title="示例数据，不代表真实业务数据">示例</span>';
  }

  window.CPUi = {
    esc, el, $, $$, toast, copy, fmtMs, fmtBytes, fmtTime, fmtDuration, byteLen,
    statusBadge, statusLabel, icon, mockFlag, STATUS,
  };
})();
