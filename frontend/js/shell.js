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
  const EXPAND_KEY = "cp.sidebar.expanded";
  const BANNER_KEY = "cp.banner.dismissed";

  /* 外壳 UI 状态：走 CPStore，折叠状态与 DOM 单向同步 */
  const UI = window.CPStore ? window.CPStore.create({ expanded: false, bannerDismissed: false }) : null;

  if (UI) {
    try {
      UI.setState({
        expanded: localStorage.getItem(EXPAND_KEY) === "1",
        bannerDismissed: localStorage.getItem(BANNER_KEY) === "1",
      });
    } catch (err) { /* 忽略 */ }

    UI.subscribe(
      function (s) { return s.expanded; },
      function (expanded) {
        try { localStorage.setItem(EXPAND_KEY, expanded ? "1" : "0"); } catch (err) { /* 忽略 */ }
        const app = document.querySelector(".app");
        if (app) app.classList.toggle("is-expanded", expanded);
      }
    );

    UI.subscribe(
      function (s) { return s.bannerDismissed; },
      function (dismissed) {
        try { localStorage.setItem(BANNER_KEY, dismissed ? "1" : "0"); } catch (err) { /* 忽略 */ }
        const bar = document.getElementById("source-banner");
        if (bar) bar.hidden = dismissed;
      }
    );
  }

  function isExpanded() {
    if (UI) return UI.getState().expanded;
    try { return localStorage.getItem(EXPAND_KEY) === "1"; } catch (err) { return false; }
  }

  function setExpanded(value) {
    if (UI) { UI.setState({ expanded: Boolean(value) }); return; }
    try { localStorage.setItem(EXPAND_KEY, value ? "1" : "0"); } catch (err) { /* 忽略 */ }
    const app = document.querySelector(".app");
    if (app) app.classList.toggle("is-expanded", value);
  }

  function renderSidebar() {
    const bar = document.getElementById("sidebar");
    if (!bar) return;
    const byKey = {};
    C.NAV.forEach(function (g) { g.items.forEach(function (i) { byKey[i.key] = i; }); });

    const groups = C.NAV.map(function (group) {
      const items = group.items.map(function (item) {
        const short = C.RAIL_LABEL[item.key] || item.label;
        return (
          `<a class="nav-item" href="${item.path}" data-link data-nav="${item.key}" ` +
          `title="${U.esc(item.label)}">` +
          U.icon(item.icon) +
          `<span class="nav-item-label">` +
          `<span class="nav-label-short">${U.esc(short)}</span>` +
          `<span class="nav-label-full">${U.esc(item.label)}</span>` +
          `</span>` +
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

    const expanded = isExpanded();
    bar.innerHTML =
      `<div class="sidebar-head">` +
      `<button type="button" class="sidebar-brand" id="sidebar-brand"` +
      ` aria-expanded="${expanded ? "true" : "false"}"` +
      ` aria-label="${expanded ? "收起导航" : "展开导航"}"` +
      ` title="${expanded ? "收起导航" : "展开导航"}">` +
      `<img src="/media/logo-mark.svg?v=2" alt="" width="36" height="36" />` +
      `<span class="sidebar-brand-text">${BRAND}</span></button>` +
      `</div>` +
      `<nav class="sidebar-nav" aria-label="主导航">${groups}</nav>` +
      `<div class="sidebar-foot">` +
      `<div class="account-wrap" id="account-wrap">` +
      `<button type="button" class="account-btn" id="user-chip" title="当前账号"` +
      ` aria-haspopup="menu" aria-expanded="false" aria-controls="account-menu">` +
      `<span class="account-avatar" id="account-avatar">·</span>` +
      `<span class="account-meta"><span class="account-name" id="account-name">未登录</span>` +
      `<span class="account-role" id="account-role">—</span></span>` +
      `</button>` +
      `<div class="account-menu" id="account-menu" role="menu" aria-label="账号" hidden>` +
      `<div class="account-menu-head">` +
      `<span class="account-menu-avatar" id="menu-avatar">·</span>` +
      `<span class="account-menu-id">` +
      `<span class="account-menu-name" id="menu-name">未登录</span>` +
      `<span class="account-menu-sub" id="menu-sub">—</span>` +
      `</span>` +
      `</div>` +
      `<div class="account-menu-card">` +
      `<div class="account-menu-card-row">` +
      `<span class="account-menu-card-label">智能助手</span>` +
      `<span class="account-menu-card-value" id="menu-model">检查中…</span>` +
      `</div>` +
      `<div class="account-menu-card-row">` +
      `<span class="account-menu-card-label">任务执行</span>` +
      `<span class="account-menu-card-value" id="menu-worker">检查中…</span>` +
      `</div>` +
      `</div>` +
      `<div class="account-menu-list">` +
      `<a class="account-menu-item" role="menuitem" href="/settings" data-link>` +
      U.icon("settings") + `<span>个人设置</span></a>` +
      `<a class="account-menu-item" role="menuitem" href="/stores" data-link>` +
      U.icon("stores") + `<span>店铺与渠道</span></a>` +
      `<a class="account-menu-item" role="menuitem" href="/data" data-link>` +
      U.icon("data") + `<span>数据资产</span></a>` +
      `</div>` +
      `<div class="account-menu-sep"></div>` +
      `<div class="account-menu-list">` +
      `<button type="button" class="account-menu-item" role="menuitem" id="user-logout">` +
      U.icon("logout") + `<span>退出登录</span></button>` +
      `</div>` +
      `</div>` +
      `</div>` +
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

  /* ---- 数据来源提示条（可关闭，关闭状态记在 store） ---- */
  function mountBanner() {
    const bar = document.getElementById("source-banner");
    if (!bar) return;
    if (isDismissed()) { bar.hidden = true; return; }
    bar.hidden = false;
    bar.innerHTML =
      U.icon("info") +
      `<span class="source-banner-text"><strong>示例数据</strong>　当前显示的商品、报告与任务里有示例内容，用来让你走通完整流程。导入你自己的文件或添加店铺后，这里就会换成你的数据。</span>` +
      `<button type="button" class="source-banner-close" id="banner-close" aria-label="关闭提示">${U.icon("close")}</button>`;
    const close = bar.querySelector("#banner-close");
    if (close) {
      close.addEventListener("click", function () {
        bar.hidden = true;
        if (UI) UI.setState({ bannerDismissed: true });
        else { try { localStorage.setItem(BANNER_KEY, "1"); } catch (err) { /* 忽略 */ } }
      });
    }
  }

  function isDismissed() {
    if (UI) return UI.getState().bannerDismissed;
    try { return localStorage.getItem(BANNER_KEY) === "1"; } catch (err) { return false; }
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
        flag.title = ((p.detail || "") + " · 任务执行服务暂时不可用").trim();
      }

      const menuModel = document.getElementById("menu-model");
      const menuWorker = document.getElementById("menu-worker");
      if (menuModel) menuModel.textContent = p.available ? name : "未配置";
      if (menuWorker) {
        menuWorker.textContent = worker && worker.alive === false ? "暂不可用" : "正常";
      }
    } catch (err) {
      flag.classList.remove("is-ok");
      flag.classList.add("is-warn");
      flag.innerHTML = `${U.icon("alert")}<span>服务状态未知</span>`;
      const menuModel = document.getElementById("menu-model");
      const menuWorker = document.getElementById("menu-worker");
      if (menuModel) menuModel.textContent = "未知";
      if (menuWorker) menuWorker.textContent = "未知";
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
      const role = user.is_admin ? "管理员" : (user.is_guest ? "临时账号" : "成员");
      const initial = String(display).slice(0, 1).toUpperCase();
      if (nameNode) nameNode.textContent = display;
      if (roleNode) roleNode.textContent = role;
      if (avatar) avatar.textContent = initial;

      const menuName = document.getElementById("menu-name");
      const menuSub = document.getElementById("menu-sub");
      const menuAvatar = document.getElementById("menu-avatar");
      if (menuName) menuName.textContent = display;
      if (menuSub) menuSub.textContent = `${role} · ${user.username || "—"}`;
      if (menuAvatar) menuAvatar.textContent = initial;

      const chip = document.getElementById("user-chip");
      if (chip) {
        chip.title = "账号";
        chip.setAttribute("aria-label", `账号 ${user.username}，打开账号菜单`);
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

  /* ---- 账号菜单：悬停展开，点击切换，Esc / 点击外部收起 ---- */
  let menuTimer = null;

  function openMenu() {
    const chip = document.getElementById("user-chip");
    const menu = document.getElementById("account-menu");
    if (!chip || !menu || !menu.hidden) return;
    menu.hidden = false;
    chip.setAttribute("aria-expanded", "true");
    if (window.CPMotion) window.CPMotion.fadeIn(menu, { y: 4, duration: 140 });
  }

  function closeMenu(restoreFocus) {
    const chip = document.getElementById("user-chip");
    const menu = document.getElementById("account-menu");
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    if (chip) chip.setAttribute("aria-expanded", "false");
    if (restoreFocus && chip) chip.focus();
  }

  function scheduleClose() {
    if (menuTimer) clearTimeout(menuTimer);
    menuTimer = setTimeout(function () { menuTimer = null; closeMenu(false); }, 160);
  }

  function mountAccountMenu() {
    const wrap = document.getElementById("account-wrap");
    if (!wrap) return;

    wrap.addEventListener("mouseenter", function () {
      if (menuTimer) { clearTimeout(menuTimer); menuTimer = null; }
      openMenu();
    });
    wrap.addEventListener("mouseleave", scheduleClose);
    wrap.addEventListener("focusin", openMenu);

    const chip = document.getElementById("user-chip");
    if (chip) {
      chip.addEventListener("click", function (event) {
        event.preventDefault();
        const menu = document.getElementById("account-menu");
        if (menu && menu.hidden) openMenu();
        else closeMenu(false);
      });
    }

    document.addEventListener("click", function (event) {
      const box = document.getElementById("account-wrap");
      if (!box) return;
      if (event.target.closest("#account-menu a, #account-menu #user-logout") || !box.contains(event.target)) {
        closeMenu(false);
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeMenu(true);
    });
  }

  function mount() {
    document.querySelector(".app").classList.toggle("is-expanded", isExpanded());
    renderSidebar();
    renderTopbar();
    renderDrawer();
    mountBanner();
    mountAccountMenu();
    const opener = document.getElementById("nav-open");
    if (opener) opener.addEventListener("click", openDrawer);
    const closer = document.getElementById("nav-close");
    if (closer) closer.addEventListener("click", closeDrawer);
    const brand = document.getElementById("sidebar-brand");
    if (brand) {
      brand.addEventListener("click", function () {
        const next = !document.querySelector(".app").classList.contains("is-expanded");
        setExpanded(next);
        const label = next ? "收起导航" : "展开导航";
        brand.setAttribute("aria-expanded", next ? "true" : "false");
        brand.setAttribute("aria-label", label);
        brand.title = label;
        if (window.CPMotion) window.CPMotion.tap(brand);
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
    setExpanded, mountBanner,
  };
})();
