/* 激浪 · 登录门
 * 复用 /api/auth/* 接口与 HttpOnly Cookie 会话。
 * 未登录时不渲染业务页面，避免出现"点了没反应"的假界面。
 *
 * 演示站策略：
 * - 固定 demo 账号提示（账号名固定，密码由部署方决定，不在前端硬编码）；
 * - 「一键体验」调用 POST /api/auth/demo 创建 24h 临时账号；
 * - 开放注册关闭后不再显示注册入口。
 */
(function () {
  "use strict";
  const U = window.CPUi;

  let currentUser = null;
  let mode = "login"; // login | register | setup
  let allowRegister = false;
  let demoAccount = false;   // 部署方是否配置了固定 demo 账号
  let guestTtl = 24;         // 临时账号有效期（小时），来自服务端

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    (children || []).forEach(function (c) {
      node.append(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function gate() {
    let node = document.getElementById("auth-gate");
    if (!node) {
      node = el("div", { id: "auth-gate", class: "auth-gate", hidden: "" });
      document.body.appendChild(node);
    }
    return node;
  }

  function hide() {
    const node = gate();
    node.hidden = true;
    node.innerHTML = "";
  }

  function pitch() {
    return (
      `<div class="auth-pitch">` +
      `<div class="auth-pitch-brand">` +
      `<img src="/media/logo-mark.svg?v=2" alt="" />` +
      `<div><div class="auth-pitch-name">激浪</div>` +
      `<div class="auth-pitch-tag">跨境电商 AI 运营助手</div></div></div>` +
      `<h2 class="auth-pitch-title">把一个业务目标，变成可复核的执行结果</h2>` +
      `<p class="auth-pitch-desc">竞品分析、Listing 撰写、数据导入与人工审批在同一条可追溯的流水线上完成。` +
      `每一步都有真实状态与证据引用，结果不会替你编造销量或排名。</p>` +
      `<div class="auth-points">` +
      `<div class="auth-point">${U.icon("check")}<span>竞品分析：价格分布、评论痛点、差异化机会，附原文证据</span></div>` +
      `<div class="auth-point">${U.icon("check")}<span>Listing 生成：基于已确认事实，自动做事实对齐质检</span></div>` +
      `<div class="auth-point">${U.icon("check")}<span>数据导入：预览 → 字段映射 → 提交 → 错误 CSV</span></div>` +
      `<div class="auth-point">${U.icon("check")}<span>自带 API Key（BYOK）：平台不提供、也不接触你的 Key</span></div>` +
      `</div>` +
      `<p class="t-xs t-faint">演示站：平台数据为模拟数据源，全部带「示例」或「Mock」标记；真实平台接口未接入。</p>` +
      `</div>`
    );
  }

  function show(errorText) {
    const node = gate();
    node.hidden = false;
    const isRegister = mode !== "login";
    const title = mode === "setup" ? "创建管理员账号" : mode === "register" ? "注册新账号" : "登录激浪";
    const hint = mode === "setup"
      ? "首次使用：第一个注册的账号会成为管理员。密码经加盐哈希后保存在数据库。"
      : "登录后可运行任务、保存报告与草稿。会话凭据由 HttpOnly Cookie 承载。";

    node.innerHTML =
      `<div class="auth-shell">` +
      pitch() +
      `<div class="auth-card card">` +
      `<div class="auth-brand">` +
      `<img src="/media/logo-mark.svg?v=2" alt="" />` +
      `<span class="auth-brand-text">激浪</span>` +
      `</div>` +
      `<h1 class="t-title">${U.esc(title)}</h1>` +
      `<p class="t-sm t-muted mt-1">${U.esc(hint)}</p>` +
      `<form id="auth-form" autocomplete="on">` +
      `<label class="field"><span class="field-label">用户名</span>` +
      `<input name="username" required minlength="3" maxlength="32" placeholder="至少 3 个字符" autocomplete="username" /></label>` +
      `<label class="field"><span class="field-label">密码</span>` +
      `<input name="password" type="password" required minlength="8" placeholder="至少 8 位" ` +
      `autocomplete="${isRegister ? "new-password" : "current-password"}" /></label>` +
      (isRegister
        ? `<label class="field"><span class="field-label">确认密码</span>` +
          `<input name="confirm" type="password" required minlength="8" autocomplete="new-password" /></label>`
        : "") +
      `<p class="callout callout-danger" id="auth-error" hidden></p>` +
      `<button type="submit" class="btn btn-primary btn-lg">${mode === "login" ? "登录" : "注册并登录"}</button>` +
      (isRegister
        ? `<button type="button" class="btn btn-quiet" id="auth-switch">返回登录</button>`
        : "") +
      `</form>` +

      `<div class="auth-divider">或</div>` +
      `<button type="button" class="btn btn-lg" id="auth-demo" style="width:100%">` +
      `${U.icon("sparkles")}一键体验（${guestTtl} 小时临时账号）</button>` +
      `<div class="auth-demo-hint">` +
      `临时账号有独立空间，可以保存自己的 API Key，${guestTtl} 小时后自动清理。` +
      // 没配密码时后端不会创建固定账号，这里就不能提示，否则访客会去找一个不存在的账号
      (demoAccount
        ? `<br>固定演示账号：<code>demo</code>（密码由部署方设置；该账号只读示例数据、不能保存 Key）。`
        : "") +
      `</div>` +

      (allowRegister && !isRegister
        ? `<div class="row center mt-4"><button type="button" class="btn-link" id="auth-switch">注册新账号</button></div>`
        : "") +

      `<p class="t-xs t-faint auth-foot">密钥与密码不会写入日志，也不会进入模型上下文。</p>` +
      `</div></div>`;

    window.CPIcon.hydrate(node);

    const form = node.querySelector("#auth-form");
    const error = node.querySelector("#auth-error");
    if (errorText) { error.hidden = false; error.textContent = errorText; }

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      error.hidden = true;
      const username = form.username.value.trim();
      const password = form.password.value;
      if (isRegister && password !== form.confirm.value) {
        error.hidden = false;
        error.textContent = "两次输入的密码不一致";
        return;
      }
      const submit = form.querySelector("button[type=submit]");
      submit.disabled = true;
      submit.textContent = "处理中…";
      try {
        await window.CPApi.post(mode === "login" ? "/api/auth/login" : "/api/auth/register", {
          username, password,
        });
        await load(true);
        window.dispatchEvent(new CustomEvent("cp:authenticated"));
      } catch (err) {
        error.hidden = false;
        error.textContent = err.message || "操作失败";
      } finally {
        submit.disabled = false;
        submit.textContent = mode === "login" ? "登录" : "注册并登录";
      }
    });

    node.querySelectorAll("#auth-switch").forEach(function (sw) {
      sw.addEventListener("click", function () {
        mode = mode === "login" ? "register" : "login";
        show();
      });
    });

    const demo = node.querySelector("#auth-demo");
    if (demo) {
      demo.addEventListener("click", async function () {
        demo.disabled = true;
        const original = demo.innerHTML;
        demo.textContent = "正在创建临时账号…";
        try {
          const data = await window.CPApi.post("/api/auth/demo", {});
          await load(true);
          window.dispatchEvent(new CustomEvent("cp:authenticated"));
          const hours = data && data.expires_in_hours ? data.expires_in_hours : 24;
          U.toast(`临时账号已创建，${hours} 小时后自动清理`, "ok");
        } catch (err) {
          demo.disabled = false;
          demo.innerHTML = original;
          window.CPIcon.hydrate(demo);
          error.hidden = false;
          error.textContent = err.message || "一键体验不可用";
        }
      });
    }

    const first = node.querySelector("input");
    if (first) first.focus();
  }

  async function load(silent) {
    let status;
    try {
      status = await window.CPApi.get("/api/auth/status");
    } catch (err) {
      if (!silent) show(err.message);
      return null;
    }
    allowRegister = Boolean(status.allow_registration);
    demoAccount = Boolean(status.demo_account);
    guestTtl = Number(status.guest_ttl_hours) || 24;
    currentUser = status.authenticated ? status.user : null;
    if (!currentUser) {
      mode = status.needs_setup ? "setup" : "login";
      show();
      return null;
    }
    hide();
    return currentUser;
  }

  async function logout() {
    try { await window.CPApi.post("/api/auth/logout", {}); } catch (err) { /* 忽略 */ }
    currentUser = null;
    mode = "login";
    show();
    window.dispatchEvent(new CustomEvent("cp:logout"));
  }

  window.CPAuth = {
    load,
    logout,
    show,
    get user() { return currentUser; },
  };
})();
