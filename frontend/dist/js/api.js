/* 激浪 · API 客户端
 * 统一处理：同源凭据、JSON 解析、错误结构、401 跳登录。
 */
(function () {
  "use strict";

  let unauthorizedHandler = null;

  /* 登录 / 注册这类「入口」接口，401 表示账号密码不对，不是会话过期。
     不能按全局 401 处理，否则会把"密码错了"显示成"登录已过期"。 */
  const AUTH_ENTRY_PATHS = ["/api/auth/login", "/api/auth/register"];

  function isAuthEntry(path) {
    return AUTH_ENTRY_PATHS.some(function (p) { return path.indexOf(p) === 0; });
  }

  function ApiError(message, status, detail) {
    const err = new Error(message);
    err.status = status;
    err.detail = detail;
    return err;
  }

  function describe(detail, status) {
    if (!detail) return `请求失败（HTTP ${status}）`;
    if (typeof detail === "string") return detail;
    if (detail.message) {
      const errors = Array.isArray(detail.errors) ? detail.errors : [];
      if (!errors.length) {
        // 后端的 code 是内部分类，不进界面；只对「缺 Key」这一类做可读补充
        const hint = detail.code === "api_key_required" ? "（需要先在设置里填入 API Key）" : "";
        return detail.message + hint;
      }
      const first = errors.slice(0, 3).map(function (e) {
        const field = e.field ? e.field + "：" : e.row ? "第 " + e.row + " 行：" : "";
        return field + (e.message || "");
      });
      return detail.message + " · " + first.join("；");
    }
    if (Array.isArray(detail)) {
      return detail.map(function (e) { return e.msg || JSON.stringify(e); }).join("；");
    }
    return String(detail);
  }

  async function request(path, options) {
    const opts = options || {};
    const init = {
      method: opts.method || "GET",
      credentials: "same-origin",
      headers: Object.assign({ Accept: "application/json" }, opts.headers || {}),
    };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    if (opts.form !== undefined) {
      init.body = opts.form;
    }

    let resp;
    try {
      resp = await fetch(path, init);
    } catch (err) {
      throw ApiError("网络不可用，请确认服务仍在运行", 0, null);
    }

    const text = await resp.text();
    let data = null;
    if (text) {
      try { data = JSON.parse(text); } catch (err) { data = null; }
    }

    /* 只有业务接口的 401 才代表登录态失效；入口接口的 401 走下面的正常报错流程，
       这样"用户名或密码不正确"能原样显示给用户 */
    if (resp.status === 401 && !isAuthEntry(path)) {
      if (unauthorizedHandler) unauthorizedHandler();
      throw ApiError("登录已过期，请重新登录", 401, data && data.detail);
    }

    if (!resp.ok) {
      const detail = data && data.detail !== undefined ? data.detail : data;
      throw ApiError(describe(detail, resp.status), resp.status, detail);
    }
    return data;
  }

  window.CPApi = {
    request,
    get: (path) => request(path),
    post: (path, body) => request(path, { method: "POST", body }),
    put: (path, body) => request(path, { method: "PUT", body }),
    del: (path, body) => request(path, { method: "DELETE", body }),
    postForm: (path, form) => request(path, { method: "POST", form }),
    onUnauthorized(fn) { unauthorizedHandler = fn; },
  };
})();
