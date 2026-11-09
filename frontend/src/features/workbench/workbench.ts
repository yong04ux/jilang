/* 激浪 · AI 助手（真实会话 + Agent Runtime + 异步执行）
 *
 * 版式：对话即执行台。澄清卡、执行卡、中断卡、结果卡都长在对话流里；
 * 完整的步骤、证据、日志收进可开合的「过程与产物」抽屉。
 * - 自然语言目标先经 `/api/agent/resolve` 解析；
 * - 执行走 `/api/agent/runs` 的异步模式，轮询真实 task_steps，可停止；
 * - 状态只有一个真源：等待补充/等待确认绝不再显示「已完成」。
 *
 * 内部用 HTML 字符串渲染，因此本文件带 @ts-nocheck；页面由 routes.tsx 经 LegacyPage 挂载。
 * 全局 `U / A / C / R / AR` 由 `ensureDeps()` 懒取：模块在 bundle 初始化时就被 import，
 * 那时门面还没安装。
 */
// @ts-nocheck
/* eslint-disable */

let U
let A
let C
let R
let AR

/** 工作台表单能完整表达的技能；其余技能需要专属参数，选中后去技能详情页。
    已经用到的执行路径：competitor = 只做竞品分析，listing = 只生成文案。 */
const WORKBENCH_SKILLS: Record<string, "competitor" | "listing"> = {
  competitor_analysis: "competitor",
  listing_generation: "listing",
}

function ensureDeps() {
  if (U) return
  U = window.CPUi
  A = window.CPApi
  C = window.CPCatalog
  R = window.CPRender
  AR = window.CPAsyncRun
}

/* 对话页与空态都用实测可用高度：顶栏上方的示例横幅在窄屏会换行，
   写死 calc(100vh - 顶栏) 会把输入框挤出视口。 */
