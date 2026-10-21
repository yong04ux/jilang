/* 激浪 · 极简 History API 路由
 * 支持：/tasks/:id 这类参数路由、未知路径回退、前进后退、深链直接打开。
 */
(function () {
  "use strict";

  const routes = [];
  let notFound = null;
  let onChange = null;
  let current = null;

  function compile(path) {
    const keys = [];
    // 先把 :param 占位成哨兵，再转义特殊字符，最后把哨兵换成捕获组。
    // 直接在已转义的字符串上做替换会因为 "/" 变成 "\/" 而匹配不到。
    const SENTINEL = "\u0000";
    let pattern = path
      .replace(/\/+$/, "")
      .replace(/:([A-Za-z0-9_]+)/g, function (_m, key) {
        keys.push(key);
        return SENTINEL;
      })
      .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      .replace(/\\\//g, "/")
      .split(SENTINEL)
      .join("([^/]+)");
    if (!pattern) pattern = "/";
    return { re: new RegExp("^" + pattern + "$"), keys };
  }

  function normalize(path) {
    if (!path) return "/";
    const clean = path.split("?")[0].split("#")[0];
    if (clean.length > 1 && clean.endsWith("/")) return clean.slice(0, -1);
    return clean || "/";
  }

  function define(path, handler, meta) {
    routes.push({ path, handler, meta: meta || {}, ...compile(path) });
  }

  function setNotFound(handler) { notFound = handler; }

  function resolve(path) {
    const clean = normalize(path);
    for (let i = 0; i < routes.length; i += 1) {
      const route = routes[i];
      const m = route.re.exec(clean);
      if (!m) continue;
      const params = {};
      route.keys.forEach(function (key, idx) { params[key] = decodeURIComponent(m[idx + 1]); });
      return { route, params, path: clean };
    }
    return { route: null, params: {}, path: clean };
  }

  function render(path) {
    const query = {};
    const rawQuery = (path.split("?")[1] || "").split("#")[0];
    rawQuery.split("&").forEach(function (pair) {
      if (!pair) return;
      const kv = pair.split("=");
      query[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || "");
    });

    const hit = resolve(path);
    current = hit;
    if (onChange) onChange(hit, query);

    if (hit.route) {
      hit.route.handler(hit.params, query);
    } else if (notFound) {
      notFound(hit.path);
    }
    window.CPIcon && window.CPIcon.hydrate(document);
  }

  function go(path, opts) {
    const replace = opts && opts.replace;
    if (normalize(path) === normalize(location.pathname) && !(opts && opts.force)) {
      render(path);
      return;
    }
    if (replace) history.replaceState({}, "", path);
    else history.pushState({}, "", path);
    render(path);
    window.scrollTo({ top: 0, behavior: "instant" in document.documentElement.style ? "instant" : "auto" });
  }

  function start(fallback) {
    notFound = fallback;
    window.addEventListener("popstate", function () { render(location.pathname + location.search); });
    // 拦截站内链接，避免整页刷新
    document.addEventListener("click", function (event) {
      const anchor = event.target.closest("a[data-link]");
      if (!anchor) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("http") || href.startsWith("#")) return;
      event.preventDefault();
      go(href);
    });
    render(location.pathname + location.search);
  }

  window.CPRouter = {
    define, start, go, render, resolve, normalize,
    setOnChange(fn) { onChange = fn; },
    get current() { return current; },
  };
})();
