/* 激浪 · Motion
   Motion（原 Framer Motion）的等价实现：基于 Web Animations API，
   统一曲线取自 tokens.css 的 --ease-out / --dur-*，并强制尊重 prefers-reduced-motion。
   提供：animate / fadeIn / fadeOut / stagger / inView / tap / scrollTo
*/
(function () {
  "use strict";

  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)");

  function reduced() { return REDUCED.matches; }

  function toMs(value, fallback) {
    if (typeof value === "number") return value;
    if (typeof value === "string" && /ms$/.test(value)) return parseFloat(value);
    if (typeof value === "string" && /s$/.test(value)) return parseFloat(value) * 1000;
    return fallback;
  }

  /* 从 CSS 变量里读默认时长，保证 JS 与 CSS 同一套节奏 */
  function tokenMs(name, fallback) {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(name);
    return toMs(raw.trim(), fallback);
  }

  function finish(el, frames) {
    const last = frames[frames.length - 1];
    if (!last || typeof last !== "object") return;
    Object.keys(last).forEach(function (k) {
      if (k === "offset" || k === "easing") return;
      el.style[k] = last[k];
    });
  }

  /* 主入口：animate(el, frames, options) → Promise */
  function animate(el, frames, options) {
    options = options || {};
    if (!el) return Promise.resolve();

    const duration = options.duration !== undefined
      ? toMs(options.duration, 180)
      : tokenMs("--dur-2", 180);
    const delay = toMs(options.delay, 0) || 0;

    if (reduced() || duration === 0) {
      finish(el, frames);
      if (typeof options.onComplete === "function") options.onComplete();
      return Promise.resolve();
    }

    if (typeof el.animate !== "function") {
      finish(el, frames);
      return Promise.resolve();
    }

    const anim = el.animate(frames, {
      duration: duration,
      delay: delay,
      easing: options.easing || "cubic-bezier(.16, 1, .3, 1)",
      fill: options.fill || "backwards",
      iterations: options.iterations || 1,
    });

    return anim.finished
      .then(function () {
        finish(el, frames);
        if (typeof options.onComplete === "function") options.onComplete();
      })
      .catch(function () { /* 被 cancel 视为完成 */ });
  }

  function fadeIn(el, options) {
    options = options || {};
    const y = options.y === undefined ? 4 : options.y;
    const x = options.x === undefined ? 0 : options.x;
    const scale = options.scale === undefined ? 1 : options.scale;
    const from = "translate3d(" + x + "px," + y + "px,0)" +
      (scale === 1 ? "" : " scale(" + scale + ")");
    return animate(el, [
      { opacity: 0, transform: from },
      { opacity: 1, transform: "translate3d(0,0,0) scale(1)" },
    ], {
      duration: options.duration !== undefined ? options.duration : tokenMs("--dur-2", 180),
      delay: options.delay,
      onComplete: options.onComplete,
    });
  }

  function fadeOut(el, options) {
    options = options || {};
    const y = options.y === undefined ? 2 : options.y;
    return animate(el, [
      { opacity: 1, transform: "translate3d(0,0,0)" },
      { opacity: 0, transform: "translate3d(0," + y + "px,0)" },
    ], {
      duration: options.duration !== undefined ? options.duration : tokenMs("--dur-1", 120),
      fill: "forwards",
    }).then(function () {
      if (options.remove !== false && el.parentNode) el.parentNode.removeChild(el);
      if (typeof options.onComplete === "function") options.onComplete();
    });
  }

  /* 交错进场：容器内所有 [data-motion-item]，按序淡入 */
  function stagger(container, options) {
    options = options || {};
    if (!container) return Promise.resolve();
    const items = container.querySelectorAll(options.selector || "[data-motion-item]");
    if (!items.length) return Promise.resolve();
    const step = options.step === undefined ? 24 : options.step;
    const y = options.y === undefined ? 6 : options.y;
    const jobs = [];
    Array.prototype.forEach.call(items, function (el, i) {
      jobs.push(fadeIn(el, { y: y, delay: i * step, duration: options.duration }));
    });
    return Promise.all(jobs);
  }

  /* 进入视口一次性回调（列表懒进场 / 埋点都可用） */
  function inView(el, callback, options) {
    options = options || {};
    if (!el || typeof IntersectionObserver !== "function") {
      if (typeof callback === "function") callback(el);
      return function () {};
    }
    const io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        io.unobserve(entry.target);
        if (typeof callback === "function") callback(entry.target);
      });
    }, { rootMargin: options.rootMargin || "0px 0px -10% 0px", threshold: options.threshold || 0.1 });
    io.observe(el);
    return function () { io.disconnect(); };
  }

  /* 按下微缩：给按钮/卡片一点按压反馈（Motion 的 whileTap） */
  function tap(el, scale) {
    if (!el) return;
    const s = scale === undefined ? 0.985 : scale;
    el.addEventListener("pointerdown", function () {
      if (reduced()) return;
      el.style.transition = "transform 90ms cubic-bezier(.16,1,.3,1)";
      el.style.transform = "scale(" + s + ")";
    });
    ["pointerup", "pointerleave", "pointercancel"].forEach(function (evt) {
      el.addEventListener(evt, function () {
        el.style.transform = "";
      });
    });
  }

  function scrollTo(el, options) {
    options = options || {};
    if (!el) return;
    el.scrollIntoView({
      block: options.block || "nearest",
      behavior: reduced() ? "auto" : "smooth",
    });
  }

  window.CPMotion = {
    reduced: reduced,
    animate: animate,
    fadeIn: fadeIn,
    fadeOut: fadeOut,
    stagger: stagger,
    inView: inView,
    tap: tap,
    scrollTo: scrollTo,
  };
})();
