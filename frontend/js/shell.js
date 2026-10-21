/* 激浪 · 应用外壳：200px 文字侧栏 + 顶栏 + 数据来源提示条 */
(function () {
  "use strict";
  const U = window.CPUi;
  const C = window.CPCatalog;

  const LABELS = {};
  C.NAV.forEach(function (g) {
    g.items.forEach(function (item) { LABELS[item.key] = item.label; });
  });

  const BRAND = "激浪";
  const COLLAPSE_KEY = "cp.sidebar.collapsed";
  const BANNER_KEY = "cp.banner.dismissed";

  function isCollapsed() {
    try { return localStorage.getItem(COLLAPSE_KEY) === "1"; } catch (err) { return false; }
  }

  function setCollapsed(value) {
    try { localStorage.setItem(COLLAPSE_KEY, value ? "1" : "0"); } catch (err) { /* 忽略 */ }
    const app = document.querySelector(".app");
    if (app) app.classList.toggle("is-collapsed", value);
  }

  function renderSidebar() {
    const bar = document.getElementById("sidebar");
    if (!bar) return;
    const byKey = {};
    C.NAV.forEach(function (g) { g.items.forEach(function (i) { byKey[i.key] = i; }); });

    const groups = C.NAV.map(function (group) {
      const items = group.items.map(function (item) {
        return (
          `<a class="nav-item${item.soon ? " is-soon" : ""}" href="${item.path}" data-link data-nav="${item.key}" ` +
          `title="${U.esc(item.label)}${item.soon ? "（开发中）" : ""}">` +
          U.icon(item.icon) +
          `<span class="nav-item-label">${U.esc(item.label)}</span>` +
          (item.soon ? `<span class="nav-soon">开发中</span>` : "") +
          `</a>`
        );
      }).join("");
      return (
        `<div class="sidebar-group">` +
        `<div class="sidebar-group-title">${U.esc(group.group)}</div>` +
        items +
        `</div>`
      );
    }).join("");

    bar.innerHTML =
      `<div class="sidebar-head">` +
      `<a class="sidebar-brand" href="/dashboard" data-link aria-label="${BRAND} 首页">` +
      `<img src="/media/logo-mark.svg?v=2" alt="" width="28" height="28" />` +
      `<span class="sidebar-brand-text">${BRAND}</span></a>` +
      `<button type="button" class="btn-icon" id="sidebar-toggle" aria-label="收起侧栏" ` +
      `aria-expanded="${isCollapsed() ? "false" : "true"}">${U.icon("chevronLeft")}</button>` +
      `</div>` +
      `<nav class="sidebar-nav" aria-label="主导航">${groups}</nav>` +
      `<div class="sidebar-foot">` +
      `<button type="button" class="account-btn" id="user-chip" title="当前账号">` +
      `<span class="account-avatar" id="account-avatar">·</span>` +
      `<span class="account-meta"><span class="account-name" id="account-name">未登录</span>` +
      `<span class="account-role" id="account-role">—</span></span>` +
      `</button>` +
      `<button type="button" class="btn-icon" id="user-logout" title="退出登录" aria-label="退出登录">` +
      U.icon("logout") + `</button>` +
      `</div>`;
  }

  function renderTopbar() {
    const bar = document.getElementById("topbar");
    if (!bar) return;
    bar.innerHTML = [
      `<div class="topbar-left">`,
      `<button type="button" class="btn-icon" id="nav-open" aria-label="打开全部导航" aria-expanded="false">${U.icon("menu")}</button>`,
      `<nav class="crumb" id="crumb" aria-label="面包屑"></nav>`,
      `</div>`,
      `<div class="topbar-right">`,
      `<span class="proto-flag" id="provider-flag" title="当前生成方式">${U.icon("info")}<span>加载中…</span></span>`,
      `<a class="pill-action" href="/workbench" data-link>${U.icon("sparkles")}<span>AI 助手</span></a>`,
      `</div>`,
    ].join("");
  }

  /* ---- 数据来源提示条（可关闭，关闭状态记在 localStorage） ---- */
  function mountBanner() {
    let dismissed = false;
    try { dismissed = localStorage.getItem(BANNER_KEY) === "1"; } catch (err) { /* 忽略 */ }
    const bar = document.getElementById("source-banner");
    if (!bar) return;
    if (dismissed) { bar.hidden = true; return; }
    bar.hidden = false;
    bar.innerHTML =
      U.icon("info") +
      `<span class="source-banner-text"><strong>演示环境</strong>　当前页面部分内容使用示例数据；连接真实店铺或导入自己的文件后，可查看对应业务数据。</span>` +
      `<button type="button" class="source-banner-close" id="banner-close" aria-label="关闭提示">${U.icon("close")}</button>`;
    const close = bar.querySelector("#banner-close");
    if (close) {
      close.addEventListener("click", function () {
        bar.hidden = true;
        try { localStorage.setItem(BANNER_KEY, "1"); } catch (err) { /* 忽略 */ }
      });
    }
  }

  async function loadProvider() {
    const flag = document.getElementById("provider-flag");
    if (!flag) return;
    try {
      const health = await window.CPApi.get("/api/health");
      const p = health.provider || {};
      const worker = health.worker || {};
      let name;
      if (p.name === "rule") name = "规则引擎";
      else name = (p.name || "未知") + (p.model ? " · " + p.model : "");
      if (!p.available) name += "（不可用）";
      else if (!p.verified) name += "（未验证）";
      flag.classList.toggle("is-warn", !p.available || Boolean(p.fallback_reason));
      flag.classList.toggle("is-ok", Boolean(p.available) && p.verified);
      flag.innerHTML = `${U.icon("info")}<span>${U.esc(name)}</span>`;
      flag.title = p.detail || "";
      if (worker && worker.alive === false) {
        flag.classList.add("is-warn");
        flag.title = (p.detail || "") + " · 异步执行器不可用";
      }
    } catch (err) {
      flag.classList.remove("is-ok");
      flag.classList.add("is-warn");
      flag.innerHTML = `${U.icon("alert")}<span>服务状态未知</span>`;
    }
  }

  async function loadUser() {
    if (!window.CPAuth || !window.CPAuth.user) return;
    try {
      const me = await window.CPApi.get("/api/auth/me");
      const user = me.user || {};
      const nameNode = document.getElementById("account-name");
      const roleNode = document.getElementById("account-role");
      const avatar = document.getElementById("account-avatar");
      const display = user.display_name || user.username || "—";
      if (nameNode) nameNode.textContent = display;
      if (roleNode) roleNode.textContent = user.is_admin ? "管理员" : (user.is_guest ? "临时账号" : "成员");
      if (avatar) avatar.textContent = String(display).slice(0, 1).toUpperCase();
      const chip = document.getElementById("user-chip");
      if (chip) {
        chip.title = `${display} · 点击退出`;
        chip.setAttribute("aria-label", `账号 ${user.username}`);
      }
    } catch (err) { /* 会话失效由 401 处理器接管 */ }
  }

  function setCrumb(key, extra) {
    const crumb = document.getElementById("crumb");
    if (!crumb) return;
    const parts = [`<a href="/dashboard" data-link>工作空间</a>`];
    parts.push(`<span class="crumb-sep">/</span>`);
    parts.push(`<span class="crumb-current">${U.esc(extra || LABELS[key] || key)}</span>`);
    crumb.innerHTML = parts.join("");
  }

  function setActive(key) {
    document.querySelectorAll("[data-nav]").forEach(function (node) {
      const active = node.getAttribute("data-nav") === key;
      node.classList.toggle("is-active", active);
      if (active) node.setAttribute("aria-current", "page");
      else node.removeAttribute("aria-current");
    });
  }

  /* ---- 全量导航抽屉（窄屏用） ---- */
  let scrim = null;

  function renderDrawer() {
    const drawer = document.getElementById("nav-drawer");
    if (!drawer) return;
    const groups = C.NAV.map(function (g) {
      const links = g.items.map(function (item) {
        return (
          `<a class="nav-item" href="${item.path}" data-link data-nav="${item.key}" data-drawer-link>` +
          U.icon(item.icon) +
          `<span class="nav-item-label">${U.esc(item.label)}</span>` +
          (item.soon ? `<span class="nav-soon">开发中</span>` : "") +
          `</a>`
        );
      }).join("");
      return `<div class="sidebar-group"><div class="sidebar-group-title">${U.esc(g.group)}</div>${links}</div>`;
    }).join("");

    drawer.innerHTML =
      `<div class="drawer-head" style="align-items:center">` +
      `<a class="sidebar-brand" href="/dashboard" data-link>` +
      `<img src="/media/logo-mark.svg?v=2" alt="" width="26" height="26" />` +
      `<span class="sidebar-brand-text">${BRAND}</span></a>` +
      `<button type="button" class="btn-icon" id="nav-close" aria-label="关闭导航">${U.icon("close")}</button>` +
      `</div>` +
      `<div class="drawer-body" style="padding:var(--sp-3)">${groups}</div>`;
    drawer.hidden = true;
  }

  function openDrawer() {
    const drawer = document.getElementById("nav-drawer");
    if (!drawer) return;
    scrim = document.createElement("div");
    scrim.className = "drawer-scrim";
    scrim.addEventListener("click", closeDrawer);
    document.body.appendChild(scrim);
    drawer.hidden = false;
    document.getElementById("nav-open").setAttribute("aria-expanded", "true");
    const first = drawer.querySelector("a");
    if (first) first.focus();
    document.addEventListener("keydown", onKeydown);
  }

  function closeDrawer() {
    const drawer = document.getElementById("nav-drawer");
    if (!drawer) return;
    drawer.hidden = true;
    if (scrim) { scrim.remove(); scrim = null; }
    const opener = document.getElementById("nav-open");
    if (opener) opener.setAttribute("aria-expanded", "false");
    document.removeEventListener("keydown", onKeydown);
  }

  function onKeydown(event) {
    if (event.key === "Escape") closeDrawer();
  }

  function mount() {
    document.querySelector(".app").classList.toggle("is-collapsed", isCollapsed());
    renderSidebar();
    renderTopbar();
    renderDrawer();
    mountBanner();
    const opener = document.getElementById("nav-open");
    if (opener) opener.addEventListener("click", openDrawer);
    const closer = document.getElementById("nav-close");
    if (closer) closer.addEventListener("click", closeDrawer);
    const toggle = document.getElementById("sidebar-toggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        const next = !document.querySelector(".app").classList.contains("is-collapsed");
        setCollapsed(next);
        toggle.setAttribute("aria-expanded", next ? "false" : "true");
        toggle.setAttribute("aria-label", next ? "展开侧栏" : "收起侧栏");
      });
    }
    document.addEventListener("click", function (event) {
      if (event.target.closest("[data-drawer-link]")) closeDrawer();
    });
  }

  function setNavKey(key) {
    setActive(key);
    setCrumb(key);
  }

  window.CPShell = {
    mount, setNavKey, openDrawer, closeDrawer, loadProvider, loadUser, LABELS,
    setCollapsed, mountBanner,
  };
})();
