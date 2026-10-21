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

  function parseJson(text, label) {
    const raw = String(text || "").trim();
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) throw new Error(label + "必须是 JSON 数组");
      return parsed;
    } catch (err) {
      throw new Error(label + "解析失败：" + err.message);
    }
  }

  function formHtml() {
    return (
      `<form id="cmp-form" class="card card-pad">` +
      `<div class="row between"><div><div class="card-title">分析输入</div>` +
      `<div class="card-sub">资料只用于本次分析，不会外发</div></div>` +
      `<span class="t-xs t-muted"><span class="t-danger">*</span> 必填</span></div>` +

      `<div class="grid-2 mt-4">` +
      `<label class="field field-span-2"><span class="field-label">商品名称 <span class="t-danger">*</span></span>` +
      `<input name="product_name" required placeholder="例如 EcoSip Insulated Water Bottle" /></label>` +
      `<label class="field"><span class="field-label">平台</span>` +
      `<select name="platform">` +
      ["amazon", "ebay", "walmart", "shopee", "mercadolibre"].map(function (p) {
        return `<option value="${p}">${p}</option>`;
      }).join("") + `</select></label>` +
      `<label class="field"><span class="field-label">站点</span>` +
      `<input name="marketplace" value="US" /></label>` +
      `<label class="field"><span class="field-label">类目</span>` +
      `<input name="category" placeholder="可选" /></label>` +
      `<label class="field"><span class="field-label">自有价格</span>` +
      `<input name="own_price" type="number" min="0" step="0.01" placeholder="可选" /></label>` +
      `</div>` +

      `<label class="field mt-3"><span class="field-label">自有规格（每行「键: 值」）</span>` +
      `<textarea name="own_specs" rows="3" spellcheck="false" placeholder="容量: 750ml&#10;材质: 304 不锈钢"></textarea>` +
      `<span class="field-help">未填写的规格不会出现在报告中，也不会被自动补全。</span></label>` +

      `<label class="field"><span class="field-label">自有卖点（每行一条）</span>` +
      `<textarea name="own_key_features" rows="2" placeholder="双层真空保温"></textarea></label>` +

      `<label class="field"><span class="field-label">竞品数据（JSON 数组）<span class="t-danger">*</span></span>` +
      `<textarea name="competitors" rows="7" spellcheck="false" required ` +
      `placeholder='[{"name":"竞品 A","price":25.99,"is_demo":false,"reviews":[{"rating":2,"text":"lid leaked"}]}]'></textarea>` +
      `<span class="field-help">必填 <code>name</code>；可选 price / rating / reviews / is_demo。</span></label>` +

      `<label class="field"><span class="field-label">关键词（JSON 数组，可选）</span>` +
      `<textarea name="keywords" rows="2" spellcheck="false" ` +
      `placeholder='[{"keyword":"insulated bottle","search_volume":12000,"rank":8}]'></textarea>` +
      `<span class="field-help">缺少搜索量或排名时不计算机会分。</span></label>` +

      `<p class="callout callout-danger" id="cmp-error" hidden></p>` +
      `<div class="row gap-2 mt-3">` +
      `<button type="submit" class="btn btn-primary">开始分析</button>` +
      `<button type="button" class="btn" id="cmp-demo">载入示例数据</button>` +
      `</div></form>`
    );
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

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      error.hidden = true;
      let payload;
      try {
        payload = buildPayload(form);
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
        form.competitors.value = JSON.stringify(req.competitors || [], null, 2);
        form.keywords.value = JSON.stringify(req.keywords || [], null, 2);
        U.toast("已载入示例数据（虚构，仅用于体验流程）", "ok");
      } catch (err) {
        U.toast(err.message, "danger");
      }
    });

    if (query && query.report) await loadReport(result, query.report);
  }

  function buildPayload(form) {
    const competitors = parseJson(form.competitors.value, "竞品数据");
    if (!competitors.length) throw new Error("至少需要 1 个竞品");
    const keywords = parseJson(form.keywords.value, "关键词");
    const price = form.own_price.value.trim();
    return {
      product_name: form.product_name.value.trim(),
      platform: form.platform.value,
      marketplace: (form.marketplace.value || "US").trim().toUpperCase(),
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
              return `<li><code>${U.esc(e.field || "")}</code> ${U.esc(e.message || "")}</li>`;
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
      `<div class="card-sub">任务 ${U.esc(String(taskId).slice(0, 10))} · 进度来自真实执行步骤</div></div>` +
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
