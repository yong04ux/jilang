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
    skillsTab: "skills",
    category: "推荐",
    goal: "",
    skill: null,
    productName: "",
    competitorsJson: "",
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
    conversationId: null,
    conversations: [],
    messages: [],
    taskId: null,
    taskRaw: null,
    poller: null,
    resTab: "steps",
    needKey: false,           // 上一步因为没配 Key 被 428 拦下 → 给一个可点的入口
  };

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

  /* ================= 空态 ================= */
  function skillCard(skill) {
    const tone = skill.tone === "info" ? "is-info" : skill.tone === "neutral" ? "is-neutral" : "";
    const flag = skill.status === "available"
      ? `<span class="skill-flag skill-flag-free">已接入</span>`
      : `<span class="skill-flag skill-flag-soon">开发中</span>`;
    return (
      `<button type="button" class="skill-card" data-skill="${U.esc(skill.key)}"` +
      `${skill.status === "available" ? "" : ' data-soon="1"'}>` +
      `<span class="skill-card-head">` +
      `<span class="skill-icon ${tone}">${U.esc(skill.icon)}</span>` +
      `<span class="skill-title-wrap"><span class="skill-name">${U.esc(skill.name)}</span>` +
      `<span class="skill-cat">${U.esc(skill.cat)}</span></span>` + flag + `</span>` +
      `<span class="skill-desc">${U.esc(skill.desc)}</span>` +
      `<span class="skill-tags">` +
      skill.tags.map(function (t) { return `<span class="tag">${U.esc(t)}</span>`; }).join("") +
      `</span></button>`
    );
  }

  function visibleSkills() {
    return C.SKILLS.filter(function (s) {
      if (state.category === "推荐") return true;
      if (state.category === "已接入") return s.status === "available";
      return s.cat === state.category;
    });
  }

  function composer() {
    return (
      `<div class="composer">` +
      `<form class="composer-box" id="composer-form">` +
      `<textarea class="composer-input" id="composer-input" rows="1" ` +
      `placeholder="说清业务目标，例如：分析「EcoSip 保温杯」在美国的竞品，然后生成英文 Listing" ` +
      `aria-label="业务目标"></textarea>` +
      `<div class="composer-bar">` +
      `<div class="composer-tools">` +
      `<button type="button" class="composer-tool" data-act="attach">${U.icon("plus")}<span>附件</span></button>` +
      `<button type="button" class="composer-tool" data-act="skills">${U.icon("skills")}<span>技能</span></button>` +
      `<button type="button" class="composer-tool" data-act="demo">${U.icon("sparkles")}<span>用示例数据</span></button>` +
      `</div>` +
      `<div class="composer-right">` +
      `<button type="submit" class="composer-send" id="composer-send" aria-label="开始执行" disabled>` +
      `${U.icon("arrowUp")}</button>` +
      `</div></div></form>` +
      `<div class="composer-foot">` +
      `<span>内容由业务代码与大模型共同生成，发布前需人工复核</span>` +
      `</div></div>`
    );
  }

  function conversationRail() {
    if (!state.conversations.length) return "";
    return (
      `<div class="wb-skills" style="margin-top:var(--sp-4)">` +
      `<div class="row between mb-2"><span class="t-section">最近的会话</span>` +
      `<button type="button" class="btn btn-quiet btn-sm" data-act="new">${U.icon("plus")}新会话</button></div>` +
      `<div class="conv-list">` + state.conversations.slice(0, 5).map(function (c) {
        return `<button type="button" class="conv-item" data-conversation="${U.esc(c.conversation_id)}">` +
          `<span class="conv-title">${U.esc(c.title)}</span>` +
          `<span class="conv-meta"><span>${c.message_count || 0} 条消息</span>` +
          `<span>${U.esc(U.fmtTime(c.updated_at))}</span></span></button>`;
      }).join("") + `</div></div>`
    );
  }

  function renderEmpty() {
    const chips = C.SKILL_CATEGORIES.map(function (c) {
      return `<button type="button" class="chip${c === state.category ? " is-active" : ""}" ` +
        `data-cat="${U.esc(c)}">${U.esc(c)}</button>`;
    }).join("");

    return (
      `<div class="wb-empty"><div class="wb-scroll">` +
      `<div class="narrow-note">当前界面为桌面优先设计，建议在 1024px 以上宽度使用。</div>` +
      `<div class="wb-hero">` +
      `<h1 class="wb-hero-title">跨境电商 AI 运营助手</h1>` +
      `<p class="wb-hero-sub">说清业务目标，Agent 会解析目标、调用已接入的技能完成分析与撰写；每一步都可追溯，结果可复核。</p>` +
      `</div>` +

      `<div class="wb-skills">` +
      `<div class="wb-skills-tabs" role="tablist">` +
      `<button type="button" class="tab${state.skillsTab === "expert" ? " is-active" : ""}" ` +
      `data-skills-tab="expert" role="tab">专家</button>` +
      `<button type="button" class="tab${state.skillsTab === "skills" ? " is-active" : ""}" ` +
      `data-skills-tab="skills" role="tab">技能</button>` +
      `</div>` +
      (state.skillsTab === "expert" ? "" : `<div class="chips wb-chips" role="group" aria-label="技能分类">${chips}</div>`) +
      (state.skillsTab === "expert" ? expertRow() : `<div class="skill-grid">${visibleSkills().map(skillCard).join("")}</div>`) +
      `<div class="wb-skills-more"><a class="btn btn-quiet btn-sm" href="/skills" data-link>` +
      `查看全部技能 ${U.icon("arrowRight")}</a></div>` +
      `</div></div>` +
      composer() +
      `</div>`
    );
  }

  function expertRow() {
    const cards = C.AGENTS.map(function (agent) {
      return (
        `<div class="skill-card" style="cursor:default">` +
        `<span class="skill-card-head">` +
        `<span class="skill-icon">${U.esc(agent.name.slice(0, 1))}</span>` +
        `<span class="skill-title-wrap"><span class="skill-name">${U.esc(agent.name)}</span>` +
        `<span class="skill-cat">${agent.skills.length} 个技能 · v${U.esc(agent.version)}</span></span>` +
        `<span class="skill-flag skill-flag-free">${agent.status === "beta" ? "Beta" : "可用"}</span></span>` +
        `<span class="skill-desc">${U.esc(agent.summary)}</span>` +
        `<span class="skill-tags">` +
        agent.skills.slice(0, 2).map(function (s) { return `<span class="tag">${U.esc(s)}</span>`; }).join("") +
        `</span></div>`
      );
    }).join("");
    return `<div class="skill-grid">${cards}</div>`;
  }

  /* ================= 参数确认 ================= */
  function specRow() {
    const info = state.resolveInfo;
    if (!info) return "";
    const spec = info.spec || {};
    const tone = info.degraded ? "callout-warn" : "callout-info";
    return (
      `<div class="callout ${tone}" style="margin-top:var(--sp-3)">${U.icon(info.degraded ? "alert" : "info")}` +
      `<div><strong>${info.degraded ? "目标解析已降级" : "目标已解析"}</strong>` +
      (info.degraded && info.reason ? `<br>${U.esc(info.reason)}` : "") +
      `<div class="row gap-2 wrap mt-2">` +
      `<span class="tag">站点 ${U.esc(spec.marketplace || state.marketplace)}</span>` +
      `<span class="tag">语言 ${U.esc(spec.listing_language || state.listingLanguage)}</span>` +
      `<span class="tag">${spec.with_listing === false ? "不生成 Listing" : "生成 Listing"}</span>` +
      (spec.category ? `<span class="tag">品类 ${U.esc(spec.category)}</span>` : "") +
      `</div></div></div>`
    );
  }

  function renderParams() {
    const skillHint = state.skill ? `已选技能：${state.skill.name}` : "默认执行竞品分析";
    return (
      `<div class="wb-empty" style="justify-content:flex-start"><div class="wb-scroll" style="justify-content:flex-start">` +
      `<div class="wb-skills" style="margin-top:0">` +
      `<div class="card card-pad">` +
      `<div class="row between"><div><div class="card-title">确认执行参数</div>` +
      `<div class="card-sub">${U.esc(skillHint)} · 参数来自目标解析，可在执行前修改</div></div>` +
      `<button type="button" class="btn-icon" data-act="back" aria-label="返回">${U.icon("close")}</button></div>` +

      `<div class="callout callout-info mt-3">${U.icon("info")}` +
      `<div>你的目标：<strong>${U.esc(state.goal || "（未填写）")}</strong><br>` +
      `执行计划：竞品分析 → 数据完整性检查 → 市场机会总结 → 保存报告${state.withListing ? " → Listing 生成 → 质量检查 → 保存草稿" : ""}。` +
      `计划由确定性规则决定，质检不会被跳过。</div></div>` +
      specRow() +

      `<div class="grid-2 mt-4">` +
      `<label class="field field-span-2"><span class="field-label">商品名称 <span class="t-danger">*</span></span>` +
      `<input id="wb-product" value="${U.esc(state.productName)}" placeholder="例如 EcoSip Insulated Water Bottle" /></label>` +
      `</div>` +

      `<label class="field mt-3"><span class="field-label">竞品数据（JSON 数组）<span class="t-danger">*</span></span>` +
      `<textarea id="wb-competitors" rows="7" spellcheck="false" placeholder='[{"name":"竞品 A","price":25.99,"reviews":[{"rating":2,"text":"lid leaked"}]}]'>${U.esc(state.competitorsJson)}</textarea>` +
      `<span class="field-help">需要 <code>name</code>；可选 price / rating / reviews / is_demo。也可以先到「数据资产」或「店铺与渠道」导入数据。</span></label>` +

      `<div class="grid-2 mt-3">` +
      `<label class="field"><span class="field-label">站点</span>` +
      `<select id="wb-marketplace">` +
      ["US", "DE", "JP", "UK"].map(function (m) {
        return `<option value="${m}"${m === state.marketplace ? " selected" : ""}>${m}</option>`;
      }).join("") +
      `</select></label>` +
      `<label class="field"><span class="field-label">Listing 语言</span>` +
      `<select id="wb-language">` +
      [["en-US", "英语"], ["de-DE", "德语"], ["ja-JP", "日语"]].map(function (pair) {
        return `<option value="${pair[0]}"${pair[0] === state.listingLanguage ? " selected" : ""}>${pair[1]}</option>`;
      }).join("") +
      `</select></label>` +
      `</div>` +

      `<label class="row gap-2 mt-3" style="cursor:pointer">` +
      `<input type="checkbox" id="wb-with-listing" ${state.withListing ? "checked" : ""} />` +
      `<span class="t-sm">同时生成 Listing 草稿（需要配置了 API Key）</span></label>` +

      (state.error ? `<p class="callout callout-danger mt-3">${U.esc(state.error)}</p>` : "") +
      keyHint() +

      `<div class="row gap-2 mt-4">` +
      `<button type="button" class="btn btn-primary" id="wb-run" ${state.busy ? "disabled" : ""}>` +
      `${state.busy ? "执行中…" : "开始执行"}</button>` +
      `<button type="button" class="btn" id="wb-demo">载入示例数据</button>` +
      `<button type="button" class="btn btn-quiet" data-act="back">返回</button>` +
      `</div></div></div></div></div>`
    );
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
      (meta.degraded ? `<div class="t-xs t-muted mt-2">目标解析降级为规则，参数已按文本推断。</div>` : "") +
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
          `<a class="btn btn-sm" href="/competitors?report=${U.esc(state.report.report_id)}" data-link>打开完整报告</a>` +
          `</div><div class="result-body">${R.renderReport(state.report)}</div></div>`
        : "",
      state.listing
        ? `<div class="result-block"><div class="result-head">` +
          `<span class="result-title">Listing 草稿</span>` +
          `<a class="btn btn-sm" href="/listings?listing=${U.esc(state.listing.listing_id)}" data-link>打开工作室</a>` +
          `</div><div class="result-body">${R.renderListing(state.listing)}</div></div>`
        : "",
      qualityBlock(),
    ].filter(Boolean);
    if (!blocks.length) {
      return `<p class="t-sm t-muted" style="padding:var(--sp-4)">任务完成后，结果会显示在这里。</p>`;
    }
    return blocks.join("");
  }

  function resultRawPane() {
    const raw = {
      task_id: state.taskId,
      status: state.taskStatus,
      plan: state.plan,
      degraded: state.degraded,
      degraded_reason: state.degradedReason,
      task: state.taskRaw,
      steps: state.steps,
    };
    return `<pre class="raw-pre">${U.esc(JSON.stringify(raw, null, 2))}</pre>`;
  }

  function resultPane() {
    const running = AR.isRunning(state.taskStatus) || state.busy;
    const failed = state.taskStatus === "failed" || (state.error && !running);
    const cancelled = state.taskStatus === "cancelled";
    const tab = state.resTab;

    return (
      `<div class="wb-pane-head">` +
      `<div class="wb-pane-title"><span class="t-section">结果</span>` +
      (running ? `<span class="badge badge-running">${state.taskStatus === "queued" ? "排队中" : "运行中"}</span>`
        : cancelled ? `<span class="badge">已取消</span>`
        : failed ? `<span class="badge badge-danger">失败</span>`
        : state.taskId ? `<span class="badge badge-ok">已完成</span>` : "") +
      (state.degraded ? `<span class="badge badge-warn">降级</span>` : "") +
      `</div>` +
      `<div class="wb-run-actions">` +
      (running && state.taskId ? `<button type="button" class="btn btn-sm" id="wb-cancel">取消</button>` : "") +
      (state.taskId ? `<a class="btn btn-sm" href="/tasks/${U.esc(state.taskId)}" data-link>任务详情</a>` : "") +
      `</div></div>` +
      AR.resultTabs({ active: tab }) +
      `<div class="res-body"><div class="res-inner">` +
      (running ? `<div class="progress is-indeterminate"><div class="progress-bar"></div></div>` : "") +
      (state.degraded
        ? `<div class="callout callout-warn">${U.icon("alert")}<div><strong>已降级执行</strong><br>` +
          `${U.esc(state.degradedReason || "目标解析使用了规则；结果仍然完整，但文案可能需要人工润色。")}</div></div>`
        : "") +
      (tab === "steps"
        ? AR.stepList(state.steps, state.plan)
        : tab === "data"
          ? resultDataPane()
          : resultRawPane()) +
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
      `<div class="wb-run" id="wb-run">` +
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
      `<div class="row gap-2 mt-2 wrap">` +
      (state.report
        ? `<a class="btn btn-sm" href="/listings?report=${U.esc(state.report.report_id)}" data-link>` +
          `${U.icon("listing")}基于报告再生成 Listing</a>`
        : "") +
      `</div></div></div>` +
      `</section>` +

      `<aside class="wb-pane wb-pane-res" id="wb-res-pane">` +
      resultPane() +
      `</aside>` +
      `</div>`
    );
  }

  /* ================= 渲染与事件 ================= */
  function render(root) {
    const body = state.mode === "empty" ? renderEmpty()
      : state.mode === "params" ? renderParams()
      : renderRun();
    root.innerHTML = `<div class="view">${body}</div>`;
    window.CPIcon.hydrate(root);
    bind(root);
    loadConversations(root);
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
      state.conversations = data.items || [];
    }).catch(function () { /* 会话列表失败不影响主流程 */ });
  }

  function bindResultPane(root) {
    root.querySelectorAll("[data-res-tab]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.resTab = btn.getAttribute("data-res-tab");
        renderInPlace(root);
      });
    });
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

    root.onclick = function (event) {
      const tab = event.target.closest("[data-skills-tab]");
      if (tab) { state.skillsTab = tab.getAttribute("data-skills-tab"); render(root); return; }

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
        const skill = C.SKILLS.find(function (s) { return s.key === key; });
        if (!skill) return;
        if (skill.status !== "available") {
          U.toast("该技能仍在开发中，暂不可用", "danger");
          return;
        }
        state.skill = skill;
        state.goal = skill.prompt;
        state.mode = "params";
        state.resolveInfo = null;
        render(root);
        beginGoal(root, skill.prompt);
        return;
      }

      const act = event.target.closest("[data-act]");
      if (act) {
        const name = act.getAttribute("data-act");
        if (name === "back" || name === "new") {
          newSession(root);
        } else if (name === "attach") {
          U.toast("附件上传请到「数据资产」页面，导入后即可在此选用", "danger");
        } else if (name === "skills") {
          state.skillsTab = "skills";
          render(root);
        } else if (name === "demo") {
          fillDemo(root);
        }
        return;
      }

      if (event.target.closest("#wb-demo")) { fillDemo(root); return; }
      if (event.target.closest("#wb-run")) { runFlow(root); return; }
      if (event.target.closest("#wb-cancel")) { cancelRun(root); return; }
    };

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

    const input = root.querySelector("#composer-input");
    if (input) {
      input.addEventListener("input", function () {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 200) + "px";
        const send = root.querySelector("#composer-send");
        if (send) send.disabled = !input.value.trim();
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
  }

  async function beginGoal(root, goal) {
    state.goal = goal;
    state.error = "";
    state.mode = "params";
    render(root);
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
        state.error = "需要先配置 API Key 才能解析目标。请到「设置 → 模型与密钥」添加配置。";
        U.toast(state.error, "danger");
      } else {
        state.resolveInfo = { degraded: true, reason: err.message, spec: {} };
      }
    }
    if (state.mode === "params") render(root);
  }

  async function fillDemo(root) {
    try {
      const demo = await A.get("/api/demo/dataset");
      const req = demo.analysis_request || {};
      state.productName = req.product_name || state.productName || "EcoSip Insulated Water Bottle";
      state.competitorsJson = JSON.stringify(req.competitors || [], null, 2);
      if (!state.goal) state.goal = "分析示例竞品的价格与评论痛点，并生成一份英文 Listing";
      state.mode = "params";
      state.error = "";
      render(root);
      U.toast("已载入示例数据（虚构，仅用于体验流程）", "ok");
    } catch (err) {
      U.toast(err.message, "danger");
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
    if (compEl) state.competitorsJson = compEl.value;
    if (listingEl) state.withListing = listingEl.checked;
    if (marketEl) state.marketplace = marketEl.value;
    if (langEl) state.listingLanguage = langEl.value;
    state.error = "";

    if (!state.productName) { state.error = "请填写商品名称"; render(root); return; }
    let competitors;
    try {
      competitors = JSON.parse(state.competitorsJson || "[]");
      if (!Array.isArray(competitors) || !competitors.length) {
        throw new Error("至少需要 1 个竞品");
      }
    } catch (err) {
      state.error = "竞品数据解析失败：" + err.message;
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
      state.degraded = !!run.degraded;
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
        state.error = "需要先配置 API Key（BYOK）。请到「设置 → 模型与密钥」添加一个厂商配置后再运行。";
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

  function entry(root, params, query) {
    resetState();
    if (query && query.agent) state.agentKey = query.agent;
    render(root);
    if (query && query.conversation) openConversation(root, query.conversation);
  }

  window.CPPageWorkbench = { entry, render };
})();
