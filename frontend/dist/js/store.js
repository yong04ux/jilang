/* 激浪 · Store
   Zustand 的等价实现：create(initializer) → getState / setState / subscribe(selector)
   零依赖、可持久化、支持选择器订阅（值不变不触发回调）。
   用法：
     const ui = CPStore.create(function (set, get) {
       return { collapsed: false, toggle: function () { set({ collapsed: !get().collapsed }); } };
     });
     ui.subscribe(function (s) { return s.collapsed; }, function (v) { ... });
*/
(function () {
  "use strict";

  function create(initializer) {
    let state;
    let prev;
    const listeners = new Set();

    function getState() { return state; }

    function setState(partial, replace) {
      const next = typeof partial === "function" ? partial(state) : partial;
      if (next === undefined || next === null) return;
      if (Object.is(next, state)) return;
      prev = state;
      state = replace ? next : Object.assign({}, state, next);
      listeners.forEach(function (entry) {
        if (entry.selector) {
          const a = entry.selector(state);
          const b = entry.selector(prev);
          if (!Object.is(a, b)) entry.listener(a, b);
        } else {
          entry.listener(state, prev);
        }
      });
    }

    /* subscribe(listener) 或 subscribe(selector, listener) */
    function subscribe(a, b) {
      const entry = typeof a === "function" && typeof b === "function"
        ? { selector: a, listener: b }
        : { selector: null, listener: a };
      listeners.add(entry);
      return function unsubscribe() { listeners.delete(entry); };
    }

    state = typeof initializer === "function" ? initializer(setState, getState) : Object.assign({}, initializer);

    return { getState: getState, setState: setState, subscribe: subscribe };
  }

  /* 把一份 state 持久化到 localStorage，并在创建时回灌 */
  function persist(store, key, pick) {
    function read() {
      try {
        const raw = localStorage.getItem(key);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return pick ? pick(parsed) : parsed;
      } catch (err) { return null; }
    }

    const saved = read();
    if (saved) store.setState(saved);

    store.subscribe(function (state) {
      try {
        const snapshot = pick ? pick(state) : state;
        localStorage.setItem(key, JSON.stringify(snapshot));
      } catch (err) { /* 隐私模式下忽略 */ }
    });

    return store;
  }

  /* 把 store 的某个选择器绑定到 DOM，值变了才重绘 */
  function connect(store, selector, render, root) {
    const run = function () { render(selector(store.getState()), root); };
    run();
    return store.subscribe(selector, run);
  }

  window.CPStore = { create: create, persist: persist, connect: connect };
})();
