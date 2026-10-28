/* 激浪 · AI 助手（真实会话 + Agent Runtime + 异步执行）
 *
 * 版式：左对话 + 右结果（步骤 / 数据 / 原始 三栏 Tab）。
 * - 自然语言目标先经 `/api/agent/resolve` 解析（模型不可用时明确标注降级）；
 * - 执行走 `/api/agent/runs` 的异步模式，轮询真实 task_steps，可取消；
 * - 结果面板不伪造进度：进度条只在"未完成"时以不确定态出现。
 */
(function () {
  "use strict";
  const U = window.CPUi;
  const A = window.CPApi;
  const C = window.CPCatalog;
  const R = window.CPRender;
  const AR = window.CPAsyncRun;

  const state = {
    mode: "empty",            // empty | params | run
    seg: "agent",             // agent | expert | skill（顶部三档切换）
    category: "推荐",
    composerDraft: "",        // 分段切换会重绘首页，输入到一半的话要留住
    goal: "",
    skill: null,
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
    picked: null,             // 当前带进输入框的技能（点卡片选中，不跳页）
    assistantOpen: false,     // 输入框右下角的助手选择器
    conversationId: null,
    conversations: [],
    messages: [],
    taskId: null,
    taskRaw: null,
    poller: null,
    resTab: "steps",
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
    listingDetailing: false,  // 「补充商品资料」是否展开
    moreParamsOpen: false,    // 竞品分析的「更多参数」是否展开
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

  /* 缺 Key 时给一个能点的入口：光有一段文字，访客还得自己去找「设置」在哪 */
  function keyHint() {
    if (!state.needKey) return "";
    return (
      `<div class="row gap-2 mt-2">` +
      `<a class="btn btn-primary btn-sm" href="/settings" data-link>${U.icon("settings")}去配置 API Key</a>` +
      `<span class="t-xs t-muted">本站不提供模型额度，用你自己的 Key 才能生成真实文案</span>` +
      `</div>`
    );
  }

  /* ================= 空态：三段入口（业务 Agent / 专家 / 技能） =================
   * 版式对标 os.linkfox.com 的新任务页：标题 → 分段控件 → 卡片区 → 底部输入框。
   * 分段切换的是「从哪儿开始」，输入框始终在底部——任何一段最终都落到同一句目标上。
   */

  const SEGMENTS = [
    { key: "agent", label: "业务 Agent", icon: "chat" },
    { key: "expert", label: "专家", icon: "user" },
    { key: "skill", label: "技能", icon: "skills" },
  ];

  /* 「试试这样说」用既有技能提示语，不另写一套文案 */
  const QUICK_GOALS = ["competitor_analysis", "market_summary", "listing_generation"];

  function segControl() {
    return (
      `<div class="wb-seg" role="tablist" aria-label="入口">` +
      SEGMENTS.map(function (seg) {
        const on = state.seg === seg.key ? " is-active" : "";
        return (
          `<button type="button" class="wb-seg-item${on}" data-seg="${seg.key}" role="tab" ` +
          `aria-selected="${state.seg === seg.key}">${U.icon(seg.icon)}<span>${seg.label}</span></button>`
        );
      }).join("") +
      `</div>`
    );
  }

  function skillCard(skill) {
    const tone = skill.tone === "info" ? "is-info" : skill.tone === "neutral" ? "is-neutral" : "";
    const on = state.picked && state.picked.key === skill.key;
    return (
      `<button type="button" class="skill-card${on ? " is-selected" : ""}" data-skill="${U.esc(skill.key)}" ` +
      `aria-pressed="${!!on}">` +
      `<span class="skill-card-head">` +
      `<span class="skill-icon ${tone}">${U.esc(skill.icon)}</span>` +
      `<span class="skill-title-wrap"><span class="skill-name">${U.esc(skill.name)}</span>` +
      `<span class="skill-cat">${U.esc(skill.cat)}</span></span>` +
      `<span class="skill-go">${on ? "已带入" : "带入"}${on ? "" : U.icon("arrowRight")}</span>` +
      `</span>` +
      `<span class="skill-desc">${U.esc(skill.desc)}</span>` +
      `<span class="skill-tags">` +
      skill.tags.map(function (t) { return `<span class="tag">${U.esc(t)}</span>`; }).join("") +
      (skill.requires.indexOf("llm") !== -1 ? `<span class="tag tag-warn">需要密钥</span>` : "") +
      `</span></button>`
    );
  }

  function expertCard(agent) {
    const names = agent.skills.map(function (k) { return C.SKILL_NAME[k]; }).filter(Boolean);
    const on = state.agentKey === agent.key;
    return (
      `<button type="button" class="skill-card${on ? " is-selected" : ""}" data-agent="${U.esc(agent.key)}" ` +
      `aria-pressed="${on}">` +
      `<span class="skill-card-head">` +
      `<span class="skill-icon">${U.esc(agent.name.slice(0, 1))}</span>` +
      `<span class="skill-title-wrap"><span class="skill-name">${U.esc(agent.name)}</span>` +
      `<span class="skill-cat">${names.length} 项能力</span></span>` +
      `<span class="skill-go">${on ? "已选" : "选它"}</span>` +
      `</span>` +
      `<span class="skill-desc">${U.esc(agent.summary)}</span>` +
      `<span class="skill-tags">` +
      names.slice(0, 3).map(function (n) { return `<span class="tag">${U.esc(n)}</span>`; }).join("") +
      `</span></button>`
    );
  }

  function visibleSkills() {
    return C.skills.filter(function (s) {
      return s.status === "available";
    }).filter(function (s) {
      return state.category === "推荐" || s.cat === state.category;
    });
  }

  function agentPanel() {
    /* 提示语和技能卡走同一条路：点一下把这句话带进输入框，不直接跳页 */
    const goals = QUICK_GOALS.map(function (key) {
      const skill = C.skillByKey(key);
      return skill
        ? `<button type="button" class="wb-prompt" data-skill="${U.esc(key)}">` +
          `${U.icon("sparkles")}<span>${U.esc(skill.prompt)}</span></button>`
        : "";
    }).join("");
    return (
      `<div class="wb-start">` +
      `<p class="wb-start-lead">说清业务目标，Agent 会依次完成竞品分析与数据完整性检查、归纳市场机会；` +
      `需要文案时再生成 Listing 并做事实核对。每一步都记录在任务里，结果可复核。</p>` +
      `<div class="wb-start-label">试试这样说</div>` +
      `<div class="wb-prompts">${goals}</div>` +
      `</div>`
    );
  }

  function expertPanel() {
    return (
      `<div class="wb-start">` +
      `<p class="wb-start-lead">选一位专家，它就只做那一类事：目标相同，但用的技能和产出不同。` +
      `选好后在下面输入目标即可。</p>` +
      `<div class="skill-grid">${C.AGENTS.map(expertCard).join("")}</div>` +
      `</div>`
    );
  }

  function skillPanel() {
    const chips = C.skillCategories().map(function (c) {
      return `<button type="button" class="chip${c === state.category ? " is-active" : ""}" ` +
        `data-cat="${U.esc(c)}">${U.esc(c)}</button>`;
    }).join("");
    const list = visibleSkills();
    const total = C.skills.length;
    return (
      `<div class="wb-skills">` +
      `<div class="chips wb-chips" role="group" aria-label="技能分类">${chips}</div>` +
      (list.length
        ? `<div class="skill-grid">${list.map(skillCard).join("")}</div>`
        : `<p class="wb-hint">这个分类下还没有能跑的能力。</p>`) +
      `<div class="wb-skills-more"><a class="btn btn-quiet btn-sm" href="/skills" data-link>` +
      `在技能广场查看全部 ${total} 项 ${U.icon("arrowRight")}</a></div>` +
      `</div>`
    );
  }

  function recentBlock() {
    const list = state.conversations.slice(0, 4);
    if (!list.length) return "";
    return (
      `<div class="wb-recent">` +
      `<div class="wb-recent-head"><span class="t-section">最近的会话</span>` +
      `<button type="button" class="btn btn-quiet btn-sm" data-act="new">${U.icon("plus")}新会话</button></div>` +
      `<div class="conv-list">` + list.map(function (c) {
        return `<button type="button" class="conv-item" data-conversation="${U.esc(c.conversation_id)}">` +
          `<span class="conv-title">${U.esc(c.title)}</span>` +
          `<span class="conv-meta"><span>${c.message_count || 0} 条消息</span>` +
          `<span>${U.esc(U.fmtTime(c.updated_at))}</span></span></button>`;
      }).join("") + `</div></div>`
    );
  }

  function assistantLabel() {
    const agent = C.AGENTS.filter(function (a) { return a.key === state.agentKey; })[0];
    return agent ? agent.name : "激浪主控 Agent";
  }

  function assistantMenu() {
    if (!state.assistantOpen) return "";
    return (
      `<div class="wb-menu" role="menu">` +
      C.AGENTS.map(function (agent) {
        const on = state.agentKey === agent.key;
        return `<button type="button" class="wb-menu-item${on ? " is-active" : ""}" ` +
          `data-agent="${U.esc(agent.key)}" role="menuitem">` +
          `<span class="wb-menu-name">${U.esc(agent.name)}</span>` +
          `<span class="wb-menu-desc">${U.esc(agent.summary)}</span></button>`;
      }).join("") +
      `</div>`
    );
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

  /** 点技能卡 / 试一句：留在首页，只把目标放进输入框并把焦点交过去 */
  function pickSkill(root, skill) {
    state.picked = skill;
    state.skill = skill;

    const input = root.querySelector("#composer-input");
    if (input) {
      input.value = skill.prompt || "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }

    /* 卡片选中态就地更新：整页重绘会把滚动位置和焦点一起丢掉 */
    root.querySelectorAll(".skill-card[data-skill]").forEach(function (btn) {
      const on = btn.getAttribute("data-skill") === skill.key;
      btn.classList.toggle("is-selected", on);
      btn.setAttribute("aria-pressed", String(on));
      const go = btn.querySelector(".skill-go");
      if (go) go.innerHTML = on ? "已带入" : "带入" + U.icon("arrowRight");
    });
    window.CPIcon.hydrate(root);
    paintEcho(root);

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
      `<button type="button" class="composer-tool" data-act="skills">${U.icon("skills")}<span>技能</span></button>` +
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
    const panel = state.seg === "agent" ? agentPanel()
      : state.seg === "expert" ? expertPanel()
      : skillPanel();

    return (
      `<div class="wb-empty"><div class="wb-scroll">` +
      `<div class="narrow-note">当前界面为桌面优先设计，建议在 1024px 以上宽度使用。</div>` +
      `<div class="wb-home">` +
      `<h1 class="wb-hero-title">跨境电商 AI 运营助手</h1>` +
      segControl() +
      panel +
      recentBlock() +
      `</div>` +
      (state.mode === "params" ? paramsCard() : "") +
      `</div>` +
      composer() +
      `</div>`
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
  function paramsCard() {
    /* Listing 生成不需要竞品，也不该让人手敲商品名：它有自己的配置卡。
       其它技能（竞品分析）仍然要填竞品，继续用原来的表单。 */
    if (isListingMode()) return listingConfigCard();
    const skillHint = state.skill ? `已选技能：${state.skill.name}` : "默认执行竞品分析";
    const products = state.products || [];
    const parsedCount = parseCompetitors(state.competitorsText).length;
    return (
      `<div class="wb-inline" id="wb-params">` +
      `<div class="card card-pad">` +
      `<div class="row between"><div><div class="card-title">确认执行参数</div>` +
      `<div class="card-sub">${U.esc(skillHint)} · 参数来自目标解析，可在执行前修改</div></div>` +
      `<button type="button" class="btn-icon" data-act="back" aria-label="返回">${U.icon("close")}</button></div>` +

      `<div class="callout callout-info mt-3">${U.icon("info")}` +
      `<div>你的目标：<strong>${U.esc(state.goal || "（未填写）")}</strong><br>` +
      `执行计划：竞品分析 → 数据完整性检查 → 市场机会总结 → 保存报告${state.withListing ? " → Listing 生成 → 质量检查 → 保存草稿" : ""}。` +
      `计划由确定性规则决定，质检不会被跳过。</div></div>` +
      specRow() +

      /* 竞品分析：只留两项必填（商品 + 竞品），其余收进「更多参数」。
         商品可以从店铺商品里挑，省得手打；竞品支持从表格直接粘。 */
      `<label class="field mt-4"><span class="field-label">商品名称 <span class="t-danger">*</span></span>` +
      (products.length
        ? `<select id="wb-product-pick">` +
          `<option value="">从店铺商品里挑（或直接在下面写）</option>` +
          products.map(function (p) {
            return `<option value="${U.esc(p.name)}">${U.esc(p.name)}${p.asin ? " · " + U.esc(p.asin) : ""}</option>`;
          }).join("") +
          `</select>`
        : "") +
      `<input id="wb-product" value="${U.esc(state.productName)}" placeholder="例如 EcoSip Insulated Water Bottle"${products.length ? ' style="margin-top:8px"' : ""} /></label>` +

      `<div class="field mt-3"><span class="field-label">竞品 <span class="t-danger">*</span>` +
      `<span class="t-xs t-muted" id="wb-competitor-count">${parsedCount ? `· 已识别 ${parsedCount} 个` : ""}</span>` +
      `</span>` +
      `<textarea id="wb-competitors" rows="6" spellcheck="false" placeholder="竞品 A | 25.99 | 4.2 | 380 | 盖子漏水&#10;竞品 B">${U.esc(state.competitorsText)}</textarea>` +
      `<span class="field-help">从 Excel 或表格里整块复制粘贴也行；每行「名称 | 价格 | 评分 | 评论数 | 一条评论」，只有名称必填。</span></div>` +

      `<details class="mt-4"${state.moreParamsOpen ? " open" : ""}>` +
      `<summary class="t-sm t-bold" style="cursor:pointer">更多参数（站点、语言、是否同时生成 Listing）</summary>` +
      `<div class="grid-2 mt-3">` +
      `<label class="field"><span class="field-label">站点</span>` +
      `<select id="wb-marketplace">` +
      ["US", "DE", "JP", "UK"].map(function (m) {
        return `<option value="${m}"${m === state.marketplace ? " selected" : ""}>${window.CPLabel.site(m)}</option>`;
      }).join("") +
      `</select></label>` +
      `<label class="field"><span class="field-label">Listing 语言</span>` +
      `<select id="wb-language">` +
      ["en-US", "de-DE", "ja-JP"].map(function (code) {
        return `<option value="${code}"${code === state.listingLanguage ? " selected" : ""}>${window.CPLabel.language(code)}</option>`;
      }).join("") +
      `</select></label>` +
      `</div>` +
      `<label class="row gap-2 mt-3" style="cursor:pointer">` +
      `<input type="checkbox" id="wb-with-listing" ${state.withListing ? "checked" : ""} />` +
      `<span class="t-sm">同时生成 Listing 草稿（要先填 API Key）</span></label>` +
      `</details>` +

      (state.error ? `<p class="callout callout-danger mt-3">${U.esc(state.error)}</p>` : "") +
      keyHint() +

      `<div class="row gap-2 mt-4">` +
      `<button type="button" class="btn btn-primary" id="wb-run" ${state.busy ? "disabled" : ""}>` +
      `${state.busy ? "执行中…" : "开始执行"}</button>` +
      `<button type="button" class="btn" id="wb-demo">载入示例数据</button>` +
      `<button type="button" class="btn btn-quiet" data-act="back">返回</button>` +
      `</div></div></div>`
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
    closeListingEditor();
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
      save.textContent = "保存中…";
      try {
        const data = await A.post(`/api/listings/${encodeURIComponent(listing.listing_id)}/versions`, payload);
        state.listing = data.listing || state.listing;
        closeListingEditor();
        U.toast("已保存为新版本，质检结果已重新计算", "ok");
        render(root);
      } catch (err) {
        save.disabled = false;
        save.textContent = "保存为新版本";
        error.hidden = false;
        error.textContent = err.message || "保存失败，请稍后重试。";
      }
    });
  }

  function closeListingEditor() {
    const scrim = document.getElementById("wb-ls-editor-scrim");
    if (scrim) scrim.remove();
    document.removeEventListener("keydown", onListingEditorKeydown);
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
    return Boolean(state.skill && state.skill.key === "listing_generation");
  }

  function listingConfigCard() {
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
      ? `<label class="field field-span-2"><span class="field-label">商品</span>` +
        `<select id="wb-ls-product">` +
        `<option value="">选择要生成 Listing 的商品</option>` + productOptions +
        `</select>` +
        `<span class="field-help">商品名称与价格从商品库带入，不用手写。</span></label>`
      : `<label class="field field-span-2"><span class="field-label">商品名称 <span class="t-danger">*</span></span>` +
        `<input id="wb-ls-name" value="${U.esc(state.listingName || "")}" placeholder="还没有店铺商品，先写商品名称" />` +
        `<span class="field-help">${U.esc(state.productsError || "接到店铺后这里会变成商品选择器。")}</span></label>`;

    return (
      `<div class="wb-inline" id="wb-params">` +
      `<div class="card card-pad">` +
      `<div class="row between"><div><div class="card-title">生成 Listing</div>` +
      `<div class="card-sub">选好商品就能生成；竞品数据不是必需的</div></div>` +
      `<button type="button" class="btn-icon" data-act="back" aria-label="取消">${U.icon("close")}</button></div>` +

      `<div class="grid-2 mt-4">` + productField +
      `<label class="field"><span class="field-label">平台</span>` +
      `<select id="wb-ls-platform">` +
      ["amazon", "ebay"].map(function (p) {
        return `<option value="${p}"${(state.listingPlatform || "amazon") === p ? " selected" : ""}>` +
          `${U.esc(window.CPLabel.platform(p))}</option>`;
      }).join("") + `</select></label>` +

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

      `<details class="mt-4"${state.listingDetailing ? " open" : ""}>` +
      `<summary class="t-sm t-bold" style="cursor:pointer">补充商品资料（可选，填了文案更准）</summary>` +
      `<label class="field mt-3"><span class="field-label">规格（每行「键: 值」）</span>` +
      `<textarea id="wb-ls-specs" rows="3" spellcheck="false" placeholder="容量: 750ml&#10;材质: 304 不锈钢">${U.esc(state.listingSpecsText || "")}</textarea></label>` +
      `<label class="field mt-3"><span class="field-label">卖点（每行一条）</span>` +
      `<textarea id="wb-ls-features" rows="3" placeholder="双层真空保温 24 小时">${U.esc(state.listingFeaturesText || "")}</textarea>` +
      `<span class="field-help">不填也能生成，但质检会因为缺少可核对的规格而给出更多待确认项。</span></label>` +
      `</details>` +

      (state.error ? `<p class="callout callout-danger mt-3">${U.esc(state.error)}</p>` : "") +
      `<div class="row gap-2 mt-4">` +
      `<button type="button" class="btn btn-primary" id="wb-ls-run" ${state.busy ? "disabled" : ""}>` +
      `${state.busy ? "生成中…" : "生成 Listing"}</button>` +
      `<button type="button" class="btn btn-quiet" data-act="back">取消</button>` +
      `</div></div></div>`
    );
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
        ? "还没有添加店铺：商品选择器要接一个店铺才有货，现在可以先写商品名称直接生成。"
        : "读不到店铺商品，先写商品名称也能生成。";
    }
    if (state.mode === "params") render(root);
  }

  function readListingCard(root) {
    state.listingDetailing = Boolean(root.querySelector("details[open]"));
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
  function messageBubble(message) {
    if (message.role === "user") {
      return `<div class="msg msg-user"><div class="msg-body"><div class="msg-bubble">${U.esc(message.content)}</div>` +
        `<div class="msg-time">${U.esc(U.fmtTime(message.created_at))}</div></div></div>`;
    }
    const meta = message.meta || {};
    const tone = message.content_type === "error" ? "t-danger" : "";
    return `<div class="msg msg-agent"><span class="msg-avatar">激</span><div class="msg-body grow">` +
      `<div class="msg-bubble ${tone}">${U.esc(message.content)}` +
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
            return `<div class="callout ${tone}" style="margin-bottom:var(--sp-2)">${U.icon("info")}<div>${U.esc(i.message)}</div></div>`;
          }).join("")
        : `<p class="t-sm t-muted">未发现数据完整性问题。</p>`) +
      `</div></div>`
    );
  }

  function summaryBlock() {
    const s = state.summary;
    if (!s) return "";
    const points = (s.points || []).map(function (p) {
      return `<div class="pain-item"><div class="t-sm">${U.esc(p.text)}</div>` +
        `<div class="t-xs t-muted">${U.esc(p.evidence_kind)}</div></div>`;
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

  function resultDataPane() {
    const blocks = [
      summaryBlock(),
      checksBlock(),
      state.report
        ? `<div class="result-block"><div class="result-head">` +
          `<span class="result-title">竞品分析结果</span>` +
          `</div><div class="result-body">${R.renderReport(state.report)}</div></div>`
        : "",
      state.listing
        ? `<div class="result-block"><div class="result-head">` +
          `<span class="result-title">Listing 草稿</span>` +
          `<button type="button" class="btn btn-sm" id="wb-ls-edit">编辑</button>` +
          `</div><div class="result-body">${R.renderListing(state.listing)}</div></div>`
        : "",
      qualityBlock(),
    ].filter(Boolean);
    if (!blocks.length) {
      return `<p class="t-sm t-muted" style="padding:var(--sp-4)">任务完成后，结果会显示在这里。</p>`;
    }
    return blocks.join("");
  }

  function resultPane() {
    const running = AR.isRunning(state.taskStatus) || state.busy;
    /* 失败只认服务端的任务状态。state.error 是「表单/请求层面」的错误，
       任务已经建出来之后，它的成败以 task.status 为准——否则一次编辑保存、
       一次轮询抖动都会把结果徽章翻成「失败」。 */
    const failed = state.taskStatus === "failed" || (!state.taskId && Boolean(state.error) && !running);
    const cancelled = state.taskStatus === "cancelled";
    /* 暂停等确认**不是**完成：少了这一档，停在 waiting_for_review 的任务会被
       显示成绿色「已完成」，用户以为跑完了，其实它还在等一个决定。 */
    const waiting = state.taskStatus === "waiting_for_review";
    const tab = state.resTab;

    return (
      `<div class="wb-pane-head">` +
      `<div class="wb-pane-title"><span class="t-section">结果</span>` +
      (running ? `<span class="badge badge-running">${state.taskStatus === "queued" ? "排队中" : "运行中"}</span>`
        : cancelled ? `<span class="badge">已取消</span>`
        : failed ? `<span class="badge badge-danger">失败</span>`
        : waiting ? `<span class="badge badge-warn">等待确认</span>`
        : state.taskId ? `<span class="badge badge-ok">已完成</span>` : "") +
      (state.engine
        ? `<span class="badge ${state.engine.kind === "rule" ? "badge-warn" : "badge-ok"}">` +
          `${U.esc(state.engine.label)}</span>`
        : "") +
      (state.degraded ? `<span class="badge badge-warn">参数已推断</span>` : "") +
      `</div>` +
      `<div class="wb-run-actions">` +
      (running && state.taskId ? `<button type="button" class="btn btn-sm" id="wb-cancel">取消</button>` : "") +
      (state.taskId ? `<a class="btn btn-sm" href="/tasks/${U.esc(state.taskId)}" data-link>任务详情</a>` : "") +
      `</div></div>` +
      AR.resultTabs({ active: tab }) +
      `<div class="res-body"><div class="res-inner">` +
      (running ? `<div class="progress is-indeterminate"><div class="progress-bar"></div></div>` : "") +
      (state.degraded
        ? `<div class="callout callout-warn">${U.icon("alert")}<div><strong>执行参数是按文字推断的</strong><br>` +
          `${U.esc(state.degradedReason || "结果仍然完整，但文案可能需要你再润色一遍。")}</div></div>`
        : "") +
      (waiting
        ? `<div class="callout callout-warn">${U.icon("info")}<div><strong>任务暂停，等你决定</strong><br>` +
          `竞品数据不足以支撑完整结论。打开「任务详情」可以选择继续生成，或取消这条任务。</div></div>`
        : "") +
      (tab === "steps"
        ? AR.stepList(state.steps, state.plan)
        : tab === "data"
          ? resultDataPane()
          : AR.stepList(state.steps, state.plan)) +
      (failed && state.error
        ? `<div class="callout callout-danger">${U.icon("alert")}<div>执行失败：${U.esc(state.error)}</div></div>`
        : "") +
      keyHint() +
      (!running && !state.taskId
        ? `<p class="t-sm t-muted">还没有执行任何任务。</p>`
        : "") +
      `</div></div>`
    );
  }

  function renderRun() {
    const messages = state.messages.length
      ? state.messages.map(messageBubble).join("")
      : `<div class="msg msg-user"><div class="msg-body"><div class="msg-bubble">${U.esc(state.goal || "（未填写目标）")}</div></div></div>` +
        `<div class="msg msg-agent"><span class="msg-avatar">激</span><div class="msg-body grow">` +
        `<div class="msg-bubble">正在创建任务…</div></div></div>`;

    return (
      `<div class="wb-run split" id="wb-run">` +
      `<section class="wb-pane wb-pane-chat">` +
      `<div class="wb-pane-head">` +
      `<div class="wb-pane-title"><span class="t-section">${U.esc(state.productName || "对话")}</span></div>` +
      `<div class="wb-run-actions">` +
      `<button type="button" class="btn btn-quiet btn-sm" data-act="new">${U.icon("plus")}新会话</button>` +
      `</div></div>` +
      `<div class="chat-scroll"><div class="chat-inner">` +
      messages +
      `<div class="msg msg-agent"><span class="msg-avatar">激</span><div class="msg-body grow">` +
      `<div class="plan-card"><div class="plan-head">` +
      `<span class="plan-title">${U.icon("tasks")}执行计划</span>` +
      `<span class="t-xs t-muted">${state.taskId ? "任务 " + U.esc(state.taskId.slice(0, 10)) : ""}</span></div>` +
      `<div class="plan-body">` +
      AR.stepList(state.steps, state.plan) +
      `</div></div></div></div>` +
      `</div></div>` +
      `<div class="chat-composer"><div class="chat-composer-inner">` +
      `<form class="row gap-2" id="wb-followup">` +
      `<input class="grow" id="wb-followup-input" placeholder="继续说明目标，例如：改成日本站并生成日文 Listing" />` +
      `<button class="btn btn-primary btn-sm" type="submit">继续</button>` +
      `</form>` +
      `</div></div>` +
      `</section>` +

      `<aside class="wb-pane wb-pane-res" id="wb-res-pane">` +
      resultPane() +
      `</aside>` +
      `</div>`
    );
  }

  /* ================= 渲染与事件 ================= */
  function render(root) {
    /* 分段切换 / 会话列表刷新都会重绘首页，先把输入框里的草稿收起来 */
    const live = root.querySelector("#composer-input");
    if (live) state.composerDraft = live.value;

    /* params 也走首页骨架：参数卡是本页输出的一段内容，不是另一张页面 */
    const body = state.mode === "run" ? renderRun() : renderEmpty();
    root.innerHTML = `<div class="view">${body}</div>`;
    window.CPIcon.hydrate(root);
    bind(root);

    const input = root.querySelector("#composer-input");
    if (input && state.composerDraft) {
      input.value = state.composerDraft;
      input.style.height = Math.min(input.scrollHeight, 200) + "px";
      const send = root.querySelector("#composer-send");
      if (send) send.disabled = false;
    }
    loadConversations(root);
  }

  function refreshRecent(root) {
    const home = root.querySelector(".wb-home");
    if (!home) return;
    const cur = home.querySelector(".wb-recent");
    const html = recentBlock();
    if (cur) {
      if (html) cur.outerHTML = html;
      else cur.remove();
    } else if (html) {
      home.insertAdjacentHTML("beforeend", html);
    }
    window.CPIcon.hydrate(home);
  }

  function renderInPlace(root) {
    /* 轮询期间只重绘结果面板，保留对话框里正在输入的内容 */
    if (state.mode !== "run") { render(root); return; }
    const draftInput = root.querySelector("#wb-followup-input");
    const draft = draftInput ? draftInput.value : "";
    const pane = root.querySelector("#wb-res-pane");
    if (pane) {
      pane.innerHTML = resultPane();
      window.CPIcon.hydrate(pane);
      bindResultPane(root);
    }
    const restored = root.querySelector("#wb-followup-input");
    if (restored && draft) restored.value = draft;
  }

  function loadConversations(root) {
    A.get("/api/conversations?limit=30").then(function (data) {
      const next = data.items || [];
      const changed = next.length !== state.conversations.length;
      state.conversations = next;
      /* 首页的「最近的会话」是异步补上的，只在条数变化时局部刷新，不整页重绘 */
      if (changed && state.mode === "empty") refreshRecent(root);
    }).catch(function () { /* 会话列表失败不影响主流程 */ });
  }

  /* 左右分栏可拖拽：比例持久化，双击复位 */
  function mountSplit(root) {
    const run = root.querySelector("#wb-run.split");
    if (!run || !window.CPPanels) return;
    window.CPPanels.split(run, {
      storageKey: "cp.split:workbench",
      defaultSize: 0.58,
      min: 0.3,
      max: 0.76,
      label: "调整对话与结果宽度",
    });
  }

  function bindResultPane(root) {
    root.querySelectorAll("[data-res-tab]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.resTab = btn.getAttribute("data-res-tab");
        renderInPlace(root);
      });
    });
    // 直接在面板里绑：结果面板是独立重绘的，走 root 的事件委托在重绘后不够可靠
    const editBtn = root.querySelector("#wb-ls-edit");
    if (editBtn) editBtn.addEventListener("click", function () { openListingEditor(root); });

    root.querySelectorAll("[data-copy]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        U.copy(btn.getAttribute("data-copy"), "内容");
      });
    });
    const cancel = root.querySelector("#wb-cancel");
    if (cancel) cancel.addEventListener("click", function () { cancelRun(root); });
  }

  function bind(root) {
    bindResultPane(root);
    mountSplit(root);

    root.onclick = function (event) {
      /* 助手菜单：点自己只开关，点菜单项交给下面的 [data-agent]，点别处先收起 */
      const onToggle = !!event.target.closest("#wb-assistant");
      const inMenu = !!event.target.closest(".wb-menu");
      if (state.assistantOpen && !onToggle && !inMenu) {
        state.assistantOpen = false;
        refreshAssistant(root);
      }

      if (onToggle) {
        state.assistantOpen = !state.assistantOpen;
        refreshAssistant(root);
        return;
      }

      const seg = event.target.closest("[data-seg]");
      if (seg) {
        const next = seg.getAttribute("data-seg");
        if (next === state.seg) return;
        state.seg = next;
        render(root);
        /* 换入口等于换一屏内容，滚到顶再显示 */
        window.scrollTo({ top: 0 });
        return;
      }

      const agent = event.target.closest("[data-agent]");
      if (agent) {
        state.agentKey = agent.getAttribute("data-agent");
        state.assistantOpen = false;
        render(root);
        const input = root.querySelector("#composer-input");
        if (input) input.focus();
        return;
      }

      const chip = event.target.closest("[data-cat]");
      if (chip) { state.category = chip.getAttribute("data-cat"); render(root); return; }

      const conversation = event.target.closest("[data-conversation]");
      if (conversation) {
        openConversation(root, conversation.getAttribute("data-conversation"));
        return;
      }

      const card = event.target.closest("[data-skill]");
      if (card) {
        const key = card.getAttribute("data-skill");
        const skill = C.skillByKey(key);
        if (!skill) return;
        if (skill.status !== "available") {
          U.toast("这个技能暂时用不了，换一个试试", "danger");
          return;
        }
        /* 不跳页：把技能的目标带进输入框，助手先说明这一步要补什么，
           用户按发送才开始。整页跳到参数表单在这个位置太突然。 */
        pickSkill(root, skill);
        return;
      }

      const act = event.target.closest("[data-act]");
      if (act) {
        const name = act.getAttribute("data-act");
        if (name === "back" || name === "new") {
          newSession(root);
        } else if (name === "data") {
          U.toast("数据资产在左侧「数据资产」页面管理，导入后这里可以直接引用");
        } else if (name === "skills") {
          state.seg = "skill";
          render(root);
          window.scrollTo({ top: 0 });
        } else if (name === "drop-skill") {
          state.picked = null;
          paintEcho(root);
        } else if (name === "demo") {
          fillDemo(root);
        }
        return;
      }

      if (event.target.closest("#wb-demo")) { fillDemo(root); return; }
      if (event.target.closest("#wb-run")) { runFlow(root); return; }
      if (event.target.closest("#wb-ls-run")) { runListingOnly(root); return; }
      if (event.target.closest("#wb-ls-edit")) { openListingEditor(root); return; }
      if (event.target.closest("#wb-cancel")) { cancelRun(root); return; }
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

    const moreParams = root.querySelector("#wb-params details");
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
        beginGoal(root, goal);
      }
    };

    root.onkeydown = function (event) {
      if (event.key === "Escape" && state.assistantOpen) {
        event.stopPropagation();
        state.assistantOpen = false;
        refreshAssistant(root);
        const btn = root.querySelector("#wb-assistant");
        if (btn) btn.focus();
      }
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
        }
      });
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          if (input.value.trim()) beginGoal(root, input.value.trim());
        }
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
    state.taskId = null;
    state.taskStatus = "";
    state.busy = false;
    state.error = "";
    state.goal = "";
    state.composerDraft = "";
    state.picked = null;
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
    state.resTab = "steps";
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
    state.picked = null;
    state.mode = "params";
    render(root);
    window.scrollTo({ top: 0 });
    try {
      const info = await A.post("/api/agent/resolve", { goal: goal });
      state.resolveInfo = info;
      const spec = info.spec || {};
      if (!state.productName) state.productName = spec.product_name || state.productName;
      state.marketplace = spec.marketplace || state.marketplace;
      state.listingLanguage = spec.listing_language || state.listingLanguage;
      if (typeof spec.with_listing === "boolean") state.withListing = spec.with_listing;
      if (info.degraded) {
        U.toast("模型不可用，目标已按规则解析，请确认参数", "danger");
      }
    } catch (err) {
      if (err.status === 428) {
        state.needKey = true;
        state.error = "这一步要用模型来读你的目标。到「设置 → 模型与密钥」填入你自己的 API Key 后就能继续。";
        U.toast(state.error, "danger");
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

  /* 参数卡是本页往下长出来的内容，渲染完把它带进视野，省得用户自己找 */
  function revealParams(root) {
    const card = root.querySelector("#wb-params");
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
    if (productEl) state.productName = productEl.value.trim();
    if (compEl) state.competitorsText = compEl.value;
    if (listingEl) state.withListing = listingEl.checked;
    if (marketEl) state.marketplace = marketEl.value;
    if (langEl) state.listingLanguage = langEl.value;
    state.error = "";

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
    state.mode = "run";
    render(root);

    try {
      const run = await A.post("/api/agent/runs", {
        agent_key: state.agentKey || "main",
        goal: state.goal || null,
        product_name: state.productName,
        platform: "amazon",
        marketplace: state.marketplace,
        competitors: competitors,
        keywords: [],
        own_specs: {},
        own_key_features: [],
        own_price: null,
        with_listing: state.withListing,
        listing_language: state.listingLanguage,
        data_source: "manual",
        conversation_id: state.conversationId,
        async_run: true,
      });

      if (run.conversation_id) state.conversationId = run.conversation_id;
      state.plan = run.plan || [];
      state.engine = run.engine || null;
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
    state.error = task.error_message || "";
    state.busy = AR.isRunning(task.status);
    state.taskRaw = task;
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
        state.busy = false;
      }
      render(root);
    } catch (err) {
      state.busy = false;
      state.error = err.message;
      render(root);
    }
  }

  async function entry(root, params, query) {
    closeListingEditor();
    resetState();
    if (query && query.agent) state.agentKey = query.agent;
    // 技能清单来自接口（唯一真源），拉不到就照常渲染——空态会提示没有可用能力
    await C.ensureSkills();
    render(root);
    if (query && query.conversation) openConversation(root, query.conversation);
  }

  window.CPPageWorkbench = { entry, render };
})();
