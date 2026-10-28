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

  /* ---------------- 技能库 ----------------
   * 已迁到 js/pages/skills.js：那一页要渲染参数表单与运行结果，
   * 和本文件里的静态列表不是一回事，混在一起会让两边都难改。 */


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

  window.CPPages = { agents, notFound, pageShell };
})();
