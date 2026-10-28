/* 激浪 · Panels
   1) split(container, opts)      —— react-resizable-panels 的等价实现
      在容器前两个子节点之间插入 1px 拖拽条，比例写进 --split-a，落 localStorage。
      移动端（<=960px）由 CSS 接管，自动退化为上下堆叠。
   2) sortable(list, opts)        —— dnd-kit 的等价实现
      基于原生 draggable 的列表重排，结束回调返回新的节点顺序。
*/
(function () {
  "use strict";

  const NARROW = window.matchMedia("(max-width: 960px)");

  /* ==========================================================================
     Resizable split
     ======================================================================== */

  function clamp(value, min, max) { return Math.min(max, Math.max(min, value)); }

  function split(container, options) {
    if (!container) return null;
    options = options || {};

    /* 幂等：重复 render 时不重复挂载 */
    if (container.__cpSplit) return container.__cpSplit;

    const handle = container.querySelector(":scope > .split-handle") || (function () {
      const panes = Array.prototype.filter.call(container.children, function (node) {
        return !node.classList.contains("split-handle");
      });
      if (panes.length < 2) return null;
      const bar = document.createElement("div");
      bar.className = "split-handle";
      panes[0].after(bar);
      return bar;
    })();

    if (!handle) return null;

    const key = options.storageKey || ("cp.split:" + (container.id || "pane"));
    const min = options.min === undefined ? 0.28 : options.min;
    const max = options.max === undefined ? 0.78 : options.max;
    const fallback = options.defaultSize === undefined ? 0.58 : options.defaultSize;

    let value = fallback;
    try {
      const saved = parseFloat(localStorage.getItem(key));
      if (!Number.isNaN(saved)) value = clamp(saved, min, max);
    } catch (err) { /* 隐私模式忽略 */ }

    function apply(next, persist) {
      value = clamp(next, min, max);
      container.style.setProperty("--split-a", (value * 100).toFixed(2) + "%");
      handle.setAttribute("aria-valuenow", String(Math.round(value * 100)));
      handle.setAttribute("aria-valuemin", String(Math.round(min * 100)));
      handle.setAttribute("aria-valuemax", String(Math.round(max * 100)));
      if (persist) {
        try { localStorage.setItem(key, String(value)); } catch (err) { /* 忽略 */ }
      }
    }

    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-orientation", "vertical");
    handle.setAttribute("aria-label", options.label || "调整分栏宽度");
    handle.tabIndex = 0;
    apply(value, false);

    let dragging = false;

    function onPointerDown(event) {
      if (NARROW.matches) return;
      if (event.button !== undefined && event.button !== 0) return;
      dragging = true;
      container.classList.add("is-resizing");
      document.body.classList.add("is-resizing");
      handle.setPointerCapture(event.pointerId);
      event.preventDefault();
    }

    function onPointerMove(event) {
      if (!dragging) return;
      const rect = container.getBoundingClientRect();
      if (rect.width === 0) return;
      apply((event.clientX - rect.left) / rect.width, false);
    }

    function onPointerUp(event) {
      if (!dragging) return;
      dragging = false;
      container.classList.remove("is-resizing");
      document.body.classList.remove("is-resizing");
      if (handle.hasPointerCapture && handle.hasPointerCapture(event.pointerId)) {
        handle.releasePointerCapture(event.pointerId);
      }
      apply(value, true);
    }

    function onKeyDown(event) {
      const step = event.shiftKey ? 0.08 : 0.02;
      if (event.key === "ArrowLeft") { apply(value - step, true); event.preventDefault(); }
      else if (event.key === "ArrowRight") { apply(value + step, true); event.preventDefault(); }
      else if (event.key === "Home") { apply(min, true); event.preventDefault(); }
      else if (event.key === "End") { apply(max, true); event.preventDefault(); }
    }

    function onReset() { apply(fallback, true); }

    handle.addEventListener("pointerdown", onPointerDown);
    handle.addEventListener("pointermove", onPointerMove);
    handle.addEventListener("pointerup", onPointerUp);
    handle.addEventListener("pointercancel", onPointerUp);
    handle.addEventListener("keydown", onKeyDown);
    handle.addEventListener("dblclick", onReset);

    const api = {
      setSize: function (ratio) { apply(ratio, true); },
      getSize: function () { return value; },
      destroy: function () {
        handle.removeEventListener("pointerdown", onPointerDown);
        handle.removeEventListener("pointermove", onPointerMove);
        handle.removeEventListener("pointerup", onPointerUp);
        handle.removeEventListener("pointercancel", onPointerUp);
        handle.removeEventListener("keydown", onKeyDown);
        handle.removeEventListener("dblclick", onReset);
        delete container.__cpSplit;
      },
    };

    container.__cpSplit = api;
    return api;
  }

  /* ==========================================================================
     Sortable list
     ======================================================================== */

  function sortable(list, options) {
    if (!list) return null;
    options = options || {};
    const itemSel = options.item || ":scope > *";
    let dragEl = null;

    function items() { return Array.prototype.slice.call(list.querySelectorAll(itemSel)); }

    function afterElement(y) {
      const candidates = items().filter(function (el) { return el !== dragEl; });
      for (let i = 0; i < candidates.length; i += 1) {
        const box = candidates[i].getBoundingClientRect();
        if (y < box.top + box.height / 2) return candidates[i];
      }
      return null;
    }

    function bind() {
      items().forEach(function (el) {
        if (el.dataset.sortable === "1") return;
        el.dataset.sortable = "1";
        el.draggable = true;
        el.classList.add("drag-item");

        el.addEventListener("dragstart", function (event) {
          dragEl = el;
          el.classList.add("is-dragging");
          if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", el.dataset.id || "");
          }
          if (typeof options.onStart === "function") options.onStart(el);
        });

        el.addEventListener("dragend", function () {
          el.classList.remove("is-dragging");
          items().forEach(function (node) { node.classList.remove("is-drop-target"); });
          dragEl = null;
          if (typeof options.onEnd === "function") {
            options.onEnd(items().map(function (node) { return node.dataset.id || null; }));
          }
        });

        el.addEventListener("dragover", function (event) {
          if (!dragEl || dragEl === el) return;
          event.preventDefault();
          const box = el.getBoundingClientRect();
          const before = (event.clientY - box.top) < box.height / 2;
          list.insertBefore(dragEl, before ? el : el.nextSibling);
          items().forEach(function (node) {
            node.classList.toggle("is-drop-target", node === el);
          });
        });

        el.addEventListener("drop", function (event) { event.preventDefault(); });
      });
    }

    bind();
    return { refresh: bind, items: items };
  }

  window.CPPanels = { split: split, sortable: sortable };
})();
