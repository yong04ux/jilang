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
      root.innerHTML = "";
      const result = handler(root, params, query);
      if (result && typeof result.catch === "function") {
        result.catch(function (err) {
          root.innerHTML = `<div class="view"><div class="page"><div class="page-inner">` +
            `<div class="callout callout-danger">${window.CPUi.icon("alert")}` +
            `<div><strong>页面加载失败</strong><br>${window.CPUi.esc(err.message || String(err))}` +
            `<div class="mt-2"><button type="button" class="btn btn-sm" onclick="location.reload()">刷新</button></div>` +
            `</div></div></div></div></div>`;
          window.CPIcon.hydrate(root);
        });
      }
      window.CPIcon.hydrate(document);
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
  R.define("/listings", mountPage("listings", window.CPPageListings.render));
  R.define("/data", mountPage("data", window.CPPageData.render));
  R.define("/agents", mountPage("agents", P.agents));
  R.define("/skills", mountPage("skills", P.skills));
  R.define("/stores", mountPage("stores", P.stores));
  R.define("/settings", mountPage("settings", window.CPPageSettings.render));

  R.define("/research", mountPage("research", function (r) {
    r.innerHTML = `<div class="view">${P.soonPage("选品与市场研究",
      "把选品判断、市场规模与竞争格局整理成可复核的结论。",
      "阶段 E（数据源与导入服务整合之后）",
      [{ label: "先用竞品分析", path: "/competitors" }, { label: "问 AI", path: "/workbench" }])}</div>`;
  }));
  R.define("/assets", mountPage("assets", function (r) {
    r.innerHTML = `<div class="view">${P.soonPage("商品素材工作室",
      "生成与管理商品图片、A+ 素材与视频脚本。",
      "未排期（需先完成对象存储与多模态能力）",
      [{ label: "查看 Listing 草稿", path: "/listings" }])}</div>`;
  }));
  R.define("/operations", mountPage("operations", function (r) {
    r.innerHTML = `<div class="view">${P.soonPage("运营分析",
      "广告、流量与转化的运营复盘。",
      "未排期（依赖真实店铺数据接入；当前只有 Mock 数据源）",
      [{ label: "查看店铺连接", path: "/stores" }])}</div>`;
  }));
  R.define("/workflows", mountPage("workflows", function (r) {
    r.innerHTML = `<div class="view">${P.soonPage("工作流",
      "可视化编排 Agent 与 Skills。",
      "未排期（第一阶段只做固定流水线，不做 DAG 编辑器）",
      [{ label: "查看 Agent", path: "/agents" }, { label: "查看技能库", path: "/skills" }])}</div>`;
  }));
  R.define("/knowledge", mountPage("knowledge", function (r) {
    r.innerHTML = `<div class="view">${P.soonPage("知识库",
      "沉淀品牌规范、类目规则与历史结论。",
      "未排期（需要向量检索与文档解析）",
      [{ label: "查看数据资产", path: "/data" }])}</div>`;
  }));

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
      started = false;
      if (wasSignedIn) window.CPAuth.show("登录已过期，请重新登录");
    });

    window.CPAuth.load().then(function (user) {
      if (user) {
        if (S.loadUser) S.loadUser();
        startApp();
      } else {
        window.addEventListener("cp:authenticated", function () {
          started = false;
          if (S.loadUser) S.loadUser();
          startApp();
        }, { once: true });
      }
    });

    window.addEventListener("cp:logout", function () {
      started = false;
      history.replaceState({}, "", "/dashboard");
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
