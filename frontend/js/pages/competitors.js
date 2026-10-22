/* 激浪 · 竞品分析（真实接口 /api/analyze） */
(function () {
  "use strict";
  const U = window.CPUi;
  const A = window.CPApi;
  const R = window.CPRender;

  function specToLines(specs) {
    return Object.keys(specs || {}).map(function (k) { return k + ": " + specs[k]; }).join("\n");
  }

  function parseSpecs(text) {
    const out = {};
    String(text || "").split(/\r?\n/).forEach(function (line) {
      const idx = line.indexOf(":");
      if (idx > 0) {
        const key = line.slice(0, idx).trim();
        const value = line.slice(idx + 1).trim();
        if (key && value) out[key] = value;
      }
    });
    return out;
  }

  /* 平台与站点：接口要代码，界面给人看的名字 */
  const PLATFORMS = [
    { value: "amazon", label: "Amazon" },
    { value: "ebay", label: "eBay" },
    { value: "walmart", label: "Walmart" },
    { value: "shopee", label: "Shopee" },
    { value: "mercadolibre", label: "Mercado Libre" },
  ];

  function competitorRow(title, data) {
    const d = data || {};
    const price = d.price === null || d.price === undefined ? "" : d.price;
    const rating = d.rating === null || d.rating === undefined ? "" : d.rating;
    const count = d.review_count === null || d.review_count === undefined ? "" : d.review_count;
    const review = Array.isArray(d.reviews) && d.reviews[0] ? (d.reviews[0].text || "") : "";
    return (
      `<div class="cmp-item" data-cmp data-demo="${d.is_demo ? "1" : ""}">` +
      `<div class="row between"><span class="t-xs t-muted" data-cmp-title>${title}</span>` +
      `<button type="button" class="btn-icon" data-cmp-remove aria-label="删除这个竞品">${U.icon("close")}</button></div>` +
      `<div class="grid-2 mt-2">` +
      `<label class="field"><span class="field-label">名称 <span class="t-danger">*</span></span>` +
      `<input data-f="name" value="${U.esc(d.name || "")}" placeholder="竞品标题" /></label>` +
      `<label class="field"><span class="field-label">价格</span>` +
      `<input data-f="price" type="number" min="0" step="0.01" value="${U.esc(price)}" placeholder="可选" /></label>` +
      `<label class="field"><span class="field-label">评分</span>` +
      `<input data-f="rating" type="number" min="0" max="5" step="0.1" value="${U.esc(rating)}" placeholder="0–5" /></label>` +
      `<label class="field"><span class="field-label">评论数</span>` +
      `<input data-f="review_count" type="number" min="0" value="${U.esc(count)}" placeholder="可选" /></label>` +
      `</div>` +
      `<label class="field mt-2"><span class="field-label">一条真实评论</span>` +
      `<textarea data-f="review" rows="2" placeholder="差评更有用，比如：盖子漏水">${U.esc(review)}</textarea></label>` +
      `</div>`
    );
  }

  function formHtml() {
    return (
      `<form id="cmp-form" class="card card-pad">` +
      `<div class="row between"><div><div class="card-title">分析输入</div>` +
      `<div class="card-sub">资料只用于本次分析，不会外发</div></div>` +
      `<span class="t-xs t-muted"><span class="t-danger">*</span> 必填</span></div>` +

      `<div class="grid-2 mt-4">` +
      `<label class="field field-span-2"><span class="field-label">你的商品名称 <span class="t-danger">*</span></span>` +
      `<input name="product_name" required placeholder="例如 EcoSip Insulated Water Bottle" /></label>` +
      `<label class="field"><span class="field-label">平台</span>` +
      `<select name="platform">` +
      PLATFORMS.map(function (p) {
        return `<option value="${p.value}">${p.label}</option>`;
      }).join("") + `</select></label>` +
      `<label class="field"><span class="field-label">站点</span>` +
      `<select name="marketplace">` +
      Object.keys(window.CPLabel.SITE).map(function (code) {
        return `<option value="${code}">${window.CPLabel.site(code)}</option>`;
      }).join("") + `</select></label>` +
      `<label class="field"><span class="field-label">类目</span>` +
      `<input name="category" placeholder="可选" /></label>` +
      `<label class="field"><span class="field-label">你的价格</span>` +
      `<input name="own_price" type="number" min="0" step="0.01" placeholder="可选" /></label>` +
      `</div>` +

      `<label class="field mt-3"><span class="field-label">你的规格（每行「键: 值」）</span>` +
      `<textarea name="own_specs" rows="3" spellcheck="false" placeholder="容量: 750ml&#10;材质: 304 不锈钢"></textarea>` +
      `<span class="field-help">没填的规格不会出现在报告里，也不会被自动补全。</span></label>` +

      `<label class="field"><span class="field-label">你的卖点（每行一条）</span>` +
      `<textarea name="own_key_features" rows="2" placeholder="双层真空保温"></textarea></label>` +

      `<div class="field mt-3"><span class="field-label">竞品 <span class="t-danger">*</span></span>` +
      `<div id="cmp-list"></div>` +
      `<div class="row gap-2 mt-2">` +
      `<button type="button" class="btn btn-sm" id="cmp-add">${U.icon("plus")}添加竞品</button>` +
      `<a class="btn btn-sm" href="/data" data-link>从文件导入</a></div>` +
      `<span class="field-help">至少 1 个。写清名称就能分析；价格、评分与评论填得越多，结论越准。</span></div>` +

      `<label class="field mt-3"><span class="field-label">关键词（每行一个，可选）</span>` +
      `<textarea name="keywords" rows="3" spellcheck="false" ` +
      `placeholder="insulated bottle&#10;water bottle 32oz | 12000 | 8"></textarea>` +
      `<span class="field-help">想算机会分就按「关键词 | 搜索量 | 排名」写，只写关键词也可以。</span></label>` +

      `<p class="callout callout-danger" id="cmp-error" hidden></p>` +
      `<div class="row gap-2 mt-3">` +
      `<button type="submit" class="btn btn-primary">开始分析</button>` +
      `<button type="button" class="btn" id="cmp-demo">载入示例数据</button>` +
      `</div></form>`
    );
  }

  /* ---- 竞品行：增删与取值 ---- */
  function renumber(list) {
    list.querySelectorAll("[data-cmp]").forEach(function (node, index) {
      const title = node.querySelector("[data-cmp-title]");
      if (title) title.textContent = `竞品 ${index + 1}`;
    });
  }

  function addRow(list, data) {
    const holder = document.createElement("div");
    holder.innerHTML = competitorRow(`竞品 ${list.children.length + 1}`, data);
    const node = holder.firstElementChild;
    list.appendChild(node);
    window.CPIcon.hydrate(node);
    renumber(list);
    return node;
  }

  function fieldValue(node, name) {
    const input = node.querySelector(`[data-f="${name}"]`);
    return input ? input.value.trim() : "";
  }

  function collectCompetitors(list) {
    const items = [];
    list.querySelectorAll("[data-cmp]").forEach(function (node) {
      const name = fieldValue(node, "name");
      if (!name) return;
      const item = { name, is_demo: node.getAttribute("data-demo") === "1" };
      const price = fieldValue(node, "price");
      if (price !== "") item.price = Number(price);
      const rating = fieldValue(node, "rating");
      if (rating !== "") item.rating = Number(rating);
      const count = fieldValue(node, "review_count");
      if (count !== "") item.review_count = Number(count);
      const text = fieldValue(node, "review");
      if (text) {
        const review = { text };
        if (rating !== "" && Number(rating) >= 1) review.rating = Number(rating);
        item.reviews = [review];
      }
      items.push(item);
    });
    return items;
  }

  /* 关键词：「词 | 搜索量 | 排名」，只写词也行 */
  function collectKeywords(text) {
    return String(text || "")
      .split(/\r?\n/)
      .map(function (line) { return line.trim(); })
      .filter(Boolean)
      .map(function (line) {
        const parts = line.split("|").map(function (s) { return s.trim(); });
        const item = { keyword: parts[0] };
        if (parts[1] && !isNaN(Number(parts[1]))) item.search_volume = Number(parts[1]);
        if (parts[2] && !isNaN(Number(parts[2]))) item.rank = Number(parts[2]);
        return item;
      })
      .filter(function (k) { return k.keyword; });
  }

  async function render(root, params, query) {
    root.innerHTML = `<div class="view"><div class="page"><div class="page-inner">` +
      `<div class="page-head"><div><h1 class="page-title">竞品分析</h1>` +
      `<p class="page-desc">汇总竞品价格、评论与关键词，输出带证据来源的结论。分析与 AI 工作台调用同一个入口。</p></div>` +
      `</div>` +
      `<div class="cmp-layout"><div>${formHtml()}</div>` +
      `<div id="cmp-result">${emptyResult()}</div></div>` +
      `</div></div></div>`;
    window.CPIcon.hydrate(root);

    const form = root.querySelector("#cmp-form");
    const result = root.querySelector("#cmp-result");
    const error = root.querySelector("#cmp-error");
    const list = root.querySelector("#cmp-list");

    addRow(list);

    root.querySelector("#cmp-add").addEventListener("click", function () {
      const node = addRow(list);
      const input = node.querySelector('[data-f="name"]');
      if (input) input.focus();
    });

    list.addEventListener("click", function (event) {
      const remove = event.target.closest("[data-cmp-remove]");
      if (!remove) return;
      const node = remove.closest("[data-cmp]");
      // 至少留一行，否则用户会以为表单坏了
      if (list.querySelectorAll("[data-cmp]").length <= 1) {
        node.querySelectorAll("input, textarea").forEach(function (el) { el.value = ""; });
        node.setAttribute("data-demo", "");
        U.toast("至少保留一个竞品", "warn");
        return;
      }
      node.remove();
      renumber(list);
    });

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      error.hidden = true;
      let payload;
      try {
        payload = buildPayload(form, list);
      } catch (err) {
        error.hidden = false;
        error.textContent = err.message;
        return;
      }
      await run(root, result, payload, form);
    });

    root.querySelector("#cmp-demo").addEventListener("click", async function () {
      try {
        const demo = await A.get("/api/demo/dataset");
        const req = demo.analysis_request || {};
        form.product_name.value = req.product_name || "";
        form.platform.value = req.platform || "amazon";
        form.marketplace.value = req.marketplace || "US";
        form.category.value = req.category || "";
        form.own_price.value = req.own_price !== undefined && req.own_price !== null ? req.own_price : "";
        form.own_specs.value = specToLines(req.own_specs);
        form.own_key_features.value = (req.own_key_features || []).join("\n");
        list.innerHTML = "";
        (req.competitors || []).forEach(function (c) { addRow(list, c); });
        if (!list.children.length) addRow(list);
        form.keywords.value = (req.keywords || []).map(function (k) {
          const parts = [k.keyword];
          if (k.search_volume !== undefined && k.search_volume !== null) parts.push(k.search_volume);
          if (k.rank !== undefined && k.rank !== null) parts.push(k.rank);
          return parts.join(" | ");
        }).join("\n");
        U.toast("已载入示例数据（虚构，只用来体验流程）", "ok");
      } catch (err) {
        U.toast(err.message, "danger");
      }
    });

    if (query && query.report) await loadReport(result, query.report);
  }

  function buildPayload(form, list) {
    const competitors = collectCompetitors(list);
    if (!competitors.length) throw new Error("至少填一个竞品的名称");
    const keywords = collectKeywords(form.keywords.value);
    const price = form.own_price.value.trim();
    return {
      product_name: form.product_name.value.trim(),
      platform: form.platform.value,
      marketplace: form.marketplace.value || "US",
      category: form.category.value.trim() || null,
      own_specs: parseSpecs(form.own_specs.value),
      own_key_features: form.own_key_features.value.split(/\r?\n/).map(function (s) { return s.trim(); }).filter(Boolean),
      own_price: price ? Number(price) : null,
      competitors,
      keywords,
      data_source: "manual",
      locale: "zh-CN",
    };
  }

  async function run(root, result, payload, form) {
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = "提交中…";
    result.innerHTML = `<div class="card card-pad"><div class="row gap-2">` +
      `<span class="badge badge-running">排队中</span><span class="t-sm t-muted">正在创建任务…</span></div>` +
      `<div class="skeleton skeleton-line mt-4"></div><div class="skeleton skeleton-line"></div></div>`;
    try {
      // 统一异步：提交立即返回 task_id，步骤来自真实 task_steps
      const run = await A.post("/api/analyze?async_run=true", payload);
      renderProgress(result, run.task_id, run.plan || []);
      button.disabled = false;
      button.textContent = "开始分析";
    } catch (err) {
      result.innerHTML = `<div class="card card-pad"><div class="callout callout-danger">${U.icon("alert")}` +
        `<div><strong>分析失败</strong><br>${U.esc(err.message)}</div></div>` +
        (err.detail && err.detail.errors
          ? `<ul class="limit-list mt-2">` + err.detail.errors.map(function (e) {
              return `<li>${U.esc(e.field || "")}：${U.esc(e.message || "")}</li>`;
            }).join("") + `</ul>`
          : "") + `</div>`;
      button.disabled = false;
      button.textContent = "开始分析";
    }
  }

  /* 真实步骤进度：不伪造百分比，只显示步骤状态 */
  function renderProgress(container, taskId, plan) {
    const AR = window.CPAsyncRun;
    container.innerHTML = `<div class="card card-pad">` +
      `<div class="row between wrap gap-2"><div><div class="card-title">正在分析</div>` +
      `<div class="card-sub">进度来自真实的执行步骤</div></div>` +
      `<button type="button" class="btn btn-sm" id="cmp-cancel">取消</button></div>` +
      `<div class="progress is-indeterminate mt-3"><div class="progress-bar"></div></div>` +
      `<div class="mt-3" id="cmp-steps"></div></div>`;
    window.CPIcon.hydrate(container);

    const stepsBox = container.querySelector("#cmp-steps");
    stepsBox.innerHTML = AR.stepList([], plan);

    const poller = AR.poller({
      taskId: taskId,
      onUpdate: function (detail) {
        stepsBox.innerHTML = AR.stepList(detail.steps || [], plan);
      },
      onDone: function (detail) {
        const task = detail.task || {};
        const report = (detail.result || {}).report;
        if (task.status === "succeeded" && report) {
          renderReport(container, report, taskId);
          U.toast("分析完成，报告已保存", "ok");
        } else if (task.status === "cancelled") {
          container.innerHTML = `<div class="card card-pad"><div class="callout callout-warn">${U.icon("info")}` +
            `<div>任务已取消，未生成报告。</div></div></div>`;
        } else {
          container.innerHTML = `<div class="card card-pad"><div class="callout callout-danger">${U.icon("alert")}` +
            `<div><strong>分析失败</strong><br>${U.esc(task.error_message || "未知错误")}</div></div></div>`;
        }
      },
      onError: function (err) {
        container.innerHTML = `<div class="card card-pad"><div class="callout callout-danger">${U.icon("alert")}` +
          `<div>进度查询失败：${U.esc(err.message)}</div></div></div>`;
      },
    });

    const cancel = container.querySelector("#cmp-cancel");
    if (cancel) {
      cancel.addEventListener("click", async function () {
        cancel.disabled = true;
        try {
          const resp = await AR.cancel(taskId);
          U.toast(resp, "ok");
        } catch (err) {
          U.toast(err.message, "danger");
          cancel.disabled = false;
        }
      });
    }
    return poller;
  }

  async function loadReport(result, reportId) {
    result.innerHTML = `<div class="card card-pad"><div class="skeleton skeleton-line"></div>` +
      `<div class="skeleton skeleton-line"></div></div>`;
    try {
      const report = await A.get(`/api/reports/${encodeURIComponent(reportId)}`);
      renderReport(result, report);
    } catch (err) {
      result.innerHTML = `<div class="card card-pad"><div class="callout callout-danger">${U.icon("alert")}` +
        `<div>报告加载失败：${U.esc(err.message)}</div></div></div>`;
    }
  }

  function renderReport(container, report, taskId) {
    const actions =
      `<div class="row gap-2">` +
      (taskId ? `<a class="btn btn-sm" href="/tasks/${U.esc(taskId)}" data-link>查看任务</a>` : "") +
      `<a class="btn btn-primary btn-sm" href="/listings?report=${U.esc(report.report_id)}" data-link>` +
      `${U.icon("listing")}用此报告生成 Listing</a></div>`;
    container.innerHTML = `<div class="card card-pad">` + R.renderReport(report, { actions }) + `</div>`;
    window.CPIcon.hydrate(container);
    bindCopy(container);
  }

  function bindCopy(scope) {
    scope.querySelectorAll("[data-copy]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        U.copy(btn.getAttribute("data-copy"), "内容");
      });
    });
  }

  function emptyResult() {
    return (
      `<div class="card"><div class="empty"><span class="empty-icon">${U.icon("competitors")}</span>` +
      `<p class="empty-title">还没有分析结果</p>` +
      `<p class="empty-desc">填写左侧商品与竞品信息后开始分析；也可以先载入示例数据体验流程。</p>` +
      `<div class="empty-actions"><a class="btn btn-sm" href="/data" data-link>导入竞品文件</a></div>` +
      `</div></div>`
    );
  }

  window.CPPageCompetitors = { render, bindCopy, renderProgress };
})();
