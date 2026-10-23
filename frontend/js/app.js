/* 激浪 · 应用入口：鉴权 → 路由 → 页面挂载 */
(function () {
  "use strict";
  const R = window.CPRouter;
  const S = window.CPShell;
  const P = window.CPPages;
  const W = window.CPPageWorkbench;
  const root = document.getElementById("view-root");

  let started = false;

  function mountPage(key, handler) {
    return function (params, query) {
      S.setNavKey(key);
      root.onclick = null;
      root.onsubmit = null;
      /* 每次挂载给一个独立容器。
         页面渲染是异步的（要等接口），用户在等待期间切走时，上一页的
         innerHTML 会在新页面挂载之后才写回来，把整页覆盖掉——网络越慢越明显。
         换成一个新容器后，旧回调只能写进已经脱离文档的节点，不影响当前页面。 */
      const slot = document.createElement("div");
      slot.className = "mount-slot";
      root.textContent = "";
      root.appendChild(slot);

      const result = handler(slot, params, query);
      if (result && typeof result.catch === "function") {
        result.catch(function (err) {
          if (!slot.isConnected) return; // 已经切走了，别把旧错误糊到新页面上
          slot.innerHTML = `<div class="view"><div class="page"><div class="page-inner">` +
            `<div class="callout callout-danger">${window.CPUi.icon("alert")}` +
            `<div><strong>页面加载失败</strong><br>${window.CPUi.esc(err.message || String(err))}` +
            `<div class="mt-2"><button type="button" class="btn btn-sm" onclick="location.reload()">刷新</button></div>` +
            `</div></div></div></div></div>`;
          window.CPIcon.hydrate(slot);
        });
      }
      window.CPIcon.hydrate(document);
      /* 页面进场：主区块按序淡入（Motion），reduced-motion 下直接落位 */
      if (window.CPMotion) {
        const stage = slot.querySelector(".page-inner") || slot.querySelector(".view");
        if (stage) window.CPMotion.stagger(stage, { selector: ":scope > *", step: 22, y: 5 });
      }
      root.focus({ preventScroll: true });
      // 登录态变化时刷新顶栏的生成方式标识
      if (S.loadProvider) S.loadProvider();
    };
  }

  R.define("/dashboard", mountPage("dashboard", window.CPPageDashboard.render));
  R.define("/workbench", mountPage("workbench", W.entry));
  R.define("/tasks", mountPage("tasks", window.CPPageTasks.render));
  R.define("/tasks/:id", mountPage("tasks", window.CPPageTasks.detail));
  R.define("/competitors", mountPage("competitors", window.CPPageCompetitors.render));
  R.define("/profit", mountPage("profit", window.CPPageProfit.render));
  R.define("/listings", mountPage("listings", window.CPPageListings.render));
  R.define("/data", mountPage("data", window.CPPageData.render));
  R.define("/agents", mountPage("agents", P.agents));
  R.define("/skills", mountPage("skills", P.skills));
  /* 店铺与渠道：四个子页共用一个页面模块，子导航在页面顶部。
     注意 mountPage 的回调签名是 (root, params, query) 三个参数——
     写成 (params, query) 会把路由 params 当成 query，URL 上的筛选条件就全丢了。 */
  const ST = window.CPPageStores;
  R.define("/stores", mountPage("stores", function (root, params, query) {
    return ST.render(root, "dashboard", query);
  }));
  R.define("/stores/authorize", mountPage("stores", function (root, params, query) {
    return ST.render(root, "authorize", query);
  }));
  R.define("/stores/product", mountPage("stores", function (root, params, query) {
    return ST.render(root, "product", query);
  }));
  R.define("/stores/ledger", mountPage("stores", function (root, params, query) {
    return ST.render(root, "ledger", query);
  }));
  R.define("/settings", mountPage("settings", window.CPPageSettings.render));

  /* 未开放的能力不进路由也不进导航：直接落到 404，
     界面上不解释「为什么还没做」，只给出现在能去哪。 */

  function fallback(path) {
    if (path === "/" || path === "" || path === "/index.html") {
      R.go("/dashboard", { replace: true });
      return;
    }
    S.setNavKey("dashboard");
    root.innerHTML = "";
    P.notFound(root, path);
    window.CPIcon.hydrate(document);
  }

  function startApp() {
    if (started) return;
    started = true;
    R.start(fallback);
  }

  async function boot() {
    // 规范入口：根路径统一落到工作台，登录前后 URL 一致
    if (location.pathname === "/" || location.pathname === "/index.html") {
      history.replaceState({}, "", "/dashboard");
    }

    S.mount();
    window.CPIcon.hydrate(document);
    if (S.loadProvider) S.loadProvider();

    // 401 时：已登录过才提示"会话过期"，否则静默交给登录门
    window.CPApi.onUnauthorized(function () {
      const wasSignedIn = Boolean(window.CPAuth.user);
      // 不要复位 started：路由事件已经绑过了，复位会导致下次登录重复绑一遍
      // （popstate / 站内链接会触发多次渲染）。会话失效时把旧页面清掉即可。
      root.textContent = "";
      if (wasSignedIn) window.CPAuth.show("登录已过期，请重新登录");
    });

    window.CPAuth.load().then(function (user) {
      if (user) {
        if (S.loadUser) S.loadUser();
        startApp();
      }
    });

    /* 登录 / 换账号：这个监听必须常驻。
       之前写成 { once: true } 只挂在"未登录"分支里，第一次登录后就消耗掉了，
       于是退出再点「一键体验」时，新账号已经建好、Cookie 也换了，
       却没人刷新顶栏和页面——界面上仍然是上一个账号的数据。 */
    window.addEventListener("cp:authenticated", function () {
      if (S.loadUser) S.loadUser();
      if (S.loadProvider) S.loadProvider();
      // 已经启动过路由（换账号再登）：直接按当前地址重绘，让页面用新账号重新取数。
      // 没启动过（首次登录）：走正常的启动流程，只绑一次事件。
      if (started) R.render(location.pathname + location.search);
      else startApp();
    });

    window.addEventListener("cp:logout", function () {
      // 退出只是亮出登录门，画面还在门后面。不清空的话，
      // 下次登录成功后会看到上一个账号的页面和数字。
      history.replaceState({}, "", "/dashboard");
      root.textContent = "";
    });

    // 侧栏的退出入口
    document.addEventListener("click", function (event) {
      if (event.target.closest("#user-logout")) {
        window.CPAuth.logout();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
