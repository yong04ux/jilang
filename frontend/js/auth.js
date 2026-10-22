/* 激浪 · 登录门
 * 复用 /api/auth/* 接口与 HttpOnly Cookie 会话。
 * 未登录时不渲染业务页面，避免出现"点了没反应"的假界面。
 *
 * 演示站策略：
 * - 固定 demo 账号提示（账号名固定，密码由部署方决定，不在前端硬编码）；
 * - 「一键体验」调用 POST /api/auth/demo 创建 24h 临时账号；
 * - 开放注册关闭后不再显示注册入口。
 *
 * 本文件只负责「未登录时展示什么」，认证状态与接口调用一律走 CPApi / CPAuth，
 * 改动渲染不影响其他页面的登录态判断。
 */
(function () {
  "use strict";
  const U = window.CPUi;

  let currentUser = null;
  let mode = "login"; // login | register | setup
  let allowRegister = false;
  let demoAccount = false;   // 部署方是否配置了固定 demo 账号
  let guestTtl = 24;         // 临时账号有效期（小时），来自服务端

  const DEMO_LABEL = "一键体验";

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

  /* 把底层错误翻成用户能照着做的下一步；服务端已经是中文就不动它 */
  function friendly(err) {
    const raw = (err && err.message) || "";
    if (!raw) return "操作没有完成，请重试一次。";
    if (/Failed to fetch|NetworkError|Load failed|网络/i.test(raw)) {
      return "连不上服务，请检查网络后重试。";
    }
    return raw;
  }

  /* ---------------------------------------------------------------- 左侧叙事 */

  const POINTS = [
    "竞品分析：价格分布、评论痛点、差异化机会，附原文出处",
    "Listing 生成：基于已确认的商品事实，生成后再做一遍事实核对",
    "数据导入：先预览、再校对字段，有问题可下载清单逐条改",
    "自带模型密钥：平台不提供模型额度，也不保存你的密钥",
  ];

  function pitch() {
    return (
      `<aside class="auth-pitch">` +
      `<div class="auth-lockup">` +
      `<img class="auth-lockup-mark" src="/media/logo-mark.svg?v=2" alt="" />` +
      `<span class="auth-lockup-name">激浪</span>` +
      `<span class="auth-lockup-tag">跨境电商 AI 运营助手</span>` +
      `</div>` +
      `<h2 class="auth-headline">把业务目标<br>变成可复核的执行结果</h2>` +
      `<p class="auth-lede">竞品分析、Listing 撰写、数据导入与人工审批在同一个流程里完成。` +
      `每一步都能看到当前状态和判断依据，结果不会替你编造销量或排名。</p>` +
      `<ul class="auth-points">` +
      POINTS.map(function (text) {
        return `<li class="auth-point">${U.icon("check")}<span>${U.esc(text)}</span></li>`;
      }).join("") +
      `</ul>` +
      `<p class="auth-note">页面里的示例数据都带「示例」标记，导入你自己的文件后就会换成你的数据。</p>` +
      `</aside>`
    );
  }

  /* ---------------------------------------------------------------- 表单字段 */

  /* 密码框独立成组：眼睛按钮不能放进 label（label 内只允许被标记的控件） */
  function passwordField(id, name, label, autocomplete) {
    return (
      `<div class="field">` +
      `<label class="field-label" for="${id}">${label}</label>` +
      `<span class="auth-group">` +
      `<input id="${id}" name="${name}" type="password" required minlength="8" ` +
      `placeholder="至少 8 位" autocomplete="${autocomplete}" />` +
      `<button type="button" class="auth-reveal" data-reveal="${id}" ` +
      `aria-label="显示密码" aria-pressed="false">${U.icon("eye")}</button>` +
      `</span>` +
      `</div>`
    );
  }

  /* ---------------------------------------------------------------- 渲染 */

  function show(errorText) {
    const node = gate();
    node.hidden = false;

    const isRegister = mode !== "login";
    const title = mode === "setup" ? "创建管理员账号" : isRegister ? "创建账号" : "登录";
    const submitLabel = isRegister ? "创建账号" : "登录";
    const busyLabel = isRegister ? "正在创建…" : "正在登录…";
    const hint = mode === "setup"
      ? "这是首次启动，第一个注册的账号会成为管理员，请牢记账号密码。"
      : isRegister
        ? "用户名至少 3 个字符，密码至少 8 位。"
        : "";

    const switcher = isRegister
      ? `<p class="auth-alt"><button type="button" class="btn-link" id="auth-switch">返回登录</button></p>`
      : allowRegister
        ? `<p class="auth-alt">还没有账号？ <button type="button" class="btn-link" id="auth-switch">立即注册</button></p>`
        : "";

    node.innerHTML =
      `<div class="auth-shell">` +
      pitch() +
      `<div class="auth-card">` +

      `<div class="auth-card-head">` +
      `<img class="auth-card-mark" src="/media/logo-mark.svg?v=2" alt="" />` +
      `<div>` +
      `<h1 class="auth-title">${U.esc(title)}</h1>` +
      (hint ? `<p class="auth-hint" id="auth-hint">${U.esc(hint)}</p>` : "") +
      `</div>` +
      `</div>` +

      `<form id="auth-form" class="auth-form" autocomplete="on"` +
      (hint ? ` aria-describedby="auth-hint"` : "") + `>` +
      `<div class="field">` +
      `<label class="field-label" for="auth-username">用户名</label>` +
      `<input id="auth-username" name="username" required minlength="3" maxlength="32" ` +
      `placeholder="至少 3 个字符" autocomplete="username" />` +
      `</div>` +
      passwordField("auth-password", "password", "密码",
        isRegister ? "new-password" : "current-password") +
      (isRegister ? passwordField("auth-confirm", "confirm", "确认密码", "new-password") : "") +
      `<p class="auth-error" id="auth-error" role="alert" hidden></p>` +
      `<button type="submit" class="btn btn-primary btn-lg auth-submit">${submitLabel}</button>` +
      `</form>` +

      switcher +

      `<div class="auth-divider"><span>或</span></div>` +
      `<button type="button" class="btn btn-secondary btn-lg auth-demo-btn" id="auth-demo">` +
      `${U.icon("sparkles")}<span class="auth-demo-label">${DEMO_LABEL}</span>` +
      `</button>` +
      `<p class="auth-demo-note">创建一个 ${guestTtl} 小时临时账号，内容与密钥单独保存，到期自动清理。` +
      // 没配密码时后端不会创建固定账号，这里就不能提示，否则访客会去找一个不存在的账号
      (demoAccount
        ? `<br>体验账号 <code>demo</code> 可直接浏览示例数据，但不能保存密钥。`
        : "") +
      `</p>` +

      `<p class="auth-foot">密码与密钥只用于你的账号，不会出现在任何执行结果里。</p>` +
      `</div></div>`;

    window.CPIcon.hydrate(node);

    const form = node.querySelector("#auth-form");
    const error = node.querySelector("#auth-error");
    const submit = form.querySelector("button[type=submit]");
    const fields = form.querySelectorAll(".field");

    function setError(text) {
      if (!text) {
        error.hidden = true;
        error.innerHTML = "";
        return;
      }
      error.innerHTML = U.icon("alert") + "<span></span>";
      error.querySelector("span").textContent = text;
      error.hidden = false;
    }

    function clearError() {
      if (error.hidden) return;
      setError("");
      fields.forEach(function (f) { f.classList.remove("is-invalid"); });
    }

    if (errorText) setError(errorText);
    form.addEventListener("input", clearError);

    /* 密码可见性切换 */
    node.querySelectorAll("[data-reveal]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const input = node.querySelector("#" + btn.getAttribute("data-reveal"));
        if (!input) return;
        const revealed = input.type === "password";
        input.type = revealed ? "text" : "password";
        btn.innerHTML = U.icon(revealed ? "eyeOff" : "eye");
        btn.setAttribute("aria-pressed", revealed ? "true" : "false");
        btn.setAttribute("aria-label", revealed ? "隐藏密码" : "显示密码");
        input.focus();
      });
    });

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      clearError();

      const username = form.username.value.trim();
      const password = form.password.value;

      if (isRegister && password !== form.confirm.value) {
        form.password.parentNode.parentNode.classList.add("is-invalid");
        form.confirm.parentNode.parentNode.classList.add("is-invalid");
        setError("两次输入的密码不一致，请重新确认。");
        form.confirm.focus();
        return;
      }

      submit.disabled = true;
      submit.textContent = busyLabel;
      try {
        await window.CPApi.post(mode === "login" ? "/api/auth/login" : "/api/auth/register", {
          username: username,
          password: password,
        });
        // 登录成功但会话没读回来（网络抖动）：不能静默放行，否则页面空着也没提示
        if (!(await load(true))) {
          show("账号信息读取失败，请重新登录一次。");
          return;
        }
        window.dispatchEvent(new CustomEvent("cp:authenticated"));
      } catch (err) {
        setError(friendly(err));
      } finally {
        submit.disabled = false;
        submit.textContent = submitLabel;
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
      const demoLabel = demo.querySelector(".auth-demo-label");
      demo.addEventListener("click", async function () {
        clearError();
        demo.disabled = true;
        if (demoLabel) demoLabel.textContent = "正在创建…";
        try {
          const data = await window.CPApi.post("/api/auth/demo", {});
          if (!(await load(true))) {
            show("临时账号已创建，但会话没有读到，请刷新页面重试。");
            return;
          }
          window.dispatchEvent(new CustomEvent("cp:authenticated"));
          const hours = data && data.expires_in_hours ? data.expires_in_hours : 24;
          U.toast(`临时账号已创建，${hours} 小时后自动清理`, "ok");
        } catch (err) {
          demo.disabled = false;
          if (demoLabel) demoLabel.textContent = DEMO_LABEL;
          setError(friendly(err));
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
      // 不把底层错误原文抛给用户
      if (!silent) show("暂时连不上服务，请稍后刷新页面重试。");
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
