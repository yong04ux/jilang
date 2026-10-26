/* 激浪 · 设置（多厂商 LLM 配置 + 团队 + 审计 + 数据源）
 *
 * 关键约束：
 * - Key 只显示掩码；保存后立即生效；
 * - 固定 demo 账号禁止写入任何配置（后端 403，前端提前拦）；
 * - 自定义 base_url 必须显式勾选，否则只允许预置厂商域名（防 SSRF）。
 */
(function () {
  "use strict";
  const U = window.CPUi;
  const A = window.CPApi;

  const state = {
    providers: null,
    editing: null,      // { provider, label, base_url, model, config_id }
    busy: false,
    health: null,
    model: null,
    tenant: null,
    members: [],
    auditItems: [],
    auditRows: "",      // 审计日志表格行，弹窗复用
    sources: [],
    activeOnly: false,
    // 现场读取到的可用模型：{ providerKey: [model, ...] }
    liveModels: {},
  };

  /* 模型候选 = 现场读到的（优先） + 预置厂商的常用候选。
   * 预置清单只是给个起步示例，权威来源是厂商的模型列表接口。 */
  function modelCandidates(providerKey) {
    const preset = ((state.providers && state.providers.presets) || [])
      .find(function (p) { return p.key === providerKey; });
    const live = state.liveModels[providerKey] || [];
    const common = (preset && preset.common_models) || [];
    const seen = {};
    return live.concat(common).filter(function (name) {
      if (!name || seen[name]) return false;
      seen[name] = true;
      return true;
    });
  }

  function modelOptionsHtml(providerKey) {
    return modelCandidates(providerKey).map(function (name) {
      return `<option value="${U.esc(name)}"></option>`;
    }).join("");
  }

  function engineLabel(name) {
    if (!name) return "未配置";
    return name === "rule" ? "规则生成" : "AI 模型";
  }

  /* 顶栏那块「厂商 · 模型」状态由 shell 持有，保存/激活/测试/删除后必须让它重读，
   * 否则顶栏一直停在切换前的那套配置上（测过了还显示上一个模型名、甚至「未验证」）。 */
  function refreshShell() {
    if (window.CPShell && window.CPShell.loadProvider) window.CPShell.loadProvider();
  }

  function canManage(tenant) {
    return tenant && (tenant.role === "admin" || tenant.role === "owner");
  }

  /* 审计记录用中文动作名展示；未收录的动作按模块归类，不暴露内部动作代码 */
  const AUDIT_LABEL = {
    "auth.login": "登录",
    "auth.logout": "退出登录",
    "auth.register": "注册账号",
    "auth.demo": "创建临时账号",
    "auth.password_change": "修改密码",
    "model.provider_save": "保存模型配置",
    "model.provider_activate": "切换当前模型",
    "model.provider_test": "测试模型连接",
    "model.provider_delete": "删除模型配置",
    "model.update": "更新模型设置",
    "model.reset": "重置模型设置",
    "store.create": "添加店铺",
    "store.sync": "同步店铺",
    "store.disconnect": "断开店铺",
    "listing.generate": "生成 Listing",
    "listing.recheck": "复检 Listing",
    "listing.export": "导出 Listing",
    "listing.version_create": "保存 Listing 版本",
    "approval.request": "提交发布申请",
    "approval.decide": "审批发布申请",
    "invite.create": "生成邀请",
    "invite.accepted": "接受邀请",
    "invite.deleted": "撤销邀请",
    "task.cancel": "取消任务",
    "task.retry": "重试任务",
    "task.run": "执行任务",
    "report.export": "导出报告",
  };

  const AUDIT_PREFIX = {
    auth: "账号操作",
    model: "模型配置变更",
    store: "店铺操作",
    listing: "Listing 操作",
    approval: "审批操作",
    invite: "成员邀请",
    task: "任务操作",
    report: "报告操作",
  };

  const TARGET_LABEL = {
    user: "成员",
    provider_config: "模型配置",
    store_connection: "店铺",
    listing: "Listing",
    report: "报告",
    task: "任务",
    invite: "邀请",
    approval: "审批",
  };

  function auditLabel(action) {
    const key = String(action || "");
    if (AUDIT_LABEL[key]) return AUDIT_LABEL[key];
    const prefix = key.split(".")[0];
    return AUDIT_PREFIX[prefix] || "操作记录";
  }

  function auditTarget(item) {
    return TARGET_LABEL[item.target_type] || "—";
  }

  /* ---------------- 模型与密钥 ---------------- */
  function providerForm() {
    const providers = (state.providers && state.providers.presets) || [];
    const editing = state.editing || {};
    const customSelected = editing.provider === "custom";

    const options = providers.map(function (p) {
      return `<option value="${U.esc(p.key)}"${p.key === (editing.provider || "deepseek") ? " selected" : ""}>` +
        `${U.esc(p.label)}</option>`;
    }).join("");

    return (
      `<form id="prov-form" class="card card-pad" style="margin-top:var(--sp-4)">` +
      `<div class="row between"><div><div class="card-title">${editing.config_id ? "编辑配置" : "新增配置"}</div>` +
      `<div class="card-sub">不同厂商用接口地址与模型名区分；Anthropic、Google 走各自官方协议，已自动适配</div></div>` +
      `<button type="button" class="btn-icon" id="prov-cancel" aria-label="取消">${U.icon("close")}</button></div>` +

      `<div class="grid-2 mt-4">` +
      `<label class="field"><span class="field-label">厂商 <span class="t-danger">*</span></span>` +
      `<select name="provider" id="prov-provider">${options}</select></label>` +
      `<label class="field"><span class="field-label">配置标签</span>` +
      `<input name="label" value="${U.esc(editing.label || "默认")}" placeholder="例如 主 Key / 备用" /></label>` +
      `</div>` +

      `<label class="field mt-3"><span class="field-label">API Key ${editing.config_id ? "" : '<span class="t-danger">*</span>'}</span>` +
      `<input name="api_key" type="password" autocomplete="off" ` +
      `placeholder="${editing.config_id ? "留空表示不修改" : "sk-..."}" />` +
      `<span class="field-help">加密保存；保存后只显示末四位。生成时只用于调用模型，不会出现在结果里。</span></label>` +

      `<label class="field mt-3"><span class="field-label">接口地址</span>` +
      `<input name="base_url" value="${U.esc(editing.base_url || "")}" placeholder="留空使用厂商默认地址" />` +
      `<span class="field-help" id="prov-url-hint">预置厂商只允许其官方域名；其他地址需选择「自定义」并勾选下方确认。</span></label>` +

      `<label class="row gap-2 mt-3" style="cursor:pointer" id="prov-custom-row">` +
      `<input type="checkbox" name="allow_custom" ${customSelected ? "" : "disabled"} />` +
      `<span class="t-sm">我确认使用自定义接口地址（仅限 OpenAI 兼容服务，不能指向内网）</span></label>` +

      `<div class="field mt-3"><span class="field-label">模型 <span class="t-danger">*</span></span>` +
      `<div class="row gap-2">` +
      `<input name="model" class="grow" list="prov-model-options" autocomplete="off" ` +
      `value="${U.esc(editing.model || "")}" placeholder="从列表里选，或直接填写模型名" />` +
      `<button type="button" class="btn btn-sm" id="prov-fetch-models">读取可用模型</button>` +
      `</div>` +
      `<datalist id="prov-model-options">${modelOptionsHtml(editing.provider || "deepseek")}</datalist>` +
      `<span class="field-help" id="prov-model-hint">列表是常用候选；点「读取可用模型」可以拉取你这个账号真正能用的模型名。</span>` +
      `</div>` +

      `<p class="callout callout-danger mt-3" id="prov-error" hidden></p>` +
      `<div class="row gap-2 mt-4">` +
      `<button type="submit" class="btn btn-primary">${state.busy ? "保存中…" : "保存配置"}</button>` +
      `<button type="button" class="btn btn-quiet" id="prov-cancel-2">取消</button>` +
      `</div></form>`
    );
  }

  /* 哪些厂商需要显示接口地址：预置厂商的地址是固定的，写出来只是噪音 */
  const SHOW_BASE_URL = ["custom", "ollama"];

  function providerList() {
    const items = (state.providers && state.providers.items) || [];
    if (!items.length) {
      return `<div class="empty" style="padding:var(--sp-5)">` +
        `<span class="empty-icon">${U.icon("settings")}</span>` +
        `<p class="empty-title">还没有配置</p>` +
        `<p class="empty-desc">激浪不提供模型额度。添加一个你自己的模型配置并设为当前使用后，才能运行生成类任务。</p></div>`;
    }
    return items.map(function (c) {
      const active = c.is_active;
      return (
        `<div class="cfg-row">` +
        `<div class="cfg-main">` +
        `<div class="cfg-title">${U.esc(c.label)}` +
        `<span class="badge">${U.esc(c.provider)}</span>` +
        (active ? `<span class="badge badge-brand">当前使用</span>` : "") +
        (!c.enabled ? `<span class="badge">已禁用</span>` : "") +
        (c.last_test_ok === true ? `<span class="badge badge-ok">测试通过</span>`
          : c.last_test_ok === false ? `<span class="badge badge-danger">测试失败</span>` : "") +
        `</div>` +
        // 副文本只留「用得上的」：模型名、Key 末四位、最近一次测试时间。
        // 预置厂商的接口地址是固定的，重复显示只是噪音；只有自定义地址
        // 和本地 Ollama 才需要看到实际地址。测试成功与否看上面的徽章，
        // 不再把「模型 xxx 响应正常（tokens=210）」这种过程信息摊在这里。
        `<div class="cfg-sub">${U.esc(c.model || "—")}` +
        (SHOW_BASE_URL.indexOf(c.provider) >= 0 ? ` · ${U.esc(c.base_url || "—")}` : "") +
        `<br>Key：${c.has_api_key ? U.esc(c.api_key_masked || "已保存") : "未保存"}` +
        (c.last_tested_at ? ` · 最近测试 ${U.esc(U.fmtTime(c.last_tested_at))}` : "") +
        (c.last_test_ok === false && c.last_test_detail
          ? `<br><span class="t-danger">${U.esc(c.last_test_detail)}</span>`
          : "") +
        `</div></div>` +
        `<div class="cfg-actions">` +
        `<button type="button" class="btn btn-sm" data-test="${U.esc(c.config_id)}">测试</button>` +
        (active
          ? `<button type="button" class="btn btn-sm" disabled>已激活</button>`
          : `<button type="button" class="btn btn-sm btn-primary" data-activate="${U.esc(c.config_id)}">设为当前</button>`) +
        `<button type="button" class="btn btn-sm btn-quiet" data-edit="${U.esc(c.config_id)}">编辑</button>` +
        `<button type="button" class="btn btn-sm btn-danger" data-delete="${U.esc(c.config_id)}">删除</button>` +
        `</div></div>`
      );
    }).join("");
  }

  /* ---------------- 数据源 ---------------- */
  function sourceRows() {
    const items = state.sources || [];
    if (!items.length) {
      return `<p class="t-sm t-muted">暂时读不到数据来源信息。</p>`;
    }
    return items.map(function (s) {
      let badge;
      if (s.mode === "upload") badge = `<span class="badge">你的文件</span>`;
      else if (s.configured && s.mode === "live") badge = `<span class="badge badge-ok">已连接</span>`;
      else if (s.configured) badge = `<span class="badge">示例数据</span>`;
      else badge = `<span class="badge">未设置</span>`;
      return (
        `<div class="src-row"><span class="grow">` +
        `<span class="src-name">${U.esc(s.label)}</span>` +
        `<span class="src-desc">${U.esc(s.detail)}` +
        (s.last_sync_at ? ` · 最后同步 ${U.esc(U.fmtTime(s.last_sync_at))}` : "") +
        `</span></span>` +
        `<span class="src-flags">${badge}</span>` +
        `</div>`
      );
    }).join("");
  }

  /* ---------------- 页面 ---------------- */
  async function render(root, params, query) {
    state.editing = null;
    state.liveModels = {};
    closeAuditModal();
    root.innerHTML = `<div class="view"><div class="page"><div class="page-inner">` +
      `<div class="page-head"><div><h1 class="page-title">设置</h1>` +
      `<p class="page-desc">账号、模型密钥、团队成员与数据来源。</p></div>` +
      `</div><div class="skeleton skeleton-line" style="height:180px"></div></div></div></div>`;

    await loadAll();
    paint(root);
    if (query && query.section) {
      const target = root.querySelector(`#section-${query.section}`);
      if (target) target.scrollIntoView({ block: "start" });
    }
  }

  async function loadAll() {
    const jobs = [
      A.get("/api/settings/providers").then(function (d) { state.providers = d; }).catch(function () { state.providers = { items: [], presets: [] }; }),
      A.get("/api/health").then(function (d) { state.health = d; }).catch(function () { }),
      A.get("/api/settings/model").then(function (d) { state.model = d; }).catch(function () { }),
      A.get("/api/tenants/current").then(function (d) { state.tenant = d; }).catch(function () { }),
      A.get("/api/tenants/members").then(function (d) { state.members = d.items || []; }).catch(function () { }),
      A.get("/api/marketplace/sources").then(function (d) { state.sources = d.items || []; }).catch(function () { }),
    ];
    await Promise.all(jobs);
    if (canManage(state.tenant)) {
      try { state.auditItems = (await A.get("/api/audit?limit=20")).items || []; } catch (err) { /* 忽略 */ }
    }
  }

  function paint(root) {
    const user = window.CPAuth.user || {};
    const provider = (state.health && state.health.provider) || {};
    const isDemo = (user.username || "").toLowerCase() === "demo";
    const manage = canManage(state.tenant);

    const memberRows = state.members.map(function (m) {
      return `<tr><td>${U.esc(m.display_name || m.username)}</td>` +
        `<td>${U.esc(m.role)}</td>` +
        `<td class="t-muted">${U.esc(U.fmtTime(m.joined_at))}</td></tr>`;
    }).join("");

    // 操作者优先显示成员名；匹配不到就不显示 ID
    const memberName = {};
    state.members.forEach(function (m) {
      memberName[m.user_id] = m.display_name || m.username;
    });

    /* 行内容在这里渲染（要用到成员名映射），表格本身收在弹窗里 */
    state.auditRows = state.auditItems.map(function (item) {
      return `<tr><td>${U.esc(auditLabel(item.action))}</td>` +
        `<td class="t-xs">${U.esc(memberName[item.actor_id] || "—")}</td>` +
        `<td class="t-xs t-muted">${U.esc(auditTarget(item))}</td>` +
        `<td class="t-muted t-xs">${U.esc(U.fmtTime(item.created_at))}</td></tr>`;
    }).join("");

    root.innerHTML = `<div class="view"><div class="page"><div class="page-inner">` +
      `<div class="page-head"><div><h1 class="page-title">设置</h1>` +
      `<p class="page-desc">账号、模型密钥、团队成员与数据来源。</p></div>` +
      `</div>` +

      `<div class="settings-grid">` +

      // ---- 账号 ----
      `<div class="card" id="section-account"><div class="card-head"><div><div class="card-title">账号</div>` +
      `<div class="card-sub">当前登录身份</div></div></div><div class="card-body">` +
      `<div class="kv"><span class="kv-k">用户名</span><span class="kv-v">${U.esc(user.username || "—")}</span></div>` +
      `<div class="kv"><span class="kv-k">显示名</span><span class="kv-v">${U.esc(user.display_name || "—")}</span></div>` +
      `<div class="kv"><span class="kv-k">管理员</span><span class="kv-v">${user.is_admin ? "是" : "否"}</span></div>` +
      `<div class="kv"><span class="kv-k">账号类型</span><span class="kv-v">` +
      `${isDemo ? '<span class="badge badge-warn">共享体验账号</span>'
        : user.is_guest ? `<span class="badge badge-warn">临时账号（${U.esc(U.fmtTime(user.guest_expires_at))} 过期）</span>`
        : '<span class="badge">普通账号</span>'}</span></div>` +
      `<div class="row gap-2 mt-4"><button type="button" class="btn btn-sm" id="btn-logout">退出登录</button></div>` +
      `</div></div>` +

      // ---- 模型与密钥 ----
      `<div class="card" id="section-model"><div class="card-head"><div>` +
      `<div class="card-title">模型与密钥</div>` +
      `<div class="card-sub">平台不提供模型额度：每个账号使用自己的 API Key</div></div>` +
      `<button type="button" class="btn btn-primary btn-sm" id="prov-new" ${isDemo ? "disabled" : ""}>` +
      `${U.icon("plus")}新增配置</button></div><div class="card-body">` +

      (isDemo
        ? `<div class="callout callout-warn">${U.icon("alert")}<div>` +
          `<strong>共享体验账号不能保存 API Key</strong>：它由所有人共用。` +
          `请使用「一键体验」创建自己的临时账号后再配置。` +
          `<div class="mt-2"><a class="btn btn-sm" href="/logout" data-link id="goto-guest" hidden></a></div>` +
          `</div></div>`
        : "") +

      `<div class="row between wrap gap-2 mb-2"><span class="t-sm t-bold">已保存的配置</span>` +
      `<span class="t-xs t-muted">当前生效：${U.esc(engineLabel(provider.name))}` +
      (provider.model ? ` · ${U.esc(provider.model)}` : "") + `</span></div>` +
      providerList() +
      (state.editing !== null ? providerForm() : "") +
      `<div class="callout callout-info mt-4">${U.icon("info")}` +
      `<span>支持 OpenAI 兼容接口：DeepSeek、OpenAI、Moonshot、智谱、通义、硅基流动、OpenRouter、Ollama，也可以填自定义地址；另有 Anthropic Claude 与 Google Gemini。</span></div>` +
      `</div></div>` +

      // ---- 数据源 ----
      `<div class="card" id="section-data"><div class="card-head"><div>` +
      `<div class="card-title">数据源</div>` +
      `<div class="card-sub">每个数据域现在用的是哪一份数据、上次什么时候同步</div></div></div>` +
      `<div class="card-body">` +
      sourceRows() +
      `<div class="row gap-2 mt-4"><a class="btn btn-sm" href="/stores" data-link>管理店铺与渠道</a></div>` +
      `</div></div>` +

      // ---- 团队 ----
      `<div class="card" id="section-team"><div class="card-head"><div>` +
      `<div class="card-title">团队与角色</div>` +
      `<div class="card-sub">${state.tenant
        ? `${U.esc(state.tenant.name)} · 我的角色 ${U.esc(state.tenant.role)}`
        : "租户信息不可用"}</div></div></div>` +
      `<div class="card-body">` +
      `<div class="table-wrap"><table class="table"><thead><tr>` +
      `<th>成员</th><th>角色</th><th>加入时间</th></tr></thead><tbody>` +
      (memberRows || '<tr><td colspan="3" class="t-muted">暂无成员</td></tr>') +
      `</tbody></table></div>` +
      (manage
        ? `<div class="row gap-2 mt-4 wrap">` +
          `<select id="invite-role" style="max-width:200px">` +
          `<option value="editor">editor（可执行任务）</option>` +
          `<option value="viewer">viewer（只读）</option>` +
          `<option value="admin">admin（可管理成员）</option>` +
          `</select>` +
          `<button type="button" class="btn btn-sm" id="btn-invite">生成邀请令牌</button>` +
          `</div>` +
          `<div class="callout callout-info mt-3">${U.icon("info")}` +
          `<span>邀请链接只显示一次，复制后发给同事即可。</span></div>` +
          `<div id="invite-result" class="mt-3"></div>`
        : `<div class="callout callout-info mt-3">${U.icon("info")}` +
          `<span>只有 admin / owner 可以邀请成员与查看审计日志。</span></div>`) +
      `</div></div>` +

      // ---- 审计 ----
      (manage
        ? `<div class="card card-pad" id="section-audit"><div class="row between gap-2">` +
          `<div><div class="card-title">审计日志</div>` +
          `<div class="card-sub">记录谁在什么时候改了什么，写入后不可修改</div></div>` +
          `<button type="button" class="btn btn-sm" id="btn-audit">查看</button>` +
          `</div></div>`
        : "") +

      `</div></div></div></div>`;

    window.CPIcon.hydrate(root);
    bind(root);
  }

  /* ---------------- 审计日志弹窗 ----------------
   * 表格一共 20 行、四列，摊在设置页上会把半个页面占满，日常又不需要常看，
   * 所以默认收起，点「查看」再浮上来。 */
  function openAuditModal() {
    closeAuditModal();
    const rows = state.auditRows || "";
    const modal = document.createElement("div");
    modal.className = "modal";
    modal.id = "audit-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "audit-modal-title");
    modal.innerHTML =
      `<div class="modal-card is-wide">` +
      `<div class="modal-head"><div>` +
      `<div class="card-title" id="audit-modal-title">审计日志</div>` +
      `<div class="card-sub">最近 20 条；记录写入后不可修改</div></div>` +
      `<button type="button" class="btn-icon" data-audit-close aria-label="关闭">${U.icon("close")}</button>` +
      `</div>` +
      `<div class="modal-body"><div class="table-wrap">` +
      `<table class="table"><thead><tr>` +
      `<th>动作</th><th>操作者</th><th>对象</th><th>时间</th></tr></thead><tbody>` +
      (rows || '<tr><td colspan="4" class="t-muted">暂无记录</td></tr>') +
      `</tbody></table></div></div>` +
      `<div class="modal-foot"><button type="button" class="btn btn-quiet" data-audit-close>关闭</button></div>` +
      `</div>`;
    document.body.appendChild(modal);
    window.CPIcon.hydrate(modal);
    modal.addEventListener("click", function (event) {
      if (event.target === modal || event.target.closest("[data-audit-close]")) {
        closeAuditModal();
      }
    });
    document.addEventListener("keydown", onAuditKeydown);
    const first = modal.querySelector("[data-audit-close]");
    if (first) first.focus();
  }

  function closeAuditModal() {
    const modal = document.getElementById("audit-modal");
    if (modal) modal.remove();
    document.removeEventListener("keydown", onAuditKeydown);
  }

  function onAuditKeydown(event) {
    if (event.key === "Escape") closeAuditModal();
  }

  function selectPreset(root, providerKey) {
    const preset = ((state.providers && state.providers.presets) || [])
      .find(function (p) { return p.key === providerKey; });
    const baseInput = root.querySelector('#prov-form [name="base_url"]');
    const modelInput = root.querySelector('#prov-form [name="model"]');
    const customRow = root.querySelector('#prov-custom-row input');
    const modelList = root.querySelector("#prov-model-options");
    if (preset) {
      if (baseInput && !baseInput.value) baseInput.value = preset.base_url || "";
      if (modelInput && !modelInput.value) modelInput.value = preset.default_model || "";
    }
    if (modelList) modelList.innerHTML = modelOptionsHtml(providerKey);
    const isCustom = providerKey === "custom";
    if (customRow) {
      customRow.disabled = !isCustom;
      if (!isCustom) customRow.checked = false;
    }
  }

  function bind(root) {
    const logout = root.querySelector("#btn-logout");
    if (logout) logout.addEventListener("click", function () { window.CPAuth.logout(); });

    const add = root.querySelector("#prov-new");
    if (add) {
      add.addEventListener("click", function () {
        state.editing = { provider: "deepseek", label: "默认", base_url: "", model: "" };
        paint(root);
        selectPreset(root, "deepseek");
      });
    }

    const providerSelect = root.querySelector("#prov-provider");
    if (providerSelect) {
      providerSelect.addEventListener("change", function () {
        if (state.editing) {
          state.editing.provider = providerSelect.value;
          const baseInput = root.querySelector('#prov-form [name="base_url"]');
          const modelInput = root.querySelector('#prov-form [name="model"]');
          if (baseInput) baseInput.value = "";
          if (modelInput) modelInput.value = "";
        }
        selectPreset(root, providerSelect.value);
      });
    }

    // 读取该账号真正可用的模型清单：模型名各家常改，问服务端比抄文档可靠
    const fetchModels = root.querySelector("#prov-fetch-models");
    if (fetchModels) {
      fetchModels.addEventListener("click", async function () {
        const form = root.querySelector("#prov-form");
        if (!form) return;
        const providerKey = form.provider.value;
        const hint = root.querySelector("#prov-model-hint");
        const original = fetchModels.textContent;
        fetchModels.disabled = true;
        fetchModels.textContent = "读取中…";
        try {
          const data = await A.post("/api/settings/providers/models", {
            provider: providerKey,
            base_url: form.base_url.value.trim() || null,
            api_key: form.api_key.value.trim() || null,
            allow_custom_base_url: Boolean(form.allow_custom && form.allow_custom.checked),
            config_id: (state.editing && state.editing.config_id) || null,
          });
          const items = (data && data.items) || [];
          state.liveModels[providerKey] = items;
          const list = root.querySelector("#prov-model-options");
          if (list) list.innerHTML = modelOptionsHtml(providerKey);
          if (items.length && !form.model.value) form.model.value = items[0];
          if (hint) {
            hint.textContent = items.length
              ? `共 ${items.length} 个可用模型，点模型输入框即可下拉选择。`
              : (data.hint || "这个接口没有返回模型清单，可以手动填写厂商文档里的模型名。");
          }
          U.toast(items.length ? `读到 ${items.length} 个可用模型` : "没有读到模型清单", items.length ? "ok" : "danger");
        } catch (err) {
          if (hint) hint.textContent = err.message;
          U.toast(err.message, "danger");
        } finally {
          fetchModels.disabled = false;
          fetchModels.textContent = original;
        }
      });
    }

    ["prov-cancel", "prov-cancel-2"].forEach(function (id) {
      const btn = root.querySelector("#" + id);
      if (btn) {
        btn.addEventListener("click", function () {
          state.editing = null;
          paint(root);
        });
      }
    });

    const form = root.querySelector("#prov-form");
    if (form) {
      form.addEventListener("submit", async function (event) {
        event.preventDefault();
        const error = root.querySelector("#prov-error");
        if (error) error.hidden = true;
        const payload = {
          provider: form.provider.value,
          label: (form.label.value || "默认").trim(),
          base_url: form.base_url.value.trim() || null,
          model: form.model.value.trim() || null,
          api_key: form.api_key.value.trim() || null,
          allow_custom_base_url: Boolean(form.allow_custom && form.allow_custom.checked),
        };
        if (state.editing && state.editing.config_id) payload.config_id = state.editing.config_id;
        if (!payload.api_key && !(state.editing && state.editing.config_id)) delete payload.api_key;
        state.busy = true;
        try {
          const saved = await A.post("/api/settings/providers", payload);
          const cfg = (saved && saved.config) || {};
          U.toast(
            cfg.is_active
              // 首套配置后端会自动激活，这里说清楚，访客不用再找「设为当前」
              ? "已保存并设为当前使用；可点「测试」验证连通性"
              : "配置已保存，可点「测试」验证，或「设为当前」切换",
            "ok"
          );
          state.editing = null;
          state.providers = await A.get("/api/settings/providers");
          try { state.health = await A.get("/api/health"); } catch (err) { /* 忽略 */ }
          paint(root);
          refreshShell();
        } catch (err) {
          state.busy = false;
          if (error) { error.hidden = false; error.textContent = err.message; }
          else U.toast(err.message, "danger");
        }
      });
    }

    root.querySelectorAll("[data-activate]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        try {
          await A.post(`/api/settings/providers/${encodeURIComponent(btn.getAttribute("data-activate"))}/activate`, {});
          U.toast("已切换当前使用的配置", "ok");
          state.providers = await A.get("/api/settings/providers");
          try { state.health = await A.get("/api/health"); } catch (err) { /* 忽略 */ }
          paint(root);
          refreshShell();
        } catch (err) {
          U.toast(err.message, "danger");
          btn.disabled = false;
        }
      });
    });

    root.querySelectorAll("[data-test]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        const original = btn.textContent;
        btn.textContent = "测试中…";
        try {
          const result = await A.post(`/api/settings/providers/${encodeURIComponent(btn.getAttribute("data-test"))}/test`, {});
          U.toast(result.ok ? `连通正常（${result.elapsed_ms || 0} ms）` : `失败：${result.detail}`, result.ok ? "ok" : "danger");
          state.providers = await A.get("/api/settings/providers");
          try { state.health = await A.get("/api/health"); } catch (err) { /* 忽略 */ }
          paint(root);
          refreshShell();
        } catch (err) {
          U.toast(err.message, "danger");
          btn.disabled = false;
          btn.textContent = original;
        }
      });
    });

    root.querySelectorAll("[data-delete]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const id = btn.getAttribute("data-delete");
        if (!window.confirm("删除这套配置？已保存的 Key 会一并删除，且不可恢复。")) return;
        btn.disabled = true;
        try {
          await A.del(`/api/settings/providers/${encodeURIComponent(id)}`);
          U.toast("配置已删除", "ok");
          state.providers = await A.get("/api/settings/providers");
          try { state.health = await A.get("/api/health"); } catch (err) { /* 忽略 */ }
          paint(root);
          refreshShell();
        } catch (err) {
          U.toast(err.message, "danger");
          btn.disabled = false;
        }
      });
    });

    root.querySelectorAll("[data-edit]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const id = btn.getAttribute("data-edit");
        const item = ((state.providers && state.providers.items) || []).find(function (c) {
          return c.config_id === id;
        });
        if (!item) return;
        state.editing = {
          config_id: item.config_id,
          provider: item.provider,
          label: item.label,
          base_url: item.base_url,
          model: item.model,
        };
        paint(root);
        selectPreset(root, item.provider);
        const baseInput = root.querySelector('#prov-form [name="base_url"]');
        if (baseInput) baseInput.value = item.base_url || "";
        const modelInput = root.querySelector('#prov-form [name="model"]');
        if (modelInput) modelInput.value = item.model || "";
      });
    });

    const auditBtn = root.querySelector("#btn-audit");
    if (auditBtn) auditBtn.addEventListener("click", openAuditModal);

    const invite = root.querySelector("#btn-invite");
    if (invite) {
      invite.addEventListener("click", async function () {
        invite.disabled = true;
        try {
          const role = root.querySelector("#invite-role").value;
          const data = await A.post("/api/tenants/invites", { role: role });
          const box = root.querySelector("#invite-result");
          box.innerHTML = `<div class="callout callout-info">${U.icon("info")}<div>` +
            `<strong>邀请令牌（只显示一次）</strong>` +
            `<div class="t-mono mt-2" style="word-break:break-all">${U.esc(data.token)}</div>` +
            `<div class="t-xs t-muted mt-2">角色：${U.esc(data.invite.role)} · 过期：${U.esc(U.fmtTime(data.invite.expires_at))}</div>` +
            `<button type="button" class="btn btn-sm mt-2" id="invite-copy">复制令牌</button>` +
            `</div></div>`;
          window.CPIcon.hydrate(box);
          const copy = box.querySelector("#invite-copy");
          if (copy) copy.addEventListener("click", function () { U.copy(data.token, "邀请令牌"); });
        } catch (err) {
          U.toast(err.message, "danger");
        } finally {
          invite.disabled = false;
        }
      });
    }
  }

  window.CPPageSettings = { render };
})();