let viewDockResize = null
function dockView(root, selector) {
  const apply = function () {
    const el = root.querySelector(selector)
    if (!el) return
    const top = el.getBoundingClientRect().top
    el.style.height = Math.max(320, window.innerHeight - top) + "px"
  }
  apply()
  window.requestAnimationFrame(function () { window.requestAnimationFrame(apply) })
  if (!viewDockResize) {
    viewDockResize = function () {
      const el = document.querySelector(".wb-shell")
      if (!el) return
      const top = el.getBoundingClientRect().top
      el.style.height = Math.max(320, window.innerHeight - top) + "px"
    }
    window.addEventListener("resize", viewDockResize)
  }
}

  const state = {
    mode: "empty",            // empty | params | run
    composerDraft: "",        // 首页重绘时把输入到一半的话留住
    goal: "",
    productName: "",
    competitorsText: "",
    withListing: true,
    marketplace: "US",
    listingLanguage: "en-US",
    resolveInfo: null,
    busy: false,
    taskStatus: "",
    error: "",
    report: null,
    listing: null,
    summary: null,
    checks: null,
    quality: null,
    plan: [],
    steps: [],
    degraded: false,
    degradedReason: "",
    agentKey: "main",
    picked: null,             // 当前带进输入框的技能（从执行方式菜单选中，不跳页）
    selectedSkills: [],       // 本次执行实际选中的技能（显式选择或 Agent 自动路由）
    routing: null,            // 后端返回的路由说明（模式 / 降级原因 / 未执行说明）
    assistantOpen: false,     // 输入框右下角的执行方式选择器
    skillsOpen: false,        // 输入框左下角的技能选择器（与专家菜单分开）
    conversationId: null,
    conversationTitle: "",
    conversations: [],
    renamingId: null,         // 正在行内重命名的会话
    messages: [],
    taskId: null,
    taskRaw: null,
    poller: null,
    drawerOpen: false,       // 过程与产物抽屉
    continuing: false,        // 本次目标是在当前会话里继续，而不是新建
    missingFocus: false,      // 从「缺资料」进入澄清卡时自动展开缺失项
    needKey: false,           // 上一步因为没配 Key 被 428 拦下 → 给一个可点的入口
    // ---- Listing 生成（对话内配置卡）----
    products: [],             // 店铺商品，供商品选择器用
    productsLoaded: false,
    productsError: "",
    listingProduct: null,
    listingName: "",
    listingPrice: null,
    listingPlatform: "amazon",
    listingMarketplace: "US",
    listingSpecsText: "",
    listingFeaturesText: "",
    listingOnly: false,       // 这次任务只生成 Listing，不需要竞品数据
    listingDetailing: false,  // 「补充商品资料」是否展开
    moreParamsOpen: false,    // 竞品分析的「更多参数」是否展开
    productCategory: "",      // 商品类目（随请求发给后端）
    ownSpecs: { size: "", material: "", capacity: "", color: "", weight: "", quantity: "" }, // 商品事实，进 own_specs
    logCache: null,           // 抽屉里的调用明细
    pending: null,            // 服务端返回的待确认信息
    engine: null,             // 本次执行用的是规则引擎还是大模型
  };

  /* 竞品录入：一行一个，字段之间用「|」隔开
     名称 | 价格 | 评分 | 评论数 | 一条评论
     解析实现放在 js/schema-form.js——技能页也用同一套，避免出现第三份解析 */
  function parseCompetitors(text) {
    return window.CPSchemaForm.parseCompetitors(text);
  }

  function competitorsToText(list) {
    return window.CPSchemaForm.competitorsToText(list);
  }

  /* ================= 空态：一句话开始 =================
   * 「自动 / 专家 / 技能」不再是首屏三段入口，而是输入框里的执行方式选择器。
   * 首屏只留标题、提示语、最近会话和输入框，减少「先选类型」这一步。
   */

  /* 「试试这样说」用既有技能提示语，不另写一套文案 */
  const QUICK_GOALS = ["competitor_analysis", "market_summary", "listing_generation"];

  function promptPanel() {
    const goals = QUICK_GOALS.map(function (key) {
      const skill = C.skillByKey(key);
      return skill
        ? `<button type="button" class="wb-prompt" data-skill="${U.esc(key)}">` +
          `${U.icon("sparkles")}<span>${U.esc(skill.prompt)}</span></button>`
        : "";
    }).join("");
    return (
      `<div class="wb-start">` +
      `<div class="wb-start-label">试试这样说</div>` +
      `<div class="wb-prompts">${goals}</div>` +
      `</div>`
    );
  }

  /* ================= 左侧会话栏 =================
   * 新会话、历史会话都收在左栏；当前会话高亮，标题可行内重命名。
   */

  function conversationRailItem(c) {
    const id = c.conversation_id;
    const active = id === state.conversationId;
    if (state.renamingId === id) {
      return (
        `<div class="wb-conv-row is-editing">` +
        `<input class="wb-conv-input" data-rename-input="${U.esc(id)}" value="${U.esc(c.title)}" ` +
        `maxlength="60" aria-label="会话名称" />` +
        `</div>`
      );
    }
    return (
      `<div class="wb-conv-row${active ? " is-active" : ""}">` +
      `<button type="button" class="wb-conv-open" data-conversation="${U.esc(id)}" title="${U.esc(c.title)}">` +
      `<span class="wb-conv-title">${U.esc(c.title)}</span>` +
      `<span class="wb-conv-meta">${c.message_count || 0} 条 · ${U.esc(U.fmtTime(c.updated_at))}</span>` +
      `</button>` +
      `<button type="button" class="wb-conv-rename" data-rename="${U.esc(id)}" ` +
      `aria-label="重命名会话" title="重命名">${U.icon("pencil")}</button>` +
      `</div>`
    );
  }

  function conversationRail() {
    const list = (state.conversations || []).slice();
    if (state.conversationId && !list.some(function (c) {
      return c.conversation_id === state.conversationId;
    })) {
      /* 会话刚创建、列表还没刷新时，先把当前会话占一个位置 */
      list.unshift({
        conversation_id: state.conversationId,
        title: state.conversationTitle || state.productName || state.goal || "当前会话",
        message_count: (state.messages || []).length,
        updated_at: new Date().toISOString(),
      });
    }
    return (
      `<aside class="wb-conv-rail" aria-label="历史会话">` +
      `<div class="wb-rail-head">` +
      `<button type="button" class="wb-new-conv" data-act="new">${U.icon("plus")}<span>新会话</span></button>` +
      `<div class="wb-rail-label">历史会话<span>${list.length}</span></div>` +
      `</div>` +
      `<div class="wb-rail-list">` +
      (list.length
        ? list.map(conversationRailItem).join("")
        : `<p class="wb-rail-empty">还没有会话。说一句话就开始。</p>`) +
      `</div>` +
      `</aside>`
    );
  }

  function wbShell(main) {
    return `<div class="wb-shell">${conversationRail()}<div class="wb-main">${main}</div></div>`;
  }

  function refreshRail(root) {
    const rail = root.querySelector(".wb-conv-rail");
    if (!rail) return;
    const list = rail.querySelector(".wb-rail-list");
    const top = list ? list.scrollTop : 0;
    rail.outerHTML = conversationRail();
    const next = root.querySelector(".wb-rail-list");
    if (next) next.scrollTop = top;
    window.CPIcon.hydrate(root);
    if (state.renamingId) {
      const input = root.querySelector("[data-rename-input]");
      if (input) {
        input.focus();
        input.select();
      }
    }
  }

  async function saveRename(root, conversationId, raw) {
    const title = String(raw || "").trim();
    if (!title) {
      U.toast("会话名称不能为空", "danger");
      refreshRail(root);
      return;
    }
    state.renamingId = null;
    try {
      const data = await A.put(`/api/conversations/${encodeURIComponent(conversationId)}`, { title });
      const next = (data && data.conversation) || {};
      state.conversations = state.conversations.map(function (item) {
        return item.conversation_id === conversationId
          ? { ...item, title: next.title || title }
          : item;
      });
      if (state.conversationId === conversationId) {
        state.conversationTitle = next.title || title;
        const titleEl = root.querySelector(".wb-chat-title .t-section");
        if (titleEl) titleEl.textContent = state.conversationTitle;
      }
      U.toast("会话已重命名", "ok");
    } catch (err) {
      U.toast(err.message || "重命名失败，请重试", "danger");
    }
    refreshRail(root);
  }

  function assistantLabel() {
    if (state.picked) return state.picked.name;
    if (state.agentKey !== "main") {
      const agent = C.AGENTS.filter(function (a) { return a.key === state.agentKey; })[0];
      if (agent) return agent.name;
    }
    return "自动执行";
  }

  function assistantMenu() {
    if (!state.assistantOpen) return "";
    const autoOn = !state.picked && state.agentKey === "main";
    const agents = C.AGENTS.filter(function (a) { return a.key !== "main"; }).map(function (agent) {
      const on = !state.picked && state.agentKey === agent.key;
      return `<button type="button" class="wb-menu-item${on ? " is-active" : ""}" ` +
        `data-agent="${U.esc(agent.key)}" role="menuitem">` +
        `<span class="wb-menu-name">${U.esc(agent.name)}</span>` +
        `<span class="wb-menu-desc">${U.esc(agent.summary)}</span></button>`;
    }).join("");
    return (
      `<div class="wb-menu" role="menu" aria-label="选择执行方式">` +
      `<div class="wb-menu-sec">自动</div>` +
      `<button type="button" class="wb-menu-item${autoOn ? " is-active" : ""}" ` +
      `data-agent="main" role="menuitem">` +
      `<span class="wb-menu-name">自动执行（推荐）</span>` +
      `<span class="wb-menu-desc">按目标自动选择专家与技能</span></button>` +
      (agents ? `<div class="wb-menu-sec">指定专家</div>` + agents : "") +
      `<div class="wb-menu-note">要指定具体技能，用输入框左下角的「技能」。</div>` +
      `</div>`
    );
  }

  /* 技能列表单独一栏：和专家菜单分开，避免一个下拉越滚越长 */
  function skillsMenu() {
    if (!state.skillsOpen) return "";
    const skills = C.skills
      .filter(function (s) { return s.status === "available"; })
      .map(function (skill) {
        const on = state.picked && state.picked.key === skill.key;
        return `<button type="button" class="wb-menu-item${on ? " is-active" : ""}" ` +
          `data-pick-skill="${U.esc(skill.key)}" role="menuitem">` +
          `<span class="wb-menu-name">${U.esc(skill.name)}</span>` +
          `<span class="wb-menu-desc">${U.esc(skill.desc)}</span></button>`;
      }).join("");
    return (
      `<div class="wb-menu wb-skill-menu" role="menu" aria-label="选择技能">` +
      `<div class="wb-menu-sec">指定技能</div>` +
      (skills
        ? `<div class="wb-skill-grid">${skills}</div>`
        : `<div class="wb-menu-note">还没有能用的技能。</div>`) +
      `<a class="wb-menu-more" href="/skills" data-link>查看全部技能 ${U.icon("arrowRight")}</a>` +
      `</div>`
    );
  }

  function skillsButton() {
    return (
      `<button type="button" class="composer-tool${state.picked ? " is-active" : ""}" id="wb-skills-toggle" ` +
      `aria-expanded="${state.skillsOpen}" aria-haspopup="menu">` +
      `${U.icon("skills")}<span>技能</span></button>` +
      skillsMenu()
    );
  }

  function refreshSkills(root) {
    const wrap = root.querySelector(".wb-skills-wrap");
    if (!wrap) return;
    wrap.innerHTML = skillsButton();
    window.CPIcon.hydrate(wrap);
  }

  /* 输入框右下角的助手选择器。开关只重绘这一小块，避免整页重建时把输入框草稿冲掉 */
  function assistantButton() {
    return (
      `<button type="button" class="wb-assistant" id="wb-assistant" ` +
      `aria-expanded="${state.assistantOpen}" aria-haspopup="menu">` +
      `${U.icon("agents")}<span>${U.esc(assistantLabel())}</span>${U.icon("chevronDown")}</button>` +
      assistantMenu()
    );
  }

  function refreshAssistant(root) {
    const wrap = root.querySelector(".wb-assistant-wrap");
    if (!wrap) return;
    wrap.innerHTML = assistantButton();
    window.CPIcon.hydrate(wrap);
  }

  /* 选中技能后，输入框上方先出一句话说明——用户不用先跳到一个陌生表单。
     技能是干什么的卡片上已经写了，这里只说「接下来该做什么」。 */
  function skillEcho() {
    const s = state.picked;
    if (!s) return "";
    return (
      `<div class="wb-echo" id="wb-skill-echo">` +
      `<span class="wb-echo-icon">${U.esc(s.icon)}</span>` +
      `<span class="wb-echo-body">` +
      `<span class="wb-echo-title">已带入「${U.esc(s.name)}」</span>` +
      `<span class="wb-echo-text">把商品和站点补在这句话里，发送后我再核对参数。</span>` +
      `</span>` +
      `<button type="button" class="wb-echo-x" data-act="drop-skill" aria-label="取消这个技能">` +
      `${U.icon("x")}</button>` +
      `</div>`
    );
  }

  function paintEcho(root) {
    const host = root.querySelector("#wb-echo-host");
    if (!host) return;
    host.innerHTML = skillEcho();
    window.CPIcon.hydrate(host);
  }

  /** 选技能（菜单或提示语）：只把目标放进输入框并把焦点交过去，不直接执行 */
  function pickSkill(root, skill) {
    state.picked = skill;
    state.agentKey = "main";

    const input = root.querySelector("#composer-input");
    if (input) {
      input.value = skill.prompt || "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }

    paintEcho(root);
    refreshAssistant(root);
    refreshSkills(root);
    if (input) {
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }
  }

  function composer() {
    return (
      `<div class="composer">` +
      `<div id="wb-echo-host">${skillEcho()}</div>` +
      `<form class="composer-box" id="composer-form">` +
      `<textarea class="composer-input" id="composer-input" rows="1" ` +
      `placeholder="说说你想做什么，或选择上面的场景开始" aria-label="业务目标"></textarea>` +
      `<div class="composer-bar">` +
      `<div class="composer-tools">` +
      `<button type="button" class="composer-tool" data-act="data" title="数据资产">${U.icon("plus")}</button>` +
      `<div class="wb-skills-wrap">` + skillsButton() + `</div>` +
      `<button type="button" class="composer-tool" data-act="demo">${U.icon("sparkles")}<span>示例数据</span></button>` +
      `</div>` +
      `<div class="composer-right">` +
      `<div class="wb-assistant-wrap">` + assistantButton() + `</div>` +
      `<button type="submit" class="composer-send" id="composer-send" aria-label="开始执行" disabled>` +
      `${U.icon("arrowUp")}</button>` +
      `</div></div></form>` +
      `<div class="composer-foot">` +
      `<span>内容由业务代码与大模型共同生成，发布前需人工复核</span>` +
      `</div></div>`
    );
  }

  function renderEmpty() {
    return wbShell(
      `<div class="wb-empty"><div class="wb-scroll">` +
      `<div class="narrow-note">当前界面为桌面优先设计，建议在 1024px 以上宽度使用。</div>` +
      `<div class="wb-home">` +
      `<h1 class="wb-hero-title">跨境电商 AI 运营助手</h1>` +
      promptPanel() +
      `</div>` +
      `</div>` +
      composer() +
      `</div>`,
    );
  }

  /* ================= 参数确认 ================= */
  function specRow() {
    const info = state.resolveInfo;
    if (!info) return "";
    const spec = info.spec || {};
    const tone = info.degraded ? "callout-warn" : "callout-info";
    return (
      `<div class="callout ${tone}" style="margin-top:var(--sp-3)">${U.icon(info.degraded ? "alert" : "info")}` +
      `<div><strong>${info.degraded ? "执行参数是按文本推断的" : "已确认执行参数"}</strong>` +
      (info.degraded && info.reason ? `<br>${U.esc(info.reason)}` : "") +
      `<div class="row gap-2 wrap mt-2">` +
      `<span class="tag">站点 ${U.esc(spec.marketplace || state.marketplace)}</span>` +
      `<span class="tag">语言 ${U.esc(spec.listing_language || state.listingLanguage)}</span>` +
      `<span class="tag">${spec.with_listing === false ? "不生成 Listing" : "生成 Listing"}</span>` +
      (spec.category ? `<span class="tag">品类 ${U.esc(spec.category)}</span>` : "") +
      `</div></div></div>`
    );
  }

  /* 参数确认卡：**不占满整页**。它就长在首页内容的下方、输入框的上方，
     像助手顺着对话把「接下来要跑什么」摊开给你看，页面本身不换。 */
  /* 工作流顺序是确定性的，这里只列阶段，不冒充执行记录 */
  function plannedStages() {
    if (isListingMode()) {
      return ["校验输入", "分派工作流", "装载站点规则", "生成 Listing 草稿", "质检草稿", "保存草稿"];
    }
    if (!state.picked) {
      // 没指定技能时由 Agent 按目标选能力，事先不编造具体步骤
      return ["校验输入", "分派工作流", "Agent 按目标选择能力", "保存结果"];
    }
    const stages = ["校验输入", "分派工作流", "竞品分析"];
    if (state.withListing && !isCompetitorOnly()) {
      stages.push("检查 Listing 必需事实", "生成 Listing 草稿", "质检草稿");
    } else {
      stages.push("市场机会总结");
    }
    stages.push("保存结果");
    return stages;
  }

  /* ================= 参数澄清：对话内的一张卡 =================
   * 目标解析完就在对话里把「我理解成什么 + 还差什么」摊开，
   * 不再把用户甩到另一张四段式表单页。控件 id 与旧表单一致，执行逻辑不用重写。
   */

  function resolveSummary() {
    const info = state.resolveInfo;
    if (!info) {
      return `<div class="wb-clarify-hint">${U.icon("clock")}正在读取你的目标…</div>`;
    }
    const spec = info.spec || {};
    const tags = [];
    if (state.productName) tags.push(`商品 ${state.productName}`);
    tags.push(`站点 ${window.CPLabel.site(spec.marketplace || state.marketplace)}`);
    tags.push(`语言 ${window.CPLabel.language(spec.listing_language || state.listingLanguage)}`);
    tags.push(spec.with_listing === false ? "不生成 Listing" : "生成 Listing");
    if (spec.category) tags.push(`品类 ${spec.category}`);
    return (
      `<div class="wb-clarify-summary">` +
      `<span class="wb-clarify-sum-label">我理解成</span>` +
      `<div class="row gap-2 wrap">` +
      tags.map(function (t) { return `<span class="tag">${U.esc(t)}</span>`; }).join("") +
      `</div>` +
      (info.degraded
        ? `<div class="wb-clarify-note">${U.icon("alert")}参数来自文本识别，请核对下面的必填项。</div>`
        : "") +
      `</div>`
    );
  }

  function missingCallout() {
    if (!state.missingFocus) return "";
    const missing = waitingMissing();
    if (!missing.length) return "";
    return (
      `<div class="callout callout-warn">${U.icon("alert")}` +
      `<div><strong>补上这几项后重试</strong><br>` +
      `${missing.map(function (f) { return `<span class="tag tag-warn">${U.esc(readableText(f))}</span>`; }).join(" ")}` +
      `<div class="t-xs t-muted mt-2">这些是生成 Listing 需要的事实；补全后重新执行，已选商品和竞品会保留。</div>` +
      `</div></div>`
    );
  }

  function goalEditor() {
    return (
      `<details class="wb-more"${state.goal ? "" : " open"}>` +
      `<summary>修改任务目标</summary>` +
      `<div class="wb-goal-field mt-2">` +
      `<textarea id="wb-goal" rows="3" maxlength="1000" aria-label="任务目标" ` +
      `placeholder="例如：分析这款宠物饮水机在美国站的竞品价格、核心卖点与差评点，并生成一份英文 Listing 草稿。">` +
      `${U.esc(state.goal || "")}</textarea>` +
      `<span class="wb-goal-count"><span id="wb-goal-count">${(state.goal || "").length}</span>/1000</span>` +
      `</div>` +
      `<div class="wb-examples">` +
      ["分析竞品价格与核心卖点并生成 Listing", "分析差评，优化产品卖点", "生成多版本标题和五点描述"]
        .map(function (text) {
          return `<button type="button" class="chip" data-goal="${U.esc(text)}">${U.esc(text)}</button>`;
        }).join("") +
      `</div></details>`
    );
  }

  function specFields() {
    const specs = state.ownSpecs || {};
    const field = function (key, label, placeholder) {
      return `<label class="field"><span class="field-label">${label}</span>` +
        `<input id="wb-spec-${key}" value="${U.esc(specs[key] || "")}" placeholder="${placeholder}" /></label>`;
    };
    return (
      `<div class="wb-grid-3 mt-3">` +
      field("size", "尺寸", "例如 20 × 15 × 15 cm") +
      field("material", "材质", "例如 ABS、304 不锈钢") +
      field("capacity", "容量", "例如 2L") +
      field("color", "颜色", "例如 哑光黑") +
      field("weight", "重量", "例如 480g") +
      field("quantity", "数量", "例如 1 件装") +
      `</div>`
    );
  }

  function competitorFields() {
    const products = state.products || [];
    const parsedCount = parseCompetitors(state.competitorsText).length;
    const productPicker = products.length
      ? `<label class="field"><span class="field-label">从店铺商品里挑</span>` +
        `<select id="wb-product-pick">` +
        `<option value="">手动填写商品名称</option>` +
        products.map(function (p) {
          return `<option value="${U.esc(p.name)}">${U.esc(p.name)}${p.asin ? " · " + U.esc(p.asin) : ""}</option>`;
        }).join("") +
        `</select></label>`
      : "";
    return (
      `<div class="wb-grid-3">` +
      `<label class="field"><span class="field-label">商品名称 <span class="t-danger">*</span></span>` +
      `<input id="wb-product" value="${U.esc(state.productName)}" placeholder="例如 EcoSip 保温杯 750ml" /></label>` +
      `<label class="field"><span class="field-label">站点 <span class="t-danger">*</span></span>` +
      `<select id="wb-marketplace">` +
      ["US", "DE", "JP", "UK"].map(function (m) {
        return `<option value="${m}"${m === state.marketplace ? " selected" : ""}>${window.CPLabel.site(m)}</option>`;
      }).join("") +
      `</select></label>` +
      `<label class="field"><span class="field-label">类目</span>` +
      `<input id="wb-category" value="${U.esc(state.productCategory || "")}" placeholder="例如 Pet Supplies > Pet Fountains" /></label>` +
      `</div>` +
      productPicker +
      `<label class="field"><span class="field-label">竞品数据 <span class="t-danger">*</span>` +
      `<span class="t-xs t-muted" id="wb-competitor-count">${parsedCount ? `· 已识别 ${parsedCount} 个` : ""}</span></span>` +
      `<textarea id="wb-competitors" rows="4" spellcheck="false" placeholder="竞品 A | 25.99 | 4.2 | 380 | 盖子漏水&#10;竞品 B | 19.99">${U.esc(state.competitorsText)}</textarea>` +
      `<span class="field-help">每行「名称 | 价格 | 评分 | 评论数 | 一条评论」，只有名称必填；整块从表格粘贴也行。` +
      `要导入 Excel/CSV，请先到 <a href="/data" data-link>数据资产</a> 导入。</span></label>`
    );
  }

  function listingFields() {
    const products = state.products || [];
    const picked = state.listingProduct;
    const productOptions = products.length
      ? products.map(function (p) {
          const on = picked && picked.product_id === p.product_id ? " selected" : "";
          return `<option value="${U.esc(p.product_id)}"${on}>` +
            `${U.esc(p.name)}${p.asin ? " · " + U.esc(p.asin) : ""}</option>`;
        }).join("")
      : "";
    const productField = products.length
      ? `<label class="field"><span class="field-label">商品 <span class="t-danger">*</span></span>` +
        `<select id="wb-ls-product">` +
        `<option value="">选择要生成 Listing 的商品</option>` + productOptions +
        `</select></label>`
      : `<label class="field"><span class="field-label">商品名称 <span class="t-danger">*</span></span>` +
        `<input id="wb-ls-name" value="${U.esc(state.listingName || state.productName || "")}" placeholder="还没有店铺商品，先写商品名称" />` +
        `<span class="field-help">${U.esc(state.productsError || "接到店铺后这里会变成商品选择器。")}</span></label>`;
    return (
      `<div class="wb-grid-3">` + productField +
      `<label class="field"><span class="field-label">站点</span>` +
      `<select id="wb-ls-marketplace">` +
      LISTING_SITES.map(function (m) {
        return `<option value="${m}"${(state.listingMarketplace || "US") === m ? " selected" : ""}>` +
          `${U.esc(window.CPLabel.site(m))}</option>`;
      }).join("") + `</select></label>` +
      `<label class="field"><span class="field-label">文案语言</span>` +
      `<select id="wb-ls-language">` +
      ["en-US", "de-DE", "ja-JP"].map(function (code) {
        return `<option value="${code}"${(state.listingLanguage || "en-US") === code ? " selected" : ""}>` +
          `${U.esc(window.CPLabel.language(code))}</option>`;
      }).join("") + `</select></label>` +
      `</div>` +
      `<label class="field"><span class="field-label">平台</span>` +
      `<select id="wb-ls-platform">` +
      ["amazon", "ebay"].map(function (p) {
        return `<option value="${p}"${(state.listingPlatform || "amazon") === p ? " selected" : ""}>` +
          `${U.esc(window.CPLabel.platform(p))}</option>`;
      }).join("") + `</select></label>`
    );
  }

  function clarifyCard() {
    const listing = isListingMode();
    return (
      `<div class="wb-card wb-clarify" id="wb-clarify">` +
      `<div class="wb-card-head">` +
      `<div><div class="wb-card-title">${state.continuing ? "继续当前任务" : "确认执行参数"}</div>` +
      `<div class="wb-card-sub">${listing ? "选一个商品就能生成，竞品数据不是必需" : "只差商品和竞品，其余参数可选"}</div></div>` +
      `<button type="button" class="btn-icon" data-act="back" aria-label="取消并返回">${U.icon("x")}</button>` +
      `</div>` +
      `<div class="wb-card-body">` +
      resolveSummary() +
      missingCallout() +
      (state.needKey
        ? `<div class="callout callout-warn">${U.icon("alert")}<div><strong>这一步需要模型</strong><br>` +
          `到「设置 → 模型与密钥」填入你自己的 API Key 后就能继续。` +
          `<div class="mt-2"><a class="btn btn-sm" href="/settings" data-link>去配置 API Key</a></div></div></div>`
        : "") +
      (listing ? listingFields() : competitorFields()) +
      `<details class="wb-more"${state.moreParamsOpen || state.missingFocus ? " open" : ""}>` +
      `<summary>更多参数（可选，填了结果更准）</summary>` +
      (listing
        ? `<label class="field mt-3"><span class="field-label">规格（每行「键: 值」）</span>` +
          `<textarea id="wb-ls-specs" rows="3" spellcheck="false" placeholder="容量: 750ml&#10;材质: 304 不锈钢">${U.esc(state.listingSpecsText || "")}</textarea></label>` +
          `<label class="field mt-3"><span class="field-label">卖点（每行一条）</span>` +
          `<textarea id="wb-ls-features" rows="3" placeholder="双层真空保温 24 小时">${U.esc(state.listingFeaturesText || "")}</textarea></label>`
        : specFields()) +
      (isCompetitorOnly()
        ? `<span class="t-xs t-muted mt-3">已显式选择「竞品分析」：本次只做分析，不生成 Listing。</span>`
        : listing
          ? ""
          : `<label class="row gap-2 mt-3" style="cursor:pointer">` +
            `<input type="checkbox" id="wb-with-listing" ${state.withListing ? "checked" : ""} />` +
            `<span class="t-sm">同时生成 Listing 草稿</span></label>` +
            `<label class="field mt-3"><span class="field-label">Listing 语言</span>` +
            `<select id="wb-language">` +
            ["en-US", "de-DE", "ja-JP"].map(function (code) {
              return `<option value="${code}"${code === state.listingLanguage ? " selected" : ""}>${window.CPLabel.language(code)}</option>`;
            }).join("") + `</select></label>`) +
      `</details>` +
      goalEditor() +
      (state.error ? `<p class="callout callout-danger">${U.esc(state.error)}</p>` : "") +
      `</div>` +
      `<div class="wb-card-foot">` +
      (listing
        ? `<button type="button" class="btn btn-primary" id="wb-ls-run" ${state.busy ? "disabled" : ""}>` +
          `${state.busy ? "生成中…" : "开始生成"}</button>`
        : `<button type="button" class="btn btn-primary" id="wb-run-task" ${state.busy ? "disabled" : ""}>` +
          `${state.busy ? "执行中…" : "开始执行"}</button>`) +
      `<button type="button" class="btn btn-quiet" id="wb-demo">载入示例数据</button>` +
      `<button type="button" class="btn btn-quiet" data-act="back">取消</button>` +
      `</div>` +
      `</div>`
    );
  }

  /* ================= Listing 完整编辑器（右侧抽屉） =================
   * 只能改文案（标题/五点/描述/搜索词），商品事实快照与事实台账不动；
   * 保存时派生新版本并自动重新质检——编辑不能让不实声明绕过质检。 */
  function listingToEditorFields(listing) {
    const bullets = (listing.bullets || []).map(function (b) {
      return `${b.headline || ""} | ${b.body || ""}`;
    }).join("\n");
    return {
      title: listing.title || "",
      bullets: bullets,
      description: listing.description || "",
      search_terms: listing.search_terms || "",
    };
  }

  function openListingEditor(root) {
    const listing = state.listing;
    if (!listing || !listing.listing_id) return;
    /* 重开不等退场：旧的立刻移除，避免两个同 id scrim 并存 */
    const prev = document.getElementById("wb-ls-editor-scrim");
    if (prev) prev.remove();
    document.removeEventListener("keydown", onListingEditorKeydown);
    const fields = listingToEditorFields(listing);

    const scrim = document.createElement("div");
    scrim.className = "drawer-scrim";
    scrim.id = "wb-ls-editor-scrim";
    scrim.innerHTML =
      `<aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="wb-ls-editor-title">` +
      `<div class="drawer-head"><div>` +
      `<div class="card-title" id="wb-ls-editor-title">编辑 Listing</div>` +
      `<div class="card-sub">保存会生成新版本（当前第 ${U.esc(String(listing.version || 1))} 版），并重新质检</div>` +
      `</div><button type="button" class="btn-icon" data-ls-close aria-label="关闭">${U.icon("close")}</button></div>` +
      `<div class="drawer-body">` +
      `<label class="field"><span class="field-label">标题</span>` +
      `<input id="wb-ls-edit-title" value="${U.esc(fields.title)}" /></label>` +
      `<label class="field mt-3"><span class="field-label">五点（每行「小标题 | 正文」）</span>` +
      `<textarea id="wb-ls-edit-bullets" rows="7" spellcheck="false">${U.esc(fields.bullets)}</textarea></label>` +
      `<label class="field mt-3"><span class="field-label">描述</span>` +
      `<textarea id="wb-ls-edit-desc" rows="6">${U.esc(fields.description)}</textarea></label>` +
      `<label class="field mt-3"><span class="field-label">搜索词</span>` +
      `<input id="wb-ls-edit-terms" value="${U.esc(fields.search_terms)}" /></label>` +
      `<p class="callout callout-danger mt-3" id="wb-ls-edit-error" hidden></p>` +
      `</div>` +
      `<div class="drawer-foot">` +
      `<button type="button" class="btn btn-quiet" data-ls-close>取消</button>` +
      `<button type="button" class="btn btn-primary" id="wb-ls-edit-save">保存为新版本</button>` +
      `</div></aside>`;
    document.body.appendChild(scrim);

    scrim.querySelectorAll("[data-ls-close]").forEach(function (btn) {
      btn.addEventListener("click", closeListingEditor);
    });
    scrim.addEventListener("click", function (event) {
      if (event.target === scrim) closeListingEditor();
    });
    document.addEventListener("keydown", onListingEditorKeydown);

    const save = scrim.querySelector("#wb-ls-edit-save");
    save.addEventListener("click", async function () {
      const error = scrim.querySelector("#wb-ls-edit-error");
      error.hidden = true;
      const bullets = scrim.querySelector("#wb-ls-edit-bullets").value
        .split("\n")
        .map(function (line) { return line.trim(); })
        .filter(Boolean)
        .map(function (line) {
          const cut = line.indexOf("|");
          return cut < 0
            ? { headline: line, body: "" }
            : { headline: line.slice(0, cut).trim(), body: line.slice(cut + 1).trim() };
        });
      const payload = {
        title: scrim.querySelector("#wb-ls-edit-title").value.trim(),
        bullets: bullets,
        description: scrim.querySelector("#wb-ls-edit-desc").value,
        search_terms: scrim.querySelector("#wb-ls-edit-terms").value.trim(),
      };
      save.disabled = true;
      save.setAttribute("aria-busy", "true");
      save.innerHTML = `<span class="cp-spin" aria-hidden="true"></span><span class="btn-swap">保存中…</span>`;
      try {
        const data = await A.post(`/api/listings/${encodeURIComponent(listing.listing_id)}/versions`, payload);
        state.listing = data.listing || state.listing;
        closeListingEditor();
        U.toast("已保存为新版本，质检结果已重新计算", "ok");
        render(root);
      } catch (err) {
        save.disabled = false;
        save.removeAttribute("aria-busy");
        save.innerHTML = `<span class="btn-swap">保存为新版本</span>`;
        error.hidden = false;
        error.textContent = err.message || "保存失败，请稍后重试。";
      }
    });
  }

  function closeListingEditor() {
    const scrim = document.getElementById("wb-ls-editor-scrim");
    document.removeEventListener("keydown", onListingEditorKeydown);
    if (!scrim || scrim.dataset.closing) return;
    scrim.dataset.closing = "1";
    const motion = window.CPMotion;
    if (!motion) { scrim.remove(); return; }
    /* 面板与遮罩并行退场、播完一起移除：让 fadeOut 独自移除会把面板退场截断 */
    const jobs = [motion.fadeOut(scrim, { y: 4, remove: false })];
    const drawer = scrim.querySelector(".drawer");
    if (drawer) {
      jobs.push(motion.animate(drawer, [
        { opacity: 1, transform: "translate3d(0,0,0)" },
        { opacity: 0, transform: "translate3d(24px,0,0)" },
      ], { fill: "forwards" }));
    }
    const remove = function () { if (scrim.parentNode) scrim.parentNode.removeChild(scrim); };
    Promise.all(jobs).then(remove, remove);
  }

  function onListingEditorKeydown(event) {
    if (event.key === "Escape") closeListingEditor();
  }

  /* ================= Listing 生成：对话内配置 =================
   * 用户选完商品就能生成：商品资料由商品库带出，规格/卖点是可选项。
   * 竞品数据这条路径完全不需要，因此这里不再出现竞品输入框。 */
  const LISTING_SITES = ["US", "UK", "DE", "JP"];
  const LISTING_LANGUAGES = { US: "en-US", UK: "en-US", DE: "de-DE", JP: "ja-JP" };

  function isListingMode() {
    return Boolean((state.picked && state.picked.key === "listing_generation") || state.listingOnly);
  }

  /** 显式选了「竞品分析」就只做分析：不再顺手生成 Listing。 */
  function isCompetitorOnly() {
    return Boolean(state.picked && state.picked.key === "competitor_analysis");
  }

  /* 选商品 → 名称/价格/站点自动带入，不再要求手写 */
  function applyListingProduct(productId) {
    const product = (state.products || []).find(function (p) {
      return p.product_id === productId;
    });
    state.listingProduct = product || null;
    if (!product) return;
    state.listingName = product.name || state.listingName;
    state.listingPrice = typeof product.price === "number" ? product.price : state.listingPrice;
    if (product.marketplace && LISTING_SITES.indexOf(product.marketplace) >= 0) {
      state.listingMarketplace = product.marketplace;
      state.listingLanguage = LISTING_LANGUAGES[product.marketplace] || state.listingLanguage;
    }
  }

  /* 商品列表只拉一次；拉不到就退回手写商品名，不阻断流程 */
  async function loadProducts(root) {
    if (state.productsLoaded) return;
    state.productsLoaded = true;
    try {
      const data = await A.get("/api/marketplace/products?limit=100");
      state.products = data.items || [];
      state.productsError = state.products.length
        ? ""
        : "店铺里还没有商品，可以先写商品名称，或去「店铺与渠道」同步一批。";
    } catch (err) {
      state.products = [];
      // 409 = 还没添加店铺；这不是故障，是还没接入商品来源
      state.productsError = err.status === 409
        ? "还没有添加店铺：接一个店铺后这里才会出现商品选择器，现在也可以直接写商品名称生成。"
        : "读不到店铺商品，先写商品名称也能生成。";
    }
    if (state.mode === "params") render(root);
  }

  function readListingCard(root) {
    const specs = root.querySelector("#wb-ls-specs");
    const features = root.querySelector("#wb-ls-features");
    const name = root.querySelector("#wb-ls-name");
    const platform = root.querySelector("#wb-ls-platform");
    const market = root.querySelector("#wb-ls-marketplace");
    const language = root.querySelector("#wb-ls-language");
    if (specs) state.listingSpecsText = specs.value;
    if (features) state.listingFeaturesText = features.value;
    if (name) state.listingName = name.value.trim();
    if (platform) state.listingPlatform = platform.value;
    if (market) state.listingMarketplace = market.value;
    if (language) state.listingLanguage = language.value;
  }

  /* 「键: 值」每行一条 → 对象；卖点每行一条 → 数组 */
  function parseSpecs(text) {
    const out = {};
    (text || "").split("\n").forEach(function (line) {
      const index = line.indexOf(":");
      const full = index < 0 ? line.indexOf("：") : index;
      if (full <= 0) return;
      const key = line.slice(0, full).trim();
      const value = line.slice(full + 1).trim();
      if (key && value) out[key] = value;
    });
    return out;
  }

  function parseLines(text) {
    return (text || "").split("\n")
      .map(function (line) { return line.trim(); })
      .filter(Boolean);
  }

  /* ================= 结果面板 ================= */
  function currentUser() {
    try {
      return (window.CPAuth && window.CPAuth.user) || null;
    } catch (err) {
      return null;
    }
  }

  function agentAvatar() {
    return (
      `<span class="msg-avatar msg-avatar-agent" aria-hidden="true">` +
      `<img src="/media/logo-mark.svg?v=3" alt="" width="22" height="22" />` +
      `</span>`
    );
  }

  function userAvatar() {
    const user = currentUser() || {};
    const name = String(user.display_name || user.username || "我");
    const initial = name.slice(0, 1).toUpperCase() || "我";
    const avatar = user.avatar
      ? `<img src="${U.esc(user.avatar)}" alt="" width="30" height="30" />`
      : U.esc(initial);
    return `<span class="msg-avatar msg-avatar-user" aria-hidden="true">${avatar}</span>`;
  }

  function messageBubble(message) {
    if (message.role === "user") {
      return `<div class="msg msg-user"><div class="msg-body"><div class="msg-bubble">${U.esc(message.content)}</div>` +
        `<div class="msg-time">${U.esc(U.fmtTime(message.created_at))}</div></div>` +
        userAvatar() + `</div>`;
    }
    const meta = message.meta || {};
    const tone = message.content_type === "error" ? "t-danger" : "";
    return `<div class="msg msg-agent">${agentAvatar()}<div class="msg-body grow">` +
      `<div class="msg-bubble ${tone}">${U.esc(readableText(message.content))}` +
      (meta.degraded ? `<div class="t-xs t-muted mt-2">这次没能完全读懂你的描述，参数是按文本推断的，开始前请核对一下。</div>` : "") +
      `</div>` +
      `<div class="msg-time">${message.task_id
        ? `<a href="/tasks/${U.esc(message.task_id)}" data-link>查看任务</a> · `
        : ""}${U.esc(U.fmtTime(message.created_at))}</div>` +
      `</div></div>`;
  }

  function checksBlock() {
    if (!state.checks) return "";
    const issues = state.checks.issues || [];
    const metrics = state.checks.metrics || {};
    return (
      `<div class="result-block"><div class="result-head">` +
      `<span class="result-title">数据完整性</span>` +
      `<span class="t-xs t-muted num">竞品 ${U.esc(metrics.competitors || 0)} · 评论 ${U.esc(metrics.reviews || 0)} · 有价格 ${U.esc(metrics.priced_competitors || 0)}</span></div>` +
      `<div class="result-body">` +
      (issues.length
        ? issues.map(function (i) {
            const tone = i.severity === "warning" ? "callout-warn" : i.severity === "error" ? "callout-danger" : "callout-info";
            return `<div class="callout ${tone}" style="margin-bottom:var(--sp-2)">${U.icon("info")}<div>${U.esc(readableText(i.message))}</div></div>`;
          }).join("")
        : `<p class="t-sm t-muted">未发现数据完整性问题。</p>`) +
      `</div></div>`
    );
  }

  function summaryBlock() {
    const s = state.summary;
    if (!s) return "";
    const points = (s.points || []).map(function (p) {
      return `<div class="pain-item"><div class="t-sm">${U.esc(readableText(p.text))}</div>` +
        `<div class="t-xs t-muted">${U.esc(evidenceLabel(p.evidence_kind))}</div></div>`;
    }).join("");
    return (
      `<div class="result-block"><div class="result-head">` +
      `<span class="result-title">市场机会总结</span>` +
      `<span class="row gap-2">${s.data_is_demo ? U.mockFlag() : ""}</span></div>` +
      `<div class="result-body">${points || '<p class="t-sm t-muted">无可用结论</p>'}` +
      (s.limitations && s.limitations.length
        ? `<details class="provenance mt-3"><summary>限制（${s.limitations.length}）</summary>` +
          `<ul class="limit-list">` + s.limitations.map(function (l) { return `<li>${U.esc(l)}</li>`; }).join("") +
          `</ul></details>` : "") +
      `</div></div>`
    );
  }

  function qualityBlock() {
    const q = state.quality;
    if (!q) return "";
    return (
      `<div class="result-block"><div class="result-head">` +
      `<span class="result-title">质量检查</span>` +
      `<span class="badge ${q.passed ? "badge-ok" : "badge-warn"}">${q.passed ? "通过" : "存在问题"}</span></div>` +
      `<div class="result-body">` +
      ((q.errors || []).map(function (e) {
        return `<div class="callout callout-danger" style="margin-bottom:var(--sp-2)">${U.icon("alert")}<div>${U.esc(e)}</div></div>`;
      }).join("")) +
      ((q.warnings || []).map(function (w) {
        return `<div class="callout callout-warn" style="margin-bottom:var(--sp-2)">${U.icon("alert")}<div>${U.esc(w)}</div></div>`;
      }).join("")) +
      ((q.pending_confirmations || []).length
        ? `<div class="t-section mt-2">待确认（${q.pending_confirmations.length}）</div>` +
          `<ul class="limit-list">` + q.pending_confirmations.map(function (p) { return `<li>${U.esc(p)}</li>`; }).join("") + `</ul>`
        : "") +
      (q.issues && q.issues.length
        ? q.issues.slice(0, 6).map(function (issue) {
            return `<div class="callout callout-warn" style="margin-bottom:var(--sp-2)">${U.icon("alert")}` +
              `<div><strong>${U.esc(issue.code)}</strong><br>${U.esc(issue.message)}</div></div>`;
          }).join("")
        : "") +
      `</div></div>`
    );
  }

  /* ---------------- 状态真源：一个任务只能有一个阶段 ---------------- */

  /* 后端会在提示里带字段键名（brand / key_features），翻成人话再显示 */
  function readableText(text) {
    const label = window.CPLabel && window.CPLabel.field ? window.CPLabel.field : null;
    if (!label) return String(text || "");
    return String(text || "").replace(/[a-z][a-z_]{2,}/g, function (word) {
      const translated = label(word);
      return translated && translated !== word ? translated : word;
    });
  }

  const EVIDENCE_LABELS = {
    statistic: "统计",
    inference: "推断",
    review: "评论",
    review_text: "评论",
    price: "价格",
    computed: "计算",
    manual: "人工",
  };

  function evidenceLabel(kind) {
    return EVIDENCE_LABELS[kind] || readableText(kind);
  }

  function pendingData() {
    const task = state.taskRaw || {};
    return state.pending || (task.output || {}).pending || null;
  }

  function waitingMissing() {
    const task = state.taskRaw || {};
    const missing = (task.output || {}).missing || [];
    return Array.isArray(missing) ? missing : [];
  }

  /* 阶段按优先级判定：跑起来 > 缺资料 > 等确认 > 终态。
     暂停/等待不允许再落到「已完成」。 */
  function taskPhase() {
    if (state.mode === "params") return "clarifying";
    if (state.busy || AR.isRunning(state.taskStatus)) return "running";
    if (state.taskStatus === "waiting_for_input") return "missing";
    if (state.taskStatus === "waiting_for_review" || state.taskStatus === "awaiting_approval" || pendingData()) return "waiting";
    if (state.taskStatus === "failed") return "failed";
    if (state.taskStatus === "cancelled") return "cancelled";
    if (state.taskStatus === "partial") return "partial";
    if (state.taskStatus === "succeeded") return "done";
    return state.taskId ? "done" : "idle";
  }

  const PHASES = {
    idle: { label: "待开始", cls: "badge" },
    clarifying: { label: "待补充", cls: "badge badge-warn" },
    running: { label: "运行中", cls: "badge badge-running" },
    missing: { label: "等待补充资料", cls: "badge badge-warn" },
    waiting: { label: "等待确认", cls: "badge badge-warn" },
    done: { label: "已完成", cls: "badge badge-ok" },
    partial: { label: "待复核", cls: "badge badge-warn" },
    failed: { label: "失败", cls: "badge badge-danger" },
    cancelled: { label: "已取消", cls: "badge" },
  };

  function phaseBadge() {
    const meta = PHASES[taskPhase()] || PHASES.idle;
    const label = taskPhase() === "running"
      ? (state.taskStatus === "queued" ? "排队中" : "运行中")
      : meta.label;
    return `<span class="${meta.cls}" data-phase-badge>${U.esc(label)}</span>`;
  }

  function emptyHint(text) {
    return `<p class="t-sm t-muted" style="padding:var(--sp-3) 0">${U.esc(text)}</p>`;
  }

  function listingResultCard() {
    const listing = state.listing;
    if (!listing) return emptyHint("这次任务没有产出 Listing 草稿。");
    const bullets = listing.bullets || [];
    const block = function (title, body, copyText) {
      return (
        `<div class="wb-ls-block">` +
        `<div class="wb-ls-block-head"><span class="wb-ls-block-title">${U.esc(title)}</span>` +
        (copyText ? `<button type="button" class="btn-icon" data-copy="${U.esc(copyText)}" aria-label="复制${U.esc(title)}">${U.icon("copy")}</button>` : "") +
        `</div><div class="wb-ls-block-body">${body}</div></div>`
      );
    };
    return (
      `<div class="wb-ls-card">` +
      `<div class="wb-ls-card-head"><div class="row gap-2 wrap">` +
      `<span class="t-section">Listing 草稿</span>` +
      `<span class="badge">第 ${U.esc(String(listing.version || 1))} 版</span>` +
      (listing.is_demo ? U.mockFlag() : "") +
      `</div>` +
      `<button type="button" class="btn btn-sm" data-ls-edit>编辑</button></div>` +
      block("标题（Title）", `<p class="wb-ls-text">${U.esc(listing.title || "—")}</p>`, listing.title || "") +
      block("五点描述（Bullet Points）",
        bullets.length
          ? `<ol class="wb-ls-bullets">` +
            bullets.map(function (b) {
              return `<li><strong>${U.esc(b.headline || "")}</strong>${b.body ? " — " + U.esc(b.body) : ""}</li>`;
            }).join("") + `</ol>`
          : emptyHint("还没有五点描述。"),
        bullets.map(function (b) { return `${b.headline || ""} — ${b.body || ""}`; }).join("\n")) +
      block("产品描述（Product Description）", `<p class="wb-ls-text">${U.esc(listing.description || "—")}</p>`, listing.description || "") +
      block("Search Terms", `<p class="wb-ls-text">${U.esc(listing.search_terms || "—")}</p>`, listing.search_terms || "") +
      `</div>`
    );
  }

  /* 中断卡：缺资料（可补后重跑）与等确认（可原地恢复）分开说 */
  function decisionCard() {
    const phase = taskPhase();
    if (phase !== "missing" && phase !== "waiting") return "";
    const pending = pendingData() || {};
    const missing = phase === "missing" ? waitingMissing() : (pending.missing_fields || pending.fields || []);
    const reasons = pending.reasons || [];
    const affected = pending.affected_conclusions || [];
    const title = phase === "missing"
      ? (missing.length ? `还差 ${missing.length} 项资料` : "还差一些商品资料")
      : (pending.question || "需要你确认是否继续");
    return (
      `<div class="wb-card wb-decision" data-decision-card>` +
      `<div class="wb-card-head">` +
      `<div><div class="wb-card-title">${U.esc(title)}</div>` +
      `<div class="wb-card-sub">${phase === "missing"
        ? "补上后重新执行，已选商品和竞品会保留"
        : "任务停在这里，等你决定要不要继续"}</div></div>` +
      phaseBadge() +
      `</div>` +
      `<div class="wb-card-body">` +
      (reasons.length
        ? `<ul class="wb-reason-list">` + reasons.map(function (r) { return `<li>${U.esc(r)}</li>`; }).join("") + `</ul>`
        : "") +
      (missing.length
        ? `<div class="row gap-2 wrap">` +
          missing.map(function (f) {
            const text = typeof f === "string" ? f : (f.label || f.field || "");
            return `<span class="tag tag-warn">${U.esc(readableText(text))}</span>`;
          }).join("") + `</div>`
        : "") +
      (affected.length
        ? `<div><div class="t-sm t-bold">受影响的结论</div>` +
          `<ul class="wb-reason-list">` + affected.map(function (a) { return `<li>${U.esc(a)}</li>`; }).join("") + `</ul></div>`
        : "") +
      `</div>` +
      `<div class="wb-card-foot">` +
      (phase === "missing"
        ? `<button type="button" class="btn btn-primary" id="wb-retry-input">补充资料并重试</button>`
        : `<button type="button" class="btn btn-primary" id="wb-confirm-continue">确认并继续</button>` +
          `<button type="button" class="btn btn-quiet" id="wb-confirm-cancel">取消任务</button>`) +
      `<button type="button" class="btn btn-quiet" data-open-drawer>查看已有结果</button>` +
      (state.taskId ? `<a class="btn btn-quiet" href="/tasks/${U.esc(state.taskId)}" data-link>任务详情</a>` : "") +
      `</div>` +
      `</div>`
    );
  }

  function logPanel() {
    if (!state.taskId) return emptyHint("任务开始后这里会显示调用明细。");
    const log = state.logCache;
    if (!log || log.loading) return `<p class="t-sm t-muted" style="padding:var(--sp-3) 0">正在读取调用明细…</p>`;
    if (log.error) return `<div class="callout callout-danger">${U.icon("alert")}<div>${U.esc(log.error)}</div></div>`;
    const totals = log.totals || {};
    const chain = log.chain || [];
    return (
      `<div class="wb-log">` +
      (log.totals && log.totals.llm_calls === 0
        ? `<div class="callout callout-info">${U.icon("info")}<div>这次执行没有调用模型：全部步骤由本地规则与校验完成。</div></div>`
        : "") +
      `<div class="wb-log-totals">` +
      `<span>步骤 <strong>${U.esc(String(totals.steps || chain.length))}</strong></span>` +
      `<span>累计耗时 <strong>${U.esc(U.fmtDuration(totals.duration_ms || 0))}</strong></span>` +
      `<span>模型调用 <strong>${U.esc(String(totals.llm_calls || 0))}</strong></span>` +
      `</div>` +
      (chain.map(function (step) {
        const calls = step.llm_calls || [];
        return (
          `<div class="wb-log-step">` +
          `<div class="wb-log-step-head">` +
          `<span class="wb-log-no">${U.esc(String(step.seq))}</span>` +
          `<span class="t-sm t-bold">${U.esc(step.name || "")}</span>` +
          U.statusBadge(step.status) +
          `<span class="t-xs t-muted">${U.esc(fmt(step.duration_ms))}</span>` +
          `</div>` +
          (calls.length
            ? `<div class="wb-log-calls">` + calls.map(function (call) {
                return `<div class="wb-log-call">` +
                  `<span class="t-xs">${U.esc(call.provider || "")} · ${U.esc(call.model || "")}</span>` +
                  `<span class="t-xs t-muted">${U.esc(fmt(call.latency_ms))} · ${U.esc(String((call.prompt_tokens || 0) + (call.completion_tokens || 0)))} tokens` +
                  `${call.ok ? "" : " · 失败"}</span>` +
                  `</div>`;
              }).join("") + `</div>`
            : (log.totals && log.totals.llm_calls === 0
              ? ""
              : `<div class="t-xs t-muted" style="padding-left:22px">这一步没有模型调用</div>`)) +
          `</div>`
        );
      }).join("") || emptyHint("还没有调用记录。")) +
      `</div>`
    );

    function fmt(ms) {
      if (ms === null || ms === undefined) return "—";
      const value = Number(ms);
      return value >= 1000 ? (value / 1000).toFixed(1) + " s" : value + " ms";
    }
  }

  /* ================= 执行卡 / 结果卡 / 过程抽屉 ================= */

  function runCard() {
    const phase = taskPhase();
    if (phase === "idle" || phase === "clarifying") return "";
    const steps = state.steps || [];
    const planned = plannedStages();
    const total = steps.length || planned.length;
    const done = steps.filter(function (s) {
      return s.status === "succeeded" || s.status === "skipped";
    }).length;
    const active = steps.filter(function (s) { return s.status === "running" })[0];
    const last = steps[steps.length - 1];
    const current = active ? active.name
      : phase === "missing" ? "等待补充资料"
        : phase === "waiting" ? "等待确认"
          : last ? last.name
            : (planned[0] || "");
    const title = phase === "running" ? "执行中"
      : phase === "missing" ? "执行暂停"
        : phase === "waiting" ? "等待确认"
          : phase === "failed" ? "执行失败"
            : phase === "cancelled" ? "已取消"
              : "执行完成";
    const paused = phase === "missing" || phase === "waiting";
    const track = (steps.length
      ? steps.map(function (s, index) {
          const isPausePoint = paused && index === steps.length - 1;
          const cls = isPausePoint ? "is-paused"
            : s.status === "running" ? "is-running"
              : s.status === "failed" ? "is-failed"
                : (s.status === "succeeded" || s.status === "skipped") ? "is-done"
                  : "";
          return `<span class="wb-stage-seg ${cls}" title="${U.esc(readableText(s.name))}"></span>`;
        }).join("")
      : planned.map(function () { return `<span class="wb-stage-seg"></span>`; }).join(""));
    const sub = paused
      ? `流程暂停 · ${done} / ${total} 步已有结果`
      : steps.length ? `已完成 ${done} / ${total} 步` : "任务已提交，等待执行器";
    return (
      `<div class="wb-card wb-run-card" data-run-card>` +
      `<div class="wb-card-head">` +
      `<div><div class="wb-card-title">${U.icon("tasks")}${U.esc(title)}</div>` +
      `<div class="wb-card-sub">${U.esc(sub)}</div></div>` +
      `</div>` +
      `<div class="wb-card-body">` +
      (phase === "running" && !steps.length
        ? `<div class="progress is-indeterminate"><div class="progress-bar"></div></div>`
        : `<div class="wb-stage-track">${track}</div>`) +
      `<div class="wb-stage-line"><span class="t-xs t-muted">当前阶段</span>` +
      `<span class="wb-stage-name">${U.esc(current || "尚未开始")}</span></div>` +
      (state.selectedSkills.length
        ? `<div class="t-xs t-muted">本次能力：${U.esc(state.selectedSkills.map(function (s) {
          return s.name || s.skill_key;
        }).join("、"))}` +
          (state.routing && state.routing.note ? ` · ${U.esc(state.routing.note)}` : "") +
          `</div>`
        : "") +
      (phase === "failed" && state.error
        ? `<div class="callout callout-danger">${U.icon("alert")}<div>${U.esc(state.error)}</div></div>`
        : "") +
      `</div>` +
      `<div class="wb-card-foot">` +
      `<button type="button" class="btn btn-quiet btn-sm" data-open-drawer>查看过程</button>` +
      (phase === "running" && state.taskId
        ? `<button type="button" class="btn btn-sm" id="wb-cancel">停止</button>`
        : "") +
      (state.taskId ? `<a class="btn btn-quiet btn-sm" href="/tasks/${U.esc(state.taskId)}" data-link>任务详情</a>` : "") +
      `</div>` +
      `</div>`
    );
  }

  function resultCard() {
    const phase = taskPhase();
    if (phase !== "done" && phase !== "partial") return "";
    const points = ((state.summary || {}).points || []).slice(0, 3);
    const hasOutput = points.length || state.report || state.listing || state.quality || state.checks;
    if (!hasOutput) {
      return (
        `<div class="wb-card wb-result-card" data-result-card>` +
        `<div class="wb-card-head"><div><div class="wb-card-title">本次结果</div>` +
        `<div class="wb-card-sub">这次执行没有产出可展示的内容</div></div>${phaseBadge()}</div>` +
        `<div class="wb-card-foot"><button type="button" class="btn btn-sm" data-open-drawer>查看执行过程</button></div>` +
        `</div>`
      );
    }
    const quality = state.quality;
    return (
      `<div class="wb-card wb-result-card" data-result-card>` +
      `<div class="wb-card-head">` +
      `<div><div class="wb-card-title">本次结果</div>` +
      `<div class="wb-card-sub">${state.engine ? U.esc(state.engine.label) : "结果已生成"}` +
      `${state.degraded ? " · 参数来自文本识别" : ""}` +
      `${quality && !quality.passed ? " · 质检未通过" : ""}</div></div>` +
      `</div>` +
      `<div class="wb-card-body">` +
      (points.length
        ? `<ul class="wb-result-points">` + points.map(function (p) {
            return `<li><span class="wb-result-point-text">${U.esc(readableText(p.text))}</span>` +
              (p.evidence_kind ? `<span class="wb-evidence">${U.esc(evidenceLabel(p.evidence_kind))}</span>` : "") +
              `</li>`;
          }).join("") + `</ul>`
        : "") +
      `<div class="wb-artifact-row">` +
      (state.report ? `<span class="tag">竞品与评论洞察</span>` : "") +
      (state.listing
        ? `<span class="tag">Listing 草稿 · 第 ${U.esc(String(state.listing.version || 1))} 版</span>`
        : "") +
      (quality
        ? `<span class="badge ${quality.passed ? "badge-ok" : "badge-warn"}">质检${quality.passed ? "通过" : "存在问题"}</span>`
        : "") +
      `</div>` +
      (state.listing
        ? `<div class="wb-listing-preview"><span class="wb-listing-preview-label">标题</span>` +
          `<span>${U.esc(state.listing.title || "—")}</span></div>`
        : "") +
      `</div>` +
      `<div class="wb-card-foot">` +
      `<button type="button" class="btn btn-primary btn-sm" data-open-drawer>查看完整结果</button>` +
      (state.listing ? `<button type="button" class="btn btn-sm" id="wb-ls-edit">编辑草稿</button>` : "") +
      `<button type="button" class="btn btn-quiet btn-sm" data-act="continue">基于此继续</button>` +
      (state.taskId ? `<a class="btn btn-quiet btn-sm" href="/tasks/${U.esc(state.taskId)}" data-link>任务详情</a>` : "") +
      `</div>` +
      `</div>`
    );
  }

  function drawerSection(title, body, open) {
    return (
      `<details class="wb-drawer-sec"${open ? " open" : ""}>` +
      `<summary>${U.esc(title)}</summary>` +
      `<div class="wb-drawer-sec-body">${body}</div>` +
      `</details>`
    );
  }

  function drawerBody() {
    const phase = taskPhase();
    const blocks = [];
    if (phase === "missing" || phase === "waiting") {
      blocks.push(
        `<div class="callout callout-warn">${U.icon("alert")}<div><strong>任务尚未结束</strong><br>` +
        `${phase === "missing" ? "补充资料后重试，已有结果仍保留在这里。" : "确认或取消后，任务才会继续。"}</div></div>`,
      );
    }
    blocks.push(drawerSection("执行过程", AR.stepList(state.steps, state.plan), true));
    const conclusion = [summaryBlock(), checksBlock(), qualityBlock()].filter(Boolean).join("");
    if (conclusion) blocks.push(drawerSection("结论与质检", conclusion, true));
    if (state.report) {
      blocks.push(drawerSection("竞品对比", `<div class="report-block">${R.renderReportPart(state.report, "competitors")}</div>`, false));
      blocks.push(drawerSection("评论洞察", `<div class="report-block">${R.renderReportPart(state.report, "reviews")}</div>`, false));
    }
    if (state.listing) blocks.push(drawerSection("Listing 草稿", listingResultCard(), false));
    blocks.push(drawerSection("调用明细", logPanel(), false));
    return blocks.join("");
  }

  function drawerHtml() {
    return (
      `<div class="wb-drawer-scrim" id="wb-drawer" data-drawer-scrim${state.drawerOpen ? "" : " hidden"}>` +
      `<aside class="wb-drawer" role="dialog" aria-modal="true" aria-labelledby="wb-drawer-title">` +
      `<div class="wb-drawer-head">` +
      `<div><div class="wb-card-title" id="wb-drawer-title">过程与产物</div>` +
      `<div class="wb-card-sub">步骤、证据与调用明细</div></div>` +
      `<button type="button" class="btn-icon" data-drawer-close aria-label="关闭">${U.icon("close")}</button>` +
      `</div>` +
      `<div class="wb-drawer-body" data-drawer-body>${state.drawerOpen ? drawerBody() : ""}</div>` +
      `</aside></div>`
    );
  }

  function composerFollowup() {
    return (
      `<div class="chat-composer"><div class="chat-composer-inner">` +
      `<div class="wb-context-row">` +
      (taskPhase() === "running"
        ? `<span class="wb-context-chip">当前任务运行中，继续追问会新建一次执行</span>`
        : `<span class="wb-context-chip">继续当前任务</span>`) +
      `<span class="wb-context-hint">Enter 发送 · Shift + Enter 换行</span>` +
      `</div>` +
      `<form class="wb-followup" id="wb-followup">` +
      `<input class="wb-followup-input" id="wb-followup-input" placeholder="继续追问，例如：把标题改得更简短" aria-label="继续追问" />` +
      `<button class="wb-followup-send" type="submit">继续</button>` +
      `</form>` +
      `</div></div>`
    );
  }

  function chatShell(inner, opts) {
    const title = state.productName || state.conversationTitle || (state.continuing ? "继续任务" : "新任务");
    return wbShell(
      `<div class="wb-chat" id="wb-chat">` +
      `<header class="wb-chat-head">` +
      `<div class="wb-chat-title" role="status" aria-live="polite"><span class="t-section">${U.esc(title)}</span>${phaseBadge()}` +
      (state.engine
        ? `<span class="badge ${state.engine.kind === "rule" ? "badge-warn" : "badge-ok"}">${U.esc(state.engine.label)}</span>`
        : "") +
      `</div>` +
      `<div class="wb-chat-actions">` +
      (state.taskId ? `<button type="button" class="btn btn-sm btn-quiet" data-open-drawer>过程与产物</button>` : "") +
      `<button type="button" class="btn btn-sm btn-quiet wb-chat-new" data-act="new">${U.icon("plus")}新会话</button>` +
      `</div></header>` +
      `<div class="chat-scroll" id="wb-chat-scroll"><div class="chat-inner">${inner}</div></div>` +
      (opts && opts.composer ? composerFollowup() : "") +
      drawerHtml() +
      `</div>`,
    );
  }

  function renderClarify() {
    const messages = state.messages.length
      ? state.messages.map(messageBubble).join("")
      : `<div class="msg msg-user"><div class="msg-body"><div class="msg-bubble">${U.esc(state.goal || "（未填写目标）")}</div></div>${userAvatar()}</div>`;
    const inner = messages +
      `<div class="msg msg-agent">${agentAvatar()}<div class="msg-body grow">` +
      clarifyCard() +
      `</div></div>`;
    return chatShell(inner, { composer: false });
  }

  function renderRun() {
    const messages = state.messages.length
      ? state.messages.map(messageBubble).join("")
      : state.taskId
        ? `<div class="msg msg-user"><div class="msg-body"><div class="msg-bubble">${U.esc(state.goal || "（未填写目标）")}</div></div>${userAvatar()}</div>` +
          `<div class="msg msg-agent">${agentAvatar()}<div class="msg-body grow">` +
          `<div class="msg-bubble">正在创建任务…</div></div></div>`
        : `<div class="wb-chat-empty">${U.icon("chat")}<p>这个会话还没有消息，在下面输入一句话开始。</p></div>`;
    const inner = messages +
      `<div data-run-card>${runCard()}</div>` +
      `<div data-decision-card>${decisionCard()}</div>` +
      `<div data-result-card>${resultCard()}</div>`;
    return chatShell(inner, { composer: true });
  }

  /* 轮询只替换三块状态卡与抽屉内容，不碰对话流和正在输入的追问 */
  function refreshRunPanels(root) {
    if (state.mode !== "run") return;
    let changed = false;
    const paint = function (selector, html) {
      const host = root.querySelector(selector);
      if (!host) return;
      if (host.innerHTML !== html) {
        host.innerHTML = html;
        changed = true;
      }
    };
    paint("[data-run-card]", runCard());
    paint("[data-decision-card]", decisionCard());
    paint("[data-result-card]", resultCard());
    const badge = root.querySelector(".wb-chat-head [data-phase-badge]");
    if (badge && badge.outerHTML !== phaseBadge()) {
      badge.outerHTML = phaseBadge();
      changed = true;
    }
    if (state.drawerOpen) {
      const body = root.querySelector("[data-drawer-body]");
      const html = drawerBody();
      if (body && body.innerHTML !== html) {
        /* 轮询每秒都会重绘抽屉：保留用户展开的分区和滚动位置 */
        const openSections = Array.prototype.map.call(
          body.querySelectorAll(".wb-drawer-sec"),
          function (el) { return el.open; },
        );
        const top = body.scrollTop;
        body.innerHTML = html;
        body.querySelectorAll(".wb-drawer-sec").forEach(function (el, i) {
          if (openSections[i] !== undefined) el.open = openSections[i];
        });
        body.scrollTop = top;
        changed = true;
      }
    }
    if (changed) window.CPIcon.hydrate(root);
  }

  /* ================= 渲染与事件 ================= */
  function render(root) {
    /* 分段切换 / 会话列表刷新都会重绘首页，先把输入框里的草稿收起来 */
    const live = root.querySelector("#composer-input");
    if (live) state.composerDraft = live.value;

    /* 旧节点即将被 innerHTML 销毁：先解绑挂在上面的墨条 */


    const body = state.mode === "run" ? renderRun()
      : state.mode === "params" ? renderClarify()
        : renderEmpty();
    root.innerHTML = `<div class="view">${body}</div>`;
    window.CPIcon.hydrate(root);
    bind(root);
    dockView(root, ".wb-shell");

    const input = root.querySelector("#composer-input");
    if (input && state.composerDraft) {
      input.value = state.composerDraft;
      input.style.height = Math.min(input.scrollHeight, 200) + "px";
      const send = root.querySelector("#composer-send");
      if (send) send.disabled = false;
    }
    const scroller = root.querySelector("#wb-chat-scroll");
    if (scroller && state.mode === "run") scroller.scrollTop = scroller.scrollHeight;
    loadConversations(root);
  }

  function renderInPlace(root) {
    /* 轮询只替换状态卡与抽屉，对话流和正在输入的追问保持不动 */
    if (state.mode !== "run") { render(root); return; }
    refreshRunPanels(root);
  }

  function loadConversations(root) {
    A.get("/api/conversations?limit=30").then(function (data) {
      state.conversations = data.items || [];
      /* 左栏是异步补上的；正在重命名时不打断输入 */
      if (!state.renamingId) refreshRail(root);
    }).catch(function () { /* 会话列表失败不影响主流程 */ });
  }

  function openDrawer(root, restoreSelector) {
    const scrim = root.querySelector("#wb-drawer");
    if (!scrim) return;
    state.drawerOpen = true;
    scrim.hidden = false;
    const body = scrim.querySelector("[data-drawer-body]");
    if (body) body.innerHTML = drawerBody();
    window.CPIcon.hydrate(scrim);
    ensureLog(root);
    const close = scrim.querySelector("[data-drawer-close]");
    if (close) close.focus();
    scrim.setAttribute("data-return-focus", restoreSelector || "");
  }

  function closeDrawer(root) {
    const scrim = root.querySelector("#wb-drawer");
    if (!scrim || scrim.hidden) return;
    state.drawerOpen = false;
    scrim.hidden = true;
    const sel = scrim.getAttribute("data-return-focus");
    const back = sel ? root.querySelector(sel) : null;
    if (back) back.focus();
  }

  function ensureLog(root) {
    if (!state.taskId) return;
    if (state.logCache && !state.logCache.error) return;
    state.logCache = { loading: true };
    A.get(`/api/tasks/${encodeURIComponent(state.taskId)}/trace`)
      .then(function (data) {
        state.logCache = data || {};
        renderInPlace(root);
      })
      .catch(function (err) {
        state.logCache = { error: err.message || String(err) };
        renderInPlace(root);
      });
  }

  async function confirmPending(root, decision) {
    if (!state.taskId) return;
    const pending = pendingData() || {};
    try {
      await A.post(`/api/tasks/${encodeURIComponent(state.taskId)}/confirm`, {
        decision: decision,
        confirmation_token: pending.confirmation_token || "",
      });
      U.toast(decision === "continue" ? "已继续生成" : "已取消", "ok");
      const detail = await A.get(`/api/tasks/${encodeURIComponent(state.taskId)}`);
      applyTaskDetail(detail);
      state.logCache = null;
      render(root);
      startPolling(root, state.taskId);
    } catch (err) {
      U.toast(err.message || String(err), "danger");
    }
  }

  function bind(root) {
    root.oninput = function (event) {
      const target = event.target as HTMLElement | null;
      if (target && target.id === "wb-goal") {
        const value = (target as HTMLTextAreaElement).value;
        state.goal = value;
        const counter = root.querySelector("#wb-goal-count");
        if (counter) counter.textContent = String(value.length);
      }
    };

    root.onclick = function (event) {
      /* 两个下拉各自开关：专家在右下角，技能在左下角，互斥展开 */
      const onToggle = !!event.target.closest("#wb-assistant");
      const onSkills = !!event.target.closest("#wb-skills-toggle");
      const inAssistant = !!event.target.closest(".wb-assistant-wrap");
      const inSkills = !!event.target.closest(".wb-skills-wrap");
      if (state.assistantOpen && !inAssistant) {
        state.assistantOpen = false;
        refreshAssistant(root);
      }
      if (state.skillsOpen && !inSkills) {
        state.skillsOpen = false;
        refreshSkills(root);
      }

      if (onToggle) {
        state.assistantOpen = !state.assistantOpen;
        state.skillsOpen = false;
        refreshAssistant(root);
        refreshSkills(root);
        return;
      }

      if (onSkills) {
        state.skillsOpen = !state.skillsOpen;
        state.assistantOpen = false;
        refreshSkills(root);
        refreshAssistant(root);
        return;
      }

      /* 过程与产物抽屉：开、关、点遮罩关 */
      const drawerClose = event.target.closest("[data-drawer-close]");
      if (drawerClose) { closeDrawer(root); return; }
      if (event.target.matches("[data-drawer-scrim]")) { closeDrawer(root); return; }
      const drawerOpen = event.target.closest("[data-open-drawer]");
      if (drawerOpen) { openDrawer(root, "[data-open-drawer]"); return; }

      const agent = event.target.closest("[data-agent]");
      if (agent) {
        state.agentKey = agent.getAttribute("data-agent");
        state.picked = null;
        state.assistantOpen = false;
        state.skillsOpen = false;
        refreshAssistant(root);
        refreshSkills(root);
        paintEcho(root);
        const input = root.querySelector("#composer-input");
        if (input) input.focus();
        return;
      }

      /* 会话标题行内重命名：优先于打开会话 */
      const rename = event.target.closest("[data-rename]");
      if (rename) {
        state.renamingId = rename.getAttribute("data-rename");
        refreshRail(root);
        return;
      }

      const pick = event.target.closest("[data-pick-skill]");
      if (pick) {
        const skill = C.skillByKey(pick.getAttribute("data-pick-skill"));
        state.assistantOpen = false;
        state.skillsOpen = false;
        refreshAssistant(root);
        refreshSkills(root);
        if (!skill) return;
        if (skill.status !== "available") {
          U.toast("这个技能暂时用不了，换一个试试", "danger");
          return;
        }
        if (!WORKBENCH_SKILLS[skill.key]) {
          U.toast(`「${skill.name}」需要专属参数，已打开技能详情`, "ok");
          window.location.assign(`/skills?skill=${encodeURIComponent(skill.key)}`);
          return;
        }
        pickSkill(root, skill);
        return;
      }

      const conversation = event.target.closest("[data-conversation]");
      if (conversation) {
        openConversation(root, conversation.getAttribute("data-conversation"));
        return;
      }

      const card = event.target.closest("[data-skill]");
      if (card) {
        const skill = C.skillByKey(card.getAttribute("data-skill"));
        if (!skill) return;
        if (skill.status !== "available") {
          U.toast("这个技能暂时用不了，换一个试试", "danger");
          return;
        }
        /* 提示语只是例句：不能由工作台完整表达的技能，只把话填进输入框 */
        if (!WORKBENCH_SKILLS[skill.key]) {
          state.picked = null;
          refreshAssistant(root);
          refreshSkills(root);
          const input = root.querySelector("#composer-input");
          if (input) {
            input.value = skill.prompt || "";
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.focus();
          }
          return;
        }
        pickSkill(root, skill);
        return;
      }

      const goalChip = event.target.closest("[data-goal]");
      if (goalChip) {
        const text = goalChip.getAttribute("data-goal") || "";
        const field = root.querySelector("#wb-goal");
        if (field) {
          field.value = text;
          state.goal = text;
          const counter = root.querySelector("#wb-goal-count");
          if (counter) counter.textContent = String(text.length);
          field.focus();
        }
        return;
      }

      const copyBtn = event.target.closest("[data-copy]");
      if (copyBtn) { U.copy(copyBtn.getAttribute("data-copy"), "内容"); return; }

      const act = event.target.closest("[data-act]");
      if (act) {
        const name = act.getAttribute("data-act");
        if (name === "back") {
          if (state.continuing && state.taskId) {
            state.continuing = false;
            state.mode = "run";
            render(root);
          } else {
            newSession(root);
          }
        } else if (name === "new") {
          newSession(root);
        } else if (name === "data") {
          U.toast("数据资产在左侧「数据资产」页面管理，导入后这里可以直接引用");
        } else if (name === "skills") {
          state.skillsOpen = true;
          state.assistantOpen = false;
          refreshSkills(root);
          refreshAssistant(root);
        } else if (name === "drop-skill") {
          state.picked = null;
          paintEcho(root);
          refreshAssistant(root);
          refreshSkills(root);
        } else if (name === "demo") {
          fillDemo(root);
        } else if (name === "continue") {
          const input = root.querySelector("#wb-followup-input");
          if (input) input.focus();
        }
        return;
      }

      if (event.target.closest("#wb-demo")) { fillDemo(root); return; }
      if (event.target.closest("#wb-run-task")) { runFlow(root); return; }
      if (event.target.closest("#wb-ls-run")) { runListingOnly(root); return; }
      if (event.target.closest("#wb-ls-edit") || event.target.closest("[data-ls-edit]")) { openListingEditor(root); return; }
      if (event.target.closest("#wb-cancel")) { cancelRun(root); return; }
      if (event.target.closest("#wb-retry-input")) { retryWithMissing(root); return; }
      if (event.target.closest("#wb-confirm-continue")) { void confirmPending(root, "continue"); return; }
      if (event.target.closest("#wb-confirm-cancel")) { void confirmPending(root, "cancel"); return; }
    };

    const lsProduct = root.querySelector("#wb-ls-product");
    if (lsProduct) {
      lsProduct.addEventListener("change", function () {
        readListingCard(root);
        applyListingProduct(lsProduct.value);
        render(root);
        revealParams(root);
      });
    }

    const productPick = root.querySelector("#wb-product-pick");
    if (productPick) {
      productPick.addEventListener("change", function () {
        if (!productPick.value) return;
        const input = root.querySelector("#wb-product");
        if (input) input.value = productPick.value;
        state.productName = productPick.value;
      });
    }

    const competitorBox = root.querySelector("#wb-competitors");
    if (competitorBox) {
      competitorBox.addEventListener("input", function () {
        // 实时更新「已识别 N 个」，不整页重绘，避免输入框失焦
        state.competitorsText = competitorBox.value;
        const label = root.querySelector("#wb-competitor-count");
        const count = parseCompetitors(competitorBox.value).length;
        if (label) label.textContent = count ? `· 已识别 ${count} 个` : "";
      });
    }

    const moreParams = root.querySelector(".wb-clarify details.wb-more");
    if (moreParams) {
      moreParams.addEventListener("toggle", function () {
        state.moreParamsOpen = moreParams.open;
      });
    }

    const lsMarket = root.querySelector("#wb-ls-marketplace");
    if (lsMarket) {
      lsMarket.addEventListener("change", function () {
        readListingCard(root);
        state.listingMarketplace = lsMarket.value;
        state.listingLanguage = LISTING_LANGUAGES[lsMarket.value] || state.listingLanguage;
        render(root);
        revealParams(root);
      });
    }

    root.onsubmit = function (event) {
      const form = event.target;
      if (form.id === "composer-form") {
        event.preventDefault();
        const input = root.querySelector("#composer-input");
        const goal = (input && input.value.trim()) || "";
        if (!goal) return;
        beginGoal(root, goal);
        return;
      }
      if (form.id === "wb-followup") {
        event.preventDefault();
        const input = root.querySelector("#wb-followup-input");
        const goal = (input && input.value.trim()) || "";
        if (!goal) return;
        continueGoal(root, goal);
      }
    };

    root.onkeydown = function (event) {
      const renameInput = event.target && event.target.closest ? event.target.closest("[data-rename-input]") : null;
      if (renameInput) {
        if (event.key === "Enter") {
          event.preventDefault();
          void saveRename(root, renameInput.getAttribute("data-rename-input"), renameInput.value);
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          state.renamingId = null;
          refreshRail(root);
          return;
        }
      }
      if (event.key !== "Escape") return;
      if (state.drawerOpen) {
        event.stopPropagation();
        closeDrawer(root);
        return;
      }
      if (state.assistantOpen) {
        event.stopPropagation();
        state.assistantOpen = false;
        refreshAssistant(root);
        const btn = root.querySelector("#wb-assistant");
        if (btn) btn.focus();
      }
    };

    root.onfocusout = function (event) {
      const renameInput = event.target && event.target.closest ? event.target.closest("[data-rename-input]") : null;
      if (!renameInput || !state.renamingId) return;
      void saveRename(root, renameInput.getAttribute("data-rename-input"), renameInput.value);
    };

    const input = root.querySelector("#composer-input");
    if (input) {
      input.addEventListener("input", function () {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 200) + "px";
        const send = root.querySelector("#composer-send");
        if (send) send.disabled = !input.value.trim();
        /* 目标被清空 = 用户不要这个技能了，别继续挂着提示 */
        if (state.picked && !input.value.trim()) {
          state.picked = null;
          paintEcho(root);
          refreshAssistant(root);
        }
      });
      input.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
        event.preventDefault();
        if (event.isComposing || event.keyCode === 229) return;
        if (input.value.trim()) beginGoal(root, input.value.trim());
      });
    }

    const followup = root.querySelector("#wb-followup-input");
    if (followup) {
      followup.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" || event.shiftKey) return;
        event.preventDefault();
        if (event.isComposing || event.keyCode === 229) return;
        const form = root.querySelector("#wb-followup");
        if (form && form.requestSubmit) form.requestSubmit();
      });
    }
  }

  function stopPolling() {
    if (state.poller) {
      state.poller.stop();
      state.poller = null;
    }
  }

  function resetState() {
    stopPolling();
    state.mode = "empty";
    state.conversationId = null;
    state.conversationTitle = "";
    state.taskId = null;
    state.taskStatus = "";
    state.busy = false;
    state.error = "";
    state.goal = "";
    state.composerDraft = "";
    state.picked = null;
    state.selectedSkills = [];
    state.routing = null;
    state.resolveInfo = null;
    state.report = null;
    state.listing = null;
    state.summary = null;
    state.checks = null;
    state.quality = null;
    state.steps = [];
    state.plan = [];
    state.messages = [];
    state.degraded = false;
    state.degradedReason = "";
    state.taskRaw = null;
    state.drawerOpen = false;
    state.continuing = false;
    state.missingFocus = false;
    state.assistantOpen = false;
    state.skillsOpen = false;
    state.renamingId = null;
    state.needKey = false;
    state.productName = "";
    state.productCategory = "";
    state.competitorsText = "";
    state.withListing = true;
    state.marketplace = "US";
    state.listingLanguage = "en-US";
    state.ownSpecs = { size: "", material: "", capacity: "", color: "", weight: "", quantity: "" };
    state.listingOnly = false;
    state.listingProduct = null;
    state.listingName = "";
    state.listingPrice = null;
    state.listingPlatform = "amazon";
    state.listingMarketplace = "US";
    state.listingSpecsText = "";
    state.listingFeaturesText = "";
    state.listingDetailing = false;
    state.moreParamsOpen = false;
    state.logCache = null;
    state.pending = null;
    state.engine = null;
  }

  function newSession(root) {
    resetState();
    render(root);
    window.scrollTo({ top: 0 });
  }

  async function beginGoal(root, goal) {
    state.goal = goal;
    state.error = "";
    state.composerDraft = "";
    state.needKey = false;
    state.missingFocus = false;
    state.resolveInfo = null;
    if (!state.continuing) {
      state.messages = [];
      state.conversationId = null;
      state.conversationTitle = "";
    }
    /* 用户这句话立刻出现在对话里，后面的澄清卡长在它下面，不跳页 */
    state.messages.push({ role: "user", content: goal, created_at: new Date().toISOString() });
    state.mode = "params";
    render(root);
    try {
      const info = await A.post("/api/agent/resolve", { goal: goal });
      state.resolveInfo = info;
      const spec = info.spec || {};
      /* 规则解析会把整句目标塞进 product_name，那不是商品名——宁可留空让人填 */
      if (!state.productName) {
        const suggested = String(spec.product_name || "").trim();
        const looksLikeName = suggested.length > 0 && suggested.length <= 40 && suggested.indexOf("，") < 0;
        if (!info.degraded && looksLikeName) state.productName = suggested;
      }
      state.marketplace = spec.marketplace || state.marketplace;
      state.listingLanguage = spec.listing_language || state.listingLanguage;
      if (typeof spec.with_listing === "boolean") state.withListing = spec.with_listing;
      if (info.listing_only) state.listingOnly = true;
      if (info.degraded) {
        U.toast("模型不可用，目标已按规则解析，请确认参数", "danger");
      }
    } catch (err) {
      if (err.status === 428) {
        state.needKey = true;
        state.error = "";
        U.toast("这一步要用模型来读你的目标，可以先手动补充参数", "danger");
      } else {
        state.resolveInfo = { degraded: true, reason: err.message, spec: {} };
      }
    }
    if (state.mode === "params") {
      render(root);
      revealParams(root);
      loadProducts(root);
    }
  }

  /* 继续追问：沿用当前会话与已填参数，不再从空白表单开始 */
  function continueGoal(root, goal) {
    if (state.busy) {
      U.toast("当前任务还在运行，等它结束再继续", "danger");
      return;
    }
    state.continuing = true;
    beginGoal(root, goal);
  }

  /* 缺资料暂停：把用户带回澄清卡，展开可选参数并聚焦第一个缺失项 */
  function retryWithMissing(root) {
    state.continuing = true;
    state.missingFocus = true;
    state.mode = "params";
    state.error = "";
    render(root);
    revealParams(root);
    const first = root.querySelector("#wb-spec-size, #wb-ls-specs, #wb-product");
    if (first) first.focus();
  }

  function revealParams(root) {
    const card = root.querySelector("#wb-clarify");
    if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function fillDemo(root) {
    try {
      const demo = await A.get("/api/demo/dataset");
      const req = demo.analysis_request || {};
      state.productName = req.product_name || state.productName || "EcoSip Insulated Water Bottle";
      state.competitorsText = competitorsToText(req.competitors || []);
      if (!state.goal) state.goal = "分析示例竞品的价格与评论痛点，并生成一份英文 Listing";
      state.mode = "params";
      state.error = "";
      render(root);
      U.toast("已载入示例数据（虚构，仅用于体验流程）", "ok");
    } catch (err) {
      U.toast(err.message, "danger");
    }
  }

  /* 生成 Listing：走 listing_only 路径，不需要竞品数据。
   * 三类失败分开说，别统一成「技术报错」：
   *   428 → 模型不可用（去配置 Key）
   *   422 + missing product_name → 还没选商品
   *   其它 → 把服务端给的中文说明原样转达 */
  async function runListingOnly(root) {
    if (state.busy) return;
    readListingCard(root);
    state.error = "";
    const name = (state.listingName || "").trim();
    if (!name) {
      state.error = "还没有选商品：先在上面选一个商品，或写清商品名称。";
      render(root);
      revealParams(root);
      return;
    }

    state.busy = true;
    state.taskStatus = "queued";
    state.report = null;
    state.listing = null;
    state.summary = null;
    state.checks = null;
    state.quality = null;
    state.steps = [];
    state.plan = [];
    state.messages = [];
    state.taskId = null;
    state.listingOnly = true;
    state.missingFocus = false;
    state.logCache = null;
    state.mode = "run";
    render(root);

    try {
      const run = await A.post("/api/agent/runs", {
        agent_key: state.agentKey || "main",
        goal: null,
        product_name: name,
        platform: state.listingPlatform || "amazon",
        marketplace: state.listingMarketplace || "US",
        competitors: [],
        keywords: [],
        own_specs: parseSpecs(state.listingSpecsText),
        own_key_features: parseLines(state.listingFeaturesText),
        own_price: typeof state.listingPrice === "number" ? state.listingPrice : null,
        skill_key: "listing_generation",
        with_listing: true,
        listing_only: true,
        listing_language: state.listingLanguage || "en-US",
        data_source: "manual",
        conversation_id: state.conversationId,
        async_run: true,
      });
      if (run.conversation_id) state.conversationId = run.conversation_id;
      state.plan = run.plan || [];
      state.engine = run.engine || null;
      state.selectedSkills = run.selected_skills || [];
      state.routing = run.routing || null;
      state.taskId = run.task_id;
      state.needKey = false;
      state.taskStatus = run.status || "queued";
      state.busy = true;
      await refreshMessages();
      render(root);
      startPolling(root, run.task_id);
    } catch (err) {
      state.busy = false;
      state.taskStatus = "failed";
      state.mode = "params";
      if (err.status === 428) {
        state.needKey = true;
        state.error = "模型不可用：到「设置 → 模型与密钥」配置你自己的 API Key 并设为当前使用。";
      } else if (err.status === 422) {
        const detail = err.detail || {};
        state.error = detail.message || "参数还不完整，检查一下商品、站点和语言。";
      } else {
        state.error = err.message || "生成失败，请稍后重试。";
      }
      U.toast(state.error, "danger");
      render(root);
      revealParams(root);
    }
  }

  async function runFlow(root) {
    if (state.busy) return;
    const productEl = root.querySelector("#wb-product");
    const compEl = root.querySelector("#wb-competitors");
    const listingEl = root.querySelector("#wb-with-listing");
    const marketEl = root.querySelector("#wb-marketplace");
    const langEl = root.querySelector("#wb-language");
    const goalEl = root.querySelector("#wb-goal");
    const catEl = root.querySelector("#wb-category");
    const specIds = { size: "#wb-spec-size", material: "#wb-spec-material", capacity: "#wb-spec-capacity", color: "#wb-spec-color", weight: "#wb-spec-weight", quantity: "#wb-spec-quantity" };
    if (productEl) state.productName = productEl.value.trim();
    if (compEl) state.competitorsText = compEl.value;
    if (listingEl) state.withListing = listingEl.checked;
    if (marketEl) state.marketplace = marketEl.value;
    if (langEl) state.listingLanguage = langEl.value;
    if (goalEl) state.goal = goalEl.value.trim();
    if (catEl) state.productCategory = catEl.value.trim();
    Object.keys(specIds).forEach(function (key) {
      const el = root.querySelector(specIds[key]);
      if (el) state.ownSpecs[key] = el.value.trim();
    });
    state.listingOnly = false;
    state.missingFocus = false;
    state.error = "";

    /* 安全网：如果技能是通过提示语 chip 带进来的、又不受工作台支持，
       不要在点「开始执行」时才假装能跑。 */
    const pickedKey = state.picked && state.picked.key;
    if (pickedKey && !WORKBENCH_SKILLS[pickedKey]) {
      U.toast(`「${state.picked.name}」需要专属参数，已打开技能详情`, "ok");
      window.location.assign(`/skills?skill=${encodeURIComponent(pickedKey)}`);
      return;
    }

    if (!state.productName) { state.error = "请填写商品名称"; render(root); return; }
    const competitors = parseCompetitors(state.competitorsText);
    if (!competitors.length) {
      state.error = "至少填一个竞品的名称";
      render(root);
      return;
    }

    state.busy = true;
    state.taskStatus = "queued";
    state.report = null;
    state.listing = null;
    state.summary = null;
    state.checks = null;
    state.quality = null;
    state.steps = [];
    state.plan = [];
    state.messages = [];
    state.error = "";
    state.taskId = null;
    state.logCache = null;
    state.mode = "run";
    render(root);

    try {
      const run = await A.post("/api/agent/runs", {
        agent_key: state.agentKey || "main",
        goal: state.goal || null,
        product_name: state.productName,
        platform: "amazon",
        marketplace: state.marketplace,
        category: state.productCategory || null,
        competitors: competitors,
        keywords: [],
        own_specs: Object.keys(state.ownSpecs).reduce(function (acc, key) {
          const value = (state.ownSpecs[key] || "").trim();
          if (value) acc[key] = value;
          return acc;
        }, {}),
        own_key_features: [],
        own_price: null,
        /* 显式选择「竞品分析」时只跑分析；未选择时交给后端 Agent 按目标路由
           （with_listing 用 undefined 让 JSON 省略，避免把表单默认值当成硬约束）。 */
        skill_key: state.picked ? state.picked.key : null,
        with_listing: isCompetitorOnly() ? false : undefined,
        listing_language: state.listingLanguage,
        data_source: "manual",
        conversation_id: state.conversationId,
        async_run: true,
      });

      if (run.conversation_id) state.conversationId = run.conversation_id;
      state.plan = run.plan || [];
      state.engine = run.engine || null;
      state.selectedSkills = run.selected_skills || [];
      state.routing = run.routing || null;
      state.degraded = !!run.degraded;
      state.engine = run.engine || null;
      state.degradedReason = run.degraded_reason || "";
      state.taskId = run.task_id;
      state.needKey = false;
      state.taskStatus = run.status || "queued";
      state.busy = true;
      await refreshMessages();
      render(root);
      startPolling(root, run.task_id);
    } catch (err) {
      state.busy = false;
      state.taskStatus = "failed";
      if (err.status === 428) {
        state.needKey = true;
        state.error = "还没有可用的模型。到「设置 → 模型与密钥」填入你自己的 API Key 并设为当前使用后再运行。";
      } else {
        state.error = err.message || String(err);
      }
      U.toast(state.error, "danger");
      render(root);
    }
  }

  function applyTaskDetail(detail) {
    const task = detail.task || {};
    const result = detail.result || {};
    state.taskId = task.task_id;
    state.taskStatus = task.status;
    state.steps = detail.steps || [];
    state.plan = result.plan && result.plan.length
      ? result.plan
      : ((task.output || {}).plan || state.plan || []);
    state.report = result.report || null;
    state.listing = result.listing || null;
    state.summary = result.summary || null;
    state.checks = result.checks || null;
    state.quality = result.quality || null;
    state.degraded = !!result.degraded;
    state.engine = result.engine || state.engine;
    state.degradedReason = result.degraded_reason || state.degradedReason;
    state.pending = detail.pending || null;
    state.error = task.error_message || "";
    state.busy = AR.isRunning(task.status);
    state.taskRaw = task;
    const payload = task.payload || {};
    if (payload.listing_only) state.listingOnly = true;
    if (payload.product_name) {
      state.productName = payload.product_name;
      if (state.listingOnly) state.listingName = payload.product_name;
    }
    /* 重新打开会话 / 继续追问时，把上次的参数带回表单，别让用户重填 */
    if (Array.isArray(payload.competitors) && payload.competitors.length) {
      state.competitorsText = competitorsToText(payload.competitors);
    }
    if (payload.own_specs && typeof payload.own_specs === "object") {
      Object.keys(state.ownSpecs).forEach(function (key) {
        if (payload.own_specs[key] !== undefined) state.ownSpecs[key] = String(payload.own_specs[key]);
      });
      state.listingSpecsText = Object.keys(payload.own_specs)
        .map(function (key) { return `${key}: ${payload.own_specs[key]}`; })
        .join("\n");
    }
    if (Array.isArray(payload.own_key_features) && payload.own_key_features.length) {
      state.listingFeaturesText = payload.own_key_features.join("\n");
    }
    if (payload.marketplace) {
      state.marketplace = payload.marketplace;
      state.listingMarketplace = payload.marketplace;
    }
    if (payload.listing_language) state.listingLanguage = payload.listing_language;
    if (typeof payload.with_listing === "boolean") state.withListing = payload.with_listing;
    if (payload.platform) state.listingPlatform = payload.platform;
    if (state.listingOnly && typeof payload.own_price === "number") state.listingPrice = payload.own_price;
  }

  function startPolling(root, taskId) {
    stopPolling();
    state.poller = AR.poller({
      taskId: taskId,
      onUpdate: function (detail) {
        if (state.taskId !== taskId) return;
        applyTaskDetail(detail);
        renderInPlace(root);
      },
      onDone: async function (detail) {
        applyTaskDetail(detail);
        await refreshMessages();
        render(root);
        if (state.taskStatus === "succeeded") U.toast("Agent 工作流完成", "ok");
        if (state.taskStatus === "cancelled") U.toast("任务已取消", "ok");
      },
      onError: function (err) {
        // 任务已经跑完就是跑完了：之后某次轮询失败（网络抖动）不该把结果翻成「失败」
        if (state.taskStatus === "succeeded" || state.taskStatus === "cancelled") return;
        state.error = err.message;
        state.busy = false;
        renderInPlace(root);
      },
    });
  }

  async function refreshMessages() {
    if (!state.conversationId) return;
    try {
      const detail = await A.get(`/api/conversations/${encodeURIComponent(state.conversationId)}`);
      state.messages = detail.messages || [];
    } catch (err) {
      /* 会话刷新失败不影响结果渲染 */
    }
  }

  async function cancelRun(root) {
    if (!state.taskId) return;
    try {
      const resp = await AR.cancel(state.taskId);
      U.toast(resp, "ok");
    } catch (err) {
      U.toast(err.message, "danger");
    }
  }

  async function openConversation(root, conversationId) {
    stopPolling();
    state.mode = "run";
    state.busy = true;
    state.taskStatus = "queued";
    state.conversationId = conversationId;
    state.error = "";
    state.report = null;
    state.listing = null;
    state.summary = null;
    state.checks = null;
    state.quality = null;
    state.steps = [];
    state.plan = [];
    render(root);

    try {
      const detail = await A.get(`/api/conversations/${encodeURIComponent(conversationId)}`);
      state.messages = detail.messages || [];
      state.conversationTitle = (detail.conversation || {}).title || "";
      const lastTask = state.messages.slice().reverse().find(function (m) { return m.task_id; });
      if (lastTask) {
        const taskDetail = await A.get(`/api/tasks/${encodeURIComponent(lastTask.task_id)}`);
        applyTaskDetail(taskDetail);
        const meta = lastTask.meta || {};
        state.plan = state.plan.length ? state.plan : (meta.plan || []);
        state.degraded = state.degraded || !!meta.degraded;
        state.goal = state.messages[0] ? state.messages[0].content : "";
        if (state.report) state.productName = state.report.product_name || state.productName;
        state.withListing = !!state.listing;
        if (state.busy) {
          render(root);
          startPolling(root, lastTask.task_id);
          return;
        }
      } else {
        /* 空会话：这是一条还没说过话的会话，不是「正在跑的任务」 */
        state.busy = false;
        state.taskStatus = "";
        state.taskId = null;
        state.goal = "";
        state.productName = "";
        state.listingOnly = false;
      }
      render(root);
    } catch (err) {
      state.busy = false;
      state.taskStatus = "";
      state.error = err.message;
      render(root);
    }
  }

  async function entryImpl(root, params, query) {
    closeListingEditor();

    resetState();
    if (query && query.agent) state.agentKey = query.agent;
    // 技能清单来自接口（唯一真源），拉不到就照常渲染——空态会提示没有可用能力
    await C.ensureSkills();

    // 技能广场点「运行」会带 ?skill= 过来：能由 Agent 接管的直接进入澄清卡
    const wanted = query && query.skill ? C.skillByKey(query.skill) : null;
    if (wanted && WORKBENCH_SKILLS[wanted.key]) {
      state.picked = wanted;
      state.agentKey = "main";
      render(root);
      try {
        window.history.replaceState({}, "", "/workbench");
      } catch (err) {
        /* 地址栏清理失败不影响执行 */
      }
      await beginGoal(root, wanted.prompt || wanted.name);
      return;
    }
    if (wanted) {
      state.composerDraft = wanted.prompt || "";
      U.toast(`「${wanted.name}」需要专属参数，请在技能页运行`, "danger");
    }
    render(root);
    if (query && query.conversation) openConversation(root, query.conversation);
  }

/** 路由入口：先装依赖再跑原逻辑 */
export async function entry(root, params, query) {
  ensureDeps()
  return entryImpl(root, params, query)
}

export { render }

export const workbenchApi = { entry, render }
