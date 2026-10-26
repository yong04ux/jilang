/* 激浪 · 技能广场（/skills）
 *
 * 两级视图，共用一个路由：
 *   /skills                  广场：卡片网格 + 搜索 + 来源/场景分类筛选
 *   /skills?skill=<key>      详情：参数表单 + 运行 + 结果
 *
 * 用查询参数而不是新增路由，是为了保住已经在用的深链——
 * 「数据校验」跑完会跳到 /skills?skill=competitor_analysis&batch=<id>。
 *
 * 能力名称、分类、说明、入参全部来自 GET /api/skills，
 * 前端只保留「卡片长什么样」这类展示信息（见 catalog.js 的 PRESENTATION）。
 */
(function () {
  "use strict";
  const U = window.CPUi;
  const A = window.CPApi;
  const C = window.CPCatalog;
  const F = window.CPSchemaForm;
  const R = window.CPRender;
  const AR = window.CPAsyncRun;

  /* 这两类要真实生成文字/做长分析，等十几秒是常态，走后台任务 + 轮询 */
  const SLOW = { competitor_analysis: true, listing_generation: true };

  /* 精选位：放最常用的三项，不按接口顺序。全量列表里它们仍然会出现。 */
  const FEATURED = ["competitor_analysis", "listing_generation", "profit_calc"];

  const state = {
    key: "",
    skills: [],
    running: false,
    taskId: null,
    poller: null,
    batch: "",
    result: null,
    error: "",
    needKey: false,
    steps: [],
    filter: { source: "all", cat: "all", q: "" },
  };

  function reset() {
    if (state.poller && state.poller.stop) state.poller.stop();
    state.running = false;
    state.taskId = null;
    state.poller = null;
    state.result = null;
    state.error = "";
    state.needKey = false;
    state.steps = [];
  }

  /* ==========================================================================
     广场
     ========================================================================== */

  function toneClass(tone) {
    return tone === "info" ? "is-info" : tone === "neutral" ? "is-neutral" : "";
  }

  function avatar(skill, size) {
    return (
      `<span class="sk-avatar ${toneClass(skill.tone)}${size === "lg" ? " sk-avatar--lg" : ""}">` +
      `${U.esc(skill.icon)}</span>`
    );
  }

  function cardHtml(skill) {
    const badge =
      skill.requires.indexOf("llm") !== -1
        ? `<span class="badge badge-warn sk-card-badge">需要密钥</span>`
        : "";
    const tags = (skill.tags || [])
      .map(function (t) { return `<span class="sk-tag">${U.esc(t)}</span>`; })
      .join("");
    return (
      `<article class="sk-card" data-open="${U.esc(skill.key)}">` +
      `<div class="sk-card-head">` +
      avatar(skill) +
      `<div class="sk-card-title-wrap">` +
      `<h3 class="sk-card-title">${U.esc(skill.name)}</h3>` +
      `<span class="sk-card-cat">${U.esc(skill.cat)}</span>` +
      `</div>` +
      badge +
      `</div>` +
      `<p class="sk-card-desc">${U.esc(skill.desc)}</p>` +
      `<div class="sk-card-tags">${tags}</div>` +
      `<div class="sk-card-foot">` +
      `<span class="sk-card-src">来源：${skill.builtin ? "激浪内置" : "你创建的"}</span>` +
      `<button type="button" class="btn btn-sm" data-open="${U.esc(skill.key)}">运行</button>` +
      `</div>` +
      `</article>`
    );
  }

  function facetChips(kind, label, total, entries) {
    const active = state.filter[kind];
    const chip = function (value, text, count) {
      const on = active === value ? " is-active" : "";
      return (
        `<button type="button" class="sk-chip${on}" data-facet="${kind}" data-value="${U.esc(value)}">` +
        `${U.esc(text)}<span class="sk-chip-num">${count}</span></button>`
      );
    };
    return (
      `<div class="sk-facet">` +
      `<span class="sk-facet-label">${U.esc(label)}：</span>` +
      `<div class="chips">` +
      chip("all", "全部", total) +
      entries
        .map(function (e) { return chip(e.value, e.label, e.count); })
        .join("") +
      `</div></div>`
    );
  }

  function facetEntries() {
    const byCat = {};
    let builtin = 0;
    state.skills.forEach(function (s) {
      if (s.cat) byCat[s.cat] = (byCat[s.cat] || 0) + 1;
      if (s.builtin) builtin += 1;
    });
    return {
      total: state.skills.length,
      sources: [
        { value: "builtin", label: "激浪内置", count: builtin },
        { value: "custom", label: "你创建的", count: state.skills.length - builtin },
      ],
      cats: Object.keys(byCat).map(function (key) {
        return { value: key, label: key, count: byCat[key] };
      }),
    };
  }

  function match(skill) {
    const f = state.filter;
    if (f.source === "builtin" && !skill.builtin) return false;
    if (f.source === "custom" && skill.builtin) return false;
    if (f.cat !== "all" && skill.cat !== f.cat) return false;
    const q = f.q.trim().toLowerCase();
    if (!q) return true;
    const hay = [skill.name, skill.cat, skill.desc]
      .concat(skill.tags || [])
      .join(" ")
      .toLowerCase();
    return hay.indexOf(q) !== -1;
  }

  function filteredSkills() {
    return state.skills.filter(match);
  }

  function gridHtml() {
    const list = filteredSkills();
    if (!list.length) {
      return (
        `<div class="sk-empty">${U.icon("search")}<div>` +
        `<strong>没有匹配的技能</strong><br>换个关键词，或把筛选条件清空再试。</div></div>`
      );
    }
    return `<div class="sk-grid">${list.map(cardHtml).join("")}</div>`;
  }

  function paintGrid(root) {
    const facts = facetEntries();
    const featured = FEATURED.map(function (key) { return C.skillByKey(key); }).filter(Boolean);

    root.innerHTML =
      `<div class="view"><div class="page"><div class="page-inner">` +
      `<div class="page-head"><div><h1 class="page-title">技能广场</h1>` +
      `<p class="page-desc">每个能力都能单独跑一遍：填好参数，直接看结果。同样的能力也会在 AI 助手里按目标自动串起来。</p></div>` +
      `<div class="page-actions"><a class="btn btn-sm" href="/workbench" data-link>去 AI 助手</a></div></div>` +
      (featured.length
        ? `<section class="sk-section">` +
          `<div class="sk-section-head"><h2 class="sk-h2">精选技能</h2>` +
          `<a class="sk-more" href="#sk-all">查看全部${U.icon("arrowRight")}</a></div>` +
          `<div class="sk-grid">${featured.map(cardHtml).join("")}</div>` +
          `</section>`
        : "") +
      `<section class="sk-section" id="sk-all">` +
      `<div class="sk-section-head"><h2 class="sk-h2">全部技能</h2>` +
      `<label class="sk-search">${U.icon("search")}` +
      `<input type="search" id="sk-search" placeholder="搜索技能" value="${U.esc(state.filter.q)}" />` +
      `</label></div>` +
      `<div class="sk-facets" id="sk-facets">` +
      facetChips("source", "来源", facts.total, facts.sources) +
      facetChips("cat", "场景分类", facts.total, facts.cats) +
      `</div>` +
      `<div class="sk-count" id="sk-count"></div>` +
      `<div id="sk-grid-all">${gridHtml()}</div>` +
      `</section>` +
      `</div></div></div>`;

    window.CPIcon.hydrate(root);
    updateCount(root);
    wireGrid(root);
  }

  function updateCount(root) {
    const el = root.querySelector("#sk-count");
    if (!el) return;
    el.textContent = `共 ${filteredSkills().length} 项`;
  }

  function refreshGrid(root) {
    const host = root.querySelector("#sk-grid-all");
    if (host) {
      host.innerHTML = gridHtml();
      window.CPIcon.hydrate(host);
      bindOpen(root, host);
    }
    root.querySelectorAll("[data-facet]").forEach(function (btn) {
      const kind = btn.getAttribute("data-facet");
      const on = btn.getAttribute("data-value") === state.filter[kind];
      btn.classList.toggle("is-active", on);
    });
    updateCount(root);
  }

  function bindOpen(root, scope) {
    (scope || root).querySelectorAll("[data-open]").forEach(function (el) {
      el.addEventListener("click", function () {
        window.CPRouter.go("/skills?skill=" + encodeURIComponent(el.getAttribute("data-open")));
      });
    });
  }

  function wireGrid(root) {
    bindOpen(root, root);

    root.querySelectorAll("[data-facet]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const kind = btn.getAttribute("data-facet");
        if (state.filter[kind] === btn.getAttribute("data-value")) return;
        state.filter[kind] = btn.getAttribute("data-value");
        refreshGrid(root);
      });
    });

    const search = root.querySelector("#sk-search");
    if (search) {
      search.addEventListener("input", function () {
        state.filter.q = search.value;
        refreshGrid(root);
      });
    }
  }

  /* ==========================================================================
     详情（参数与结果）
     ========================================================================== */

  function detailHtml(skill) {
    const needs = F.describe(skill.inputSchema, { max: 5 });
    const tags = (skill.tags || [])
      .map(function (t) { return `<span class="sk-tag">${U.esc(t)}</span>`; })
      .join("");
    return (
      `<div class="sk-detail-head">` +
      avatar(skill, "lg") +
      `<div class="sk-detail-title">` +
      `<h2 class="sk-h2">${U.esc(skill.name)}</h2>` +
      `<span class="sk-card-cat">${U.esc(skill.cat)}</span>` +
      `</div>` +
      (skill.requires.indexOf("llm") !== -1
        ? `<span class="badge badge-warn">需要密钥</span>`
        : `<span class="badge badge-ok">本地计算</span>`) +
      `</div>` +
      `<p class="sk-detail-desc">${U.esc(skill.desc)}</p>` +
      (tags ? `<div class="sk-card-tags">${tags}</div>` : "") +
      (needs
        ? `<p class="field-help mt-3">你需要准备：<strong>${U.esc(needs)}</strong></p>`
        : "") +
      (state.batch && skill.key === "competitor_analysis"
        ? `<div class="callout callout-info mt-3">${U.icon("info")}<div>已带入刚才校验通过的那批数据。</div></div>`
        : "") +
      `<form id="sk-form" class="mt-4" autocomplete="off">` +
      F.render(skill.inputSchema, {}) +
      `</form>` +
      // 结果区放在运行条之前：运行条是吸底的，结果放在它后面就会被压在视口外，
      // 用户点了「运行」却看不到刚跑出来的东西。
      `<div class="sk-result" id="sk-result"></div>` +
      `<div class="sk-run-bar">` +
      `<button type="button" class="btn btn-primary btn-sm" id="sk-run">${U.icon("play")}运行</button>` +
      `<span class="t-xs t-muted" id="sk-hint">${
        skill.requires.indexOf("llm") !== -1 ? "这一步会调用你自己的模型密钥" : "全部本地计算，不调用模型"
      }</span>` +
      `</div>`
    );
  }

  function paintDetail(root, skill) {
    root.innerHTML =
      `<div class="view"><div class="page"><div class="page-inner">` +
      `<a class="sk-back" href="/skills" data-link>${U.icon("chevronLeft")}技能广场</a>` +
      `<section class="sk-detail" id="sk-detail">${detailHtml(skill)}</section>` +
      `</div></div></div>`;

    window.CPIcon.hydrate(root);

    const runBtn = root.querySelector("#sk-run");
    if (runBtn) runBtn.addEventListener("click", function () { submit(root); });

    bindFile(root);
    F.hydratePickers(root.querySelector("#sk-detail"));

    if (state.result) renderResult(root, outputHtml(skill, state.result));
    else if (state.error) renderError(root, state.error);
  }

  /* ---------------- 文件选择：当场读成 base64 ----------------
   * 不做二次上传接口：/api/import 已经把「上传 + 列映射」做完整了，
   * 技能这边只需要把内容交给 executor。 */

  function bindFile(root) {
    const input = root.querySelector('input[type="file"][data-path]');
    if (!input) return;
    input.addEventListener("change", function () {
      const file = input.files && input.files[0];
      if (!file) return;
      const label = root.querySelector("[data-file-name]");
      if (file.size > 5 * 1024 * 1024) {
        input.value = "";
        if (label) label.textContent = "文件超过 5 MB，请拆分后再试";
        return;
      }
      const reader = new FileReader();
      reader.onload = function () {
        const result = String(reader.result || "");
        input.setAttribute("data-base64", result.split(",")[1] || "");
        input.setAttribute("data-filename", file.name);
        if (label) label.textContent = `已选择：${file.name}`;
      };
      reader.readAsDataURL(file);
    });
  }

  /* ---------------- 运行 ---------------- */

  async function submit(root) {
    if (state.running) return;
    const skill = C.skillByKey(state.key);
    const form = root.querySelector("#sk-form");

    clearFieldErrors(root);
    let payload;
    try {
      payload = F.read(form, skill.inputSchema);
    } catch (err) {
      applyFieldErrors(root, [{ field: err.field, message: err.message }]);
      return;
    }
    if (state.batch && skill.key === "competitor_analysis") {
      payload.import_batch_id = state.batch;
    }

    state.running = true;
    state.result = null;
    state.error = "";
    state.needKey = false;
    state.steps = [];
    setBusy(root, true);
    renderResult(root, `<div class="sk-loading">${U.icon("clock")}<span>正在运行…</span></div>`, { reveal: true });

    try {
      if (SLOW[skill.key]) {
        const res = await A.post(`/api/skills/${encodeURIComponent(skill.key)}/run?async_run=true`, payload);
        state.taskId = res.task_id;
        startPolling(root, skill, res.task_id);
        return;
      }
      const res = await A.post(`/api/skills/${encodeURIComponent(skill.key)}/run`, payload);
      state.result = res;
      state.running = false;
      setBusy(root, false);
      renderResult(root, outputHtml(skill, res), { reveal: true });
    } catch (err) {
      state.running = false;
      setBusy(root, false);
      handleError(root, err);
    }
  }

  function startPolling(root, skill, taskId) {
    state.poller = AR.poller({
      taskId: taskId,
      onUpdate: function (detail) {
        state.steps = detail.steps || [];
        renderResult(
          root,
          `<div class="sk-loading">${U.icon("clock")}<span>正在运行…</span></div>` +
            AR.stepList(state.steps, []) +
            cancelRow()
        );
        bindCancel(root, taskId);
      },
      onDone: function (detail) {
        state.running = false;
        setBusy(root, false);
        const task = detail.task || {};
        if (task.status === "succeeded") {
          const sk = detail.result.skill || {};
          const output = sk.output || detail.result.report || detail.result.listing || {};
          state.result = {
            output: output,
            is_demo: Boolean(sk.is_demo),
            result_ref: sk.result_ref,
            task_id: taskId,
          };
          state.steps = detail.steps || [];
          renderResult(root, outputHtml(skill, state.result), { reveal: true });
          return;
        }
        const message = task.error_message || "这次运行没有完成，可以重试一次";
        state.error = message;
        renderResult(
          root,
          `<div class="callout callout-danger">${U.icon("alert")}<div>${U.esc(message)}</div></div>`,
          { reveal: true }
        );
      },
      onError: function (err) {
        state.running = false;
        setBusy(root, false);
        renderResult(
          root,
          `<div class="callout callout-danger">${U.icon("alert")}<div>${U.esc(err.message || "任务状态读取失败")}</div></div>`,
          { reveal: true }
        );
      },
    });
  }

  function cancelRow() {
    return (
      `<div class="row gap-2 mt-2">` +
      `<button type="button" class="btn btn-sm" id="sk-cancel">取消运行</button></div>`
    );
  }

  function bindCancel(root, taskId) {
    const btn = root.querySelector("#sk-cancel");
    if (!btn || btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", async function () {
      btn.disabled = true;
      try {
        await AR.cancel(taskId);
        U.toast("已请求取消", "info");
      } catch (err) {
        btn.disabled = false;
        U.toast(err.message, "danger");
      }
    });
  }

  function setBusy(root, busy) {
    const btn = root.querySelector("#sk-run");
    if (btn) {
      btn.disabled = busy;
      btn.innerHTML = busy ? `${U.icon("clock")}运行中…` : `${U.icon("play")}运行`;
    }
  }

  function renderResult(root, html, opts) {
    const host = root.querySelector("#sk-result");
    if (!host) return;
    host.innerHTML = html;
    window.CPIcon.hydrate(host);
    const skill = C.skillByKey(state.key);
    if (state.result && skill) paintChart(host, skill, state.result);
    // 参数多的能力表单很长，结果默认落在折叠线以下。
    // 用户在顶部点「运行」，不滚一下根本看不到结果（尤其失败提示）。
    if (opts && opts.reveal) {
      const box = host.getBoundingClientRect();
      if (box.top > window.innerHeight - 80 || box.bottom < 0) {
        host.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }
  }

  function renderError(root, message) {
    renderResult(
      root,
      `<div class="callout callout-danger">${U.icon("alert")}<div>${U.esc(message)}</div></div>`,
      { reveal: true }
    );
  }

  /* ---------------- 错误呈现 ---------------- */

  function handleError(root, err) {
    const detail = err.detail || {};

    if (err.status === 428) {
      state.needKey = true;
      renderResult(
        root,
        `<div class="callout callout-warn">${U.icon("alert")}<div>` +
          `<strong>这一步需要你自己的模型密钥</strong><br>${U.esc(err.message)}` +
          `<div class="row gap-2 mt-2"><a class="btn btn-primary btn-sm" href="/settings" data-link>` +
          `${U.icon("settings")}去配置 API Key</a></div></div></div>`,
        { reveal: true }
      );
      window.CPIcon.hydrate(root);
      return;
    }

    if (err.status === 422 && Array.isArray(detail.errors) && detail.errors.length) {
      applyFieldErrors(root, detail.errors);
      renderResult(
        root,
        `<div class="callout callout-warn">${U.icon("alert")}<div>${U.esc(
          detail.message || "有几处需要修正"
        )}</div></div>`,
        { reveal: true }
      );
      return;
    }

    renderError(root, err.message || "这次运行没有完成");
  }

  function clearFieldErrors(root) {
    root.querySelectorAll(".is-invalid").forEach(function (el) {
      el.classList.remove("is-invalid");
    });
    root.querySelectorAll(".field-error").forEach(function (el) {
      el.remove();
    });
  }

  /* 服务端回的是中文标签（"商品名称"），表单上也是中文标签，按标签文本对上即可 */
  function applyFieldErrors(root, errors) {
    errors.slice(0, 6).forEach(function (err) {
      const wanted = String(err.field || "").split(" · ")[0].trim();
      if (!wanted) return;
      const holders = Array.prototype.slice.call(root.querySelectorAll("[data-holder]"));
      const holder = holders.filter(function (el) {
        const label = el.querySelector(".field-label");
        return label && label.textContent.replace("*", "").trim().indexOf(wanted) === 0;
      })[0];
      if (!holder) return;
      holder.classList.add("is-invalid");
      const tip = document.createElement("span");
      tip.className = "field-error";
      tip.textContent = err.message || "这一格需要修正";
      holder.appendChild(tip);
    });
  }

  /* ---------------- 结果渲染 ---------------- */

  function demoBanner(isDemo) {
    if (!isDemo) return "";
    return (
      `<div class="callout callout-warn mb-3">${U.icon("alert")}` +
      `<div><strong>示例数据</strong><br>这份结果基于示例数据，不能用于真实经营决策。</div></div>`
    );
  }

  function outputHtml(skill, payload) {
    const out = payload.output || {};
    const demo = demoBanner(payload.is_demo);

    if (skill.key === "competitor_analysis") return demo + R.renderReport(out, {});
    if (skill.key === "listing_generation") return demo + R.renderListing(out, {});
    if (skill.key === "market_summary") return demo + summaryBlock(out);
    if (skill.key === "review_mining") return demo + miningBlock(out);
    if (skill.key === "listing_quality") return demo + qualityBlock(out);
    if (skill.key === "data_validation") return validationBlock(out);
    if (skill.key === "profit_calc") return profitBlock(out);
    return demo;
  }

  function summaryBlock(out) {
    const points = (out.points || [])
      .map(function (p) {
        return `<li>${U.esc(p.text)}${R.kindBadge ? R.kindBadge(p.evidence_kind) : ""}</li>`;
      })
      .join("");
    return (
      `<div class="card card-pad"><div class="card-title">${U.esc(out.headline || "市场机会判断")}</div>` +
      `<ul class="sk-bullets mt-3">${points || "<li>这份报告里没有可用于归纳的结论。</li>"}</ul>` +
      ((out.limitations || []).length
        ? `<p class="t-xs t-muted mt-3">局限：${U.esc((out.limitations || []).join("；"))}</p>`
        : "") +
      `</div>`
    );
  }

  function miningBlock(out) {
    const sections = [
      { title: "痛点", rows: out.pain_points || [], withShare: true },
      { title: "需求", rows: out.needs || [], withShare: false },
      { title: "购买顾虑", rows: out.concerns || [], withShare: false },
    ];
    return sections
      .map(function (sec) {
        const rows = sec.rows
          .map(function (r) {
            const share =
              sec.withShare && r.share !== undefined && r.share !== null
                ? `<td class="num">${Math.round(r.share * 1000) / 10}%</td>`
                : sec.withShare
                ? `<td class="num">—</td>`
                : "";
            return `<tr><td>${U.esc(r.label)}</td><td class="num">${r.frequency || 0}</td>${share}</tr>`;
          })
          .join("");
        return (
          `<div class="card mb-3"><div class="table-wrap"><table class="table">` +
          `<thead><tr><th>${U.esc(sec.title)}</th><th class="num">出现次数</th>` +
          (sec.withShare ? `<th class="num">占比</th>` : "") +
          `</tr></thead><tbody>${rows || `<tr><td colspan="${
            sec.withShare ? 3 : 2
          }" class="t-muted">这份报告里没有这一类样本。</td></tr>`}</tbody></table></div></div>`
        );
      })
      .join("") +
      `<p class="t-xs t-muted">共 ${out.total_samples || 0} 条评论样本，其中 ${
        out.with_rating || 0
      } 条带星级。</p>`;
  }

  function qualityBlock(out) {
    const row = function (text, tone) {
      return `<li><span class="badge ${tone || ""}">${
        tone === "badge-danger" ? "必须改" : tone === "badge-warn" ? "建议改" : "待确认"
      }</span> ${U.esc(text)}</li>`;
    };
    const errors = (out.errors || []).map(function (t) { return row(t, "badge-danger"); });
    const warnings = (out.warnings || []).map(function (t) { return row(t, "badge-warn"); });
    const pending = (out.pending_confirmations || []).map(function (t) { return row(t, ""); });
    const all = errors.concat(warnings).concat(pending);
    return (
      `<div class="card card-pad"><div class="row between">` +
      `<div class="card-title">检查结果</div>` +
      `<span class="badge ${out.passed ? "badge-ok" : "badge-danger"}">${
        out.passed ? "通过" : "需要处理"
      }</span></div>` +
      (all.length
        ? `<ul class="sk-bullets mt-3">${all.join("")}</ul>`
        : `<p class="t-sm t-soft mt-2">没有发现需要修改的地方。</p>`) +
      (out.policy_disclaimer ? `<p class="t-xs t-muted mt-3">${U.esc(out.policy_disclaimer)}</p>` : "") +
      `</div>`
    );
  }

  function validationBlock(out) {
    const errors = out.errors || [];
    const rows = errors
      .map(function (e) {
        return `<tr><td class="num">${e.row || "—"}</td><td>${U.esc(e.field || "")}</td><td>${U.esc(
          e.message || ""
        )}</td></tr>`;
      })
      .join("");
    const preview = (out.preview || [])
      .map(function (c) {
        return `<tr><td>${U.esc(c.name || "")}</td><td class="num">${
          c.price === null || c.price === undefined ? "—" : c.price
        }</td><td class="num">${c.rating === null || c.rating === undefined ? "—" : c.rating}</td></tr>`;
      })
      .join("");

    return (
      `<div class="card card-pad mb-3"><div class="row between">` +
      `<div class="card-title">${out.ok ? "校验通过" : "有需要修正的行"}</div>` +
      `<span class="badge ${out.ok ? "badge-ok" : "badge-warn"}">共 ${out.total_rows || 0} 行 · 有效 ${
        out.valid_rows || 0
      } 行</span></div>` +
      (errors.length
        ? `<div class="table-wrap mt-3"><table class="table"><thead><tr>` +
          `<th class="num">行</th><th>字段</th><th>问题</th></tr></thead><tbody>${rows}</tbody></table></div>`
        : `<p class="t-sm t-soft mt-2">每一行都通过了字段检查。</p>`) +
      ((out.warnings || []).length
        ? `<p class="t-xs t-muted mt-3">${U.esc((out.warnings || []).join("；"))}</p>`
        : "") +
      `</div>` +
      (preview
        ? `<div class="card"><div class="table-wrap"><table class="table"><thead><tr>` +
          `<th>预览（前 5 个竞品）</th><th class="num">价格</th><th class="num">评分</th>` +
          `</tr></thead><tbody>${preview}</tbody></table></div></div>`
        : "") +
      (out.batch_id
        ? `<div class="row gap-2 mt-3"><a class="btn btn-sm" href="/skills?skill=competitor_analysis&batch=${U.esc(
            out.batch_id
          )}" data-link>用这批数据做竞品分析</a>` +
          `<a class="btn btn-quiet btn-sm" href="/data" data-link>去数据资产查看</a></div>`
        : "")
    );
  }

  function profitBlock(out) {
    const cur = out.currency || "USD";
    const money = function (v) {
      return window.CPChart ? window.CPChart.money(v, cur) : `${v} ${cur}`;
    };
    const kpi = function (label, value, hint) {
      return (
        `<div class="sk-kpi"><span class="sk-kpi-label">${U.esc(label)}</span>` +
        `<span class="sk-kpi-value">${value}</span>` +
        (hint ? `<span class="sk-kpi-hint">${U.esc(hint)}</span>` : "") +
        `</div>`
      );
    };
    const rows = (out.cost_breakdown || [])
      .map(function (c) {
        return (
          `<tr><td>${U.esc(c.label)}</td><td class="num">${money(c.amount)}</td>` +
          `<td class="num">${Math.round((c.ratio_to_price || 0) * 1000) / 10}%</td>` +
          `<td class="t-xs t-muted">${U.esc(c.formula || "")}</td></tr>`
        );
      })
      .join("");

    return (
      `<div class="card card-pad mb-3">` +
      `<div class="sk-kpis">` +
      kpi("单件售价", money(out.selling_price)) +
      kpi("单件总成本", money(out.total_cost)) +
      kpi("单件毛利", money(out.unit_profit)) +
      kpi("毛利率", `${Math.round((out.margin || 0) * 1000) / 10}%`) +
      `</div>` +
      `<div class="chart" data-chart="cost" style="margin-top:var(--sp-4)"></div>` +
      `</div>` +
      `<div class="card mb-3"><div class="table-wrap"><table class="table"><thead><tr>` +
      `<th>成本项</th><th class="num">金额</th><th class="num">占售价比</th><th>口径</th>` +
      `</tr></thead><tbody>${rows}</tbody></table></div></div>` +
      `<div class="card card-pad">` +
      `<div class="sk-kpis">` +
      kpi("保本价", out.break_even_price === null ? "—" : money(out.break_even_price)) +
      kpi("建议价", out.recommended_price === null ? "—" : money(out.recommended_price)) +
      kpi(
        "可接受区间",
        out.price_floor === null || out.price_ceiling === null
          ? "—"
          : `${money(out.price_floor)} – ${money(out.price_ceiling)}`
      ) +
      `</div>` +
      ((out.warnings || []).length
        ? `<p class="t-xs t-muted mt-3">${U.esc((out.warnings || []).join("；"))}</p>`
        : "") +
      `</div>`
    );
  }

  function paintChart(host, skill, payload) {
    if (skill.key !== "profit_calc" || !window.CPChart) return;
    const target = host.querySelector('[data-chart="cost"]');
    if (!target) return;
    const out = payload.output || {};
    const series = (out.cost_breakdown || []).map(function (c) {
      return { label: c.label, value: c.amount };
    });
    window.CPChart.bars(target, {
      series: series,
      categories: true,
      label: "成本构成",
      format: "number",
      height: 168,
    });
  }

  /* ==========================================================================
     入口
     ========================================================================== */

  async function render(root, params, query) {
    query = query || {};
    reset();
    root.innerHTML =
      `<div class="view"><div class="page"><div class="page-inner">` +
      `<div class="skeleton skeleton-line" style="height:180px"></div></div></div></div>`;

    state.skills = await C.ensureSkills();
    if (!state.skills.length) {
      const err = C.skillLoadError();
      // 这里不能走 renderError：它写入的是 #sk-result，此时页面骨架还没画，会一片空白。
      root.innerHTML =
        `<div class="view"><div class="page"><div class="page-inner">` +
        `<div class="page-head"><div><h1 class="page-title">技能广场</h1></div></div>` +
        `<div class="callout callout-warn">${U.icon("alert")}<div>` +
        (err ? "技能列表暂时读不出来，刷新一下再试。" : "暂时没有可以运行的能力。") +
        `</div></div></div></div></div>`;
      window.CPIcon.hydrate(root);
      return;
    }

    state.batch = String(query.batch || "");
    const wanted = String(query.skill || "");

    if (wanted && C.skillByKey(wanted)) {
      state.key = wanted;
      paintDetail(root, C.skillByKey(wanted));
      return;
    }
    paintGrid(root);
  }

  window.CPPageSkills = { render };
})();
