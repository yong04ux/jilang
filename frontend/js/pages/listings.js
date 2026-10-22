/* 激浪 · Listing 工作室（真实接口 /api/listings/*） */
(function () {
  "use strict";
  const U = window.CPUi;
  const A = window.CPApi;
  const R = window.CPRender;

  const LANGUAGES = {
    US: "en-US", CA: "en-CA", UK: "en-GB", DE: "de-DE", FR: "fr-FR",
    IT: "it-IT", ES: "es-ES", JP: "ja-JP", MX: "es-MX",
  };

  /* 站点与语言代码是内部标识，统一走 CPLabel 展示成人话 */
  const LANGUAGE_LABEL = window.CPLabel.LANGUAGE;

  function siteLabel(code) {
    return window.CPLabel.site(code);
  }

  function languageLabel(code) {
    return window.CPLabel.language(code);
  }

  /* 历史草稿可能带列表里没有的语言，补一个选项而不是把值丢掉 */
  function setFormLanguage(form, code) {
    const value = code || "en-US";
    if (!LANGUAGE_LABEL[value] && !form.language.querySelector(`option[value="${value}"]`)) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = languageLabel(value);
      form.language.appendChild(option);
    }
    form.language.value = value;
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

  function lines(text) {
    return String(text || "").split(/\r?\n/).map(function (s) { return s.trim(); }).filter(Boolean);
  }

  function formHtml(reports) {
    const options = [`<option value="">不关联</option>`].concat(
      reports.map(function (r) {
        return `<option value="${U.esc(r.report_id)}">${U.esc(r.product_name)} · ${U.esc(U.fmtTime(r.created_at))}</option>`;
      })
    ).join("");

    return (
      `<form id="lst-form" class="card card-pad">` +
      `<div class="row between"><div><div class="card-title">商品资料</div>` +
      `<div class="card-sub">未提供的属性会标记为「待确认」，不会自动编造</div></div>` +
      `<span class="t-xs t-muted"><span class="t-danger">*</span> 必填</span></div>` +

      `<div class="grid-2 mt-4">` +
      `<label class="field field-span-2"><span class="field-label">商品名称 <span class="t-danger">*</span></span>` +
      `<input name="name" required placeholder="EcoSip Insulated Water Bottle" /></label>` +
      `<label class="field"><span class="field-label">品牌</span><input name="brand" /></label>` +
      `<label class="field"><span class="field-label">站点</span>` +
      `<select name="marketplace">` +
      Object.keys(LANGUAGES).map(function (m) {
        return `<option value="${m}">${siteLabel(m)}</option>`;
      }).join("") + `</select></label>` +
      `<label class="field"><span class="field-label">目标语言</span>` +
      `<select name="language">` +
      Object.keys(LANGUAGE_LABEL).map(function (code) {
        return `<option value="${code}">${LANGUAGE_LABEL[code]}</option>`;
      }).join("") + `</select></label>` +
      `<label class="field"><span class="field-label">价格</span>` +
      `<input name="price" type="number" min="0" step="0.01" /></label>` +
      `<label class="field field-span-2"><span class="field-label">目标用户</span><input name="target_audience" /></label>` +
      `</div>` +

      `<label class="field mt-3"><span class="field-label">规格（每行「键: 值」）</span>` +
      `<textarea name="specifications" rows="4" spellcheck="false" ` +
      `placeholder="容量: 750ml&#10;材质: 304 不锈钢"></textarea>` +
      `<span class="field-help">留空即不生成相关参数，对应内容会进入「待确认」。</span></label>` +

      `<label class="field"><span class="field-label">卖点（每行一条）</span>` +
      `<textarea name="key_features" rows="3"></textarea></label>` +

      `<label class="field"><span class="field-label">认证 / 检测（每行一条）</span>` +
      `<textarea name="certifications" rows="2" placeholder="没有就留空"></textarea>` +
      `<span class="field-help">未提供的认证不会被写入文案。</span></label>` +

      `<label class="field"><span class="field-label">品牌禁用词（逗号分隔）</span>` +
      `<input name="banned_terms" placeholder="premium quality, guaranteed" /></label>` +

      `<label class="field"><span class="field-label">关联竞品分析报告</span>` +
      `<select name="analysis_report_id">${options}</select>` +
      `<span class="field-help">关联后只使用报告中的差异化方向；商品事实仍以本表单为准。</span></label>` +

      `<p class="callout callout-danger" id="lst-error" hidden></p>` +
      `<div class="row gap-2 mt-3">` +
      `<button type="submit" class="btn btn-primary">生成 Listing</button>` +
      `<button type="button" class="btn" id="lst-demo">载入示例资料</button>` +
      `</div></form>`
    );
  }

  async function render(root, params, query) {
    root.innerHTML = `<div class="view"><div class="page"><div class="page-inner">` +
      `<div class="page-head"><div><h1 class="page-title">Listing 工作室</h1>` +
      `<p class="page-desc">基于已确认的商品事实撰写文案，并逐条做事实对齐质检。</p></div>` +
      `<div class="page-actions"><a class="btn btn-sm" href="/listings" data-link id="lst-new">新建草稿</a></div>` +
      `</div><div class="skeleton skeleton-line" style="height:200px"></div></div></div></div>`;

    let reports = [];
    let recent = [];
    try {
      const results = await Promise.all([
        A.get("/api/reports"),
        A.get("/api/listings?limit=6"),
      ]);
      reports = results[0].items || [];
      recent = results[1].items || [];
    } catch (err) { /* 列表失败不阻塞主流程 */ }

    root.innerHTML = `<div class="view"><div class="page"><div class="page-inner">` +
      `<div class="page-head"><div><h1 class="page-title">Listing 工作室</h1>` +
      `<p class="page-desc">基于已确认的商品事实撰写文案，并逐条做事实对齐质检。</p></div>` +
      `<div class="page-actions"><a class="btn btn-sm" href="/listings" data-link>新建草稿</a></div>` +
      `</div>` +
      `<div class="cmp-layout"><div>${formHtml(reports)}</div>` +
      `<div id="lst-result">${emptyResult(recent)}</div></div>` +
      `</div></div></div>`;
    window.CPIcon.hydrate(root);

    const form = root.querySelector("#lst-form");
    const result = root.querySelector("#lst-result");
    const error = root.querySelector("#lst-error");

    form.marketplace.addEventListener("change", function () {
      setFormLanguage(form, LANGUAGES[form.marketplace.value] || "en-US");
    });

    if (query && query.report) form.analysis_report_id.value = query.report;

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
      await generate(root, result, payload, form);
    });

    root.querySelector("#lst-demo").addEventListener("click", async function () {
      try {
        const demo = await A.get("/api/demo/dataset");
        const req = demo.listing_request || {};
        const product = req.product || {};
        form.name.value = product.name || "";
        form.brand.value = product.brand || "";
        form.marketplace.value = product.marketplace || "US";
        setFormLanguage(form, req.language || "en-US");
        form.price.value = product.price !== undefined && product.price !== null ? product.price : "";
        form.target_audience.value = product.target_audience || "";
        form.specifications.value = Object.keys(product.specifications || {})
          .map(function (k) { return k + ": " + product.specifications[k]; }).join("\n");
        form.key_features.value = (product.key_features || []).join("\n");
        form.certifications.value = (product.certifications || []).join("\n");
        U.toast("已载入示例资料（虚构）", "ok");
      } catch (err) {
        U.toast(err.message, "danger");
      }
    });

    if (query && query.listing) await loadListing(result, query.listing);
  }

  function buildPayload(form) {
    const name = form.name.value.trim();
    if (!name) throw new Error("商品名称必填");
    const marketplace = form.marketplace.value;
    const price = form.price.value.trim();
    return {
      product: {
        name,
        brand: form.brand.value.trim() || null,
        target_platform: "amazon",
        marketplace,
        language: form.language.value.trim() || LANGUAGES[marketplace] || "en-US",
        price: price ? Number(price) : null,
        target_audience: form.target_audience.value.trim() || null,
        specifications: parseSpecs(form.specifications.value),
        key_features: lines(form.key_features.value),
        certifications: lines(form.certifications.value),
        banned_terms: form.banned_terms.value.split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean),
      },
      language: form.language.value.trim() || LANGUAGES[marketplace] || "en-US",
      marketplace,
      analysis_report_id: form.analysis_report_id.value || null,
      keywords: [],
      banned_terms: [],
      data_source: "manual",
    };
  }

  async function generate(root, result, payload, form) {
    const AR = window.CPAsyncRun;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = "提交中…";
    result.innerHTML = `<div class="card card-pad"><div class="row gap-2">` +
      `<span class="badge badge-running">排队中</span>` +
      `<span class="t-sm t-muted">正在创建生成任务…</span></div>` +
      `<div class="skeleton skeleton-line mt-4"></div><div class="skeleton skeleton-line"></div></div>`;
    let run;
    try {
      // Listing 生成 15–35 秒，必须异步；后端同时强制 BYOK
      run = await A.post("/api/listings/generate?async_run=true", payload);
    } catch (err) {
      button.disabled = false;
      button.textContent = "生成 Listing";
      if (err.status === 428) {
        result.innerHTML = `<div class="card card-pad"><div class="callout callout-warn">${U.icon("alert")}` +
          `<div><strong>还没有可用的模型</strong><br>` +
          `激浪不提供模型额度。到设置页填入你自己的 API Key 并设为当前使用，就能生成。` +
          `<div class="mt-2"><a class="btn btn-primary btn-sm" href="/settings" data-link>去配置</a></div>` +
          `</div></div></div>`;
        return;
      }
      result.innerHTML = `<div class="card card-pad"><div class="callout callout-danger">${U.icon("alert")}` +
        `<div><strong>生成失败</strong><br>${U.esc(err.message)}</div></div></div>`;
      return;
    }
    button.disabled = false;
    button.textContent = "生成 Listing";

    renderProgress(result, run.task_id, run.plan || [], payload);
  }

  /* 真实步骤进度：不伪造百分比 */
  function renderProgress(container, taskId, plan, payload) {
    const AR = window.CPAsyncRun;
    container.innerHTML = `<div class="card card-pad">` +
      `<div class="row between wrap gap-2"><div><div class="card-title">正在生成</div>` +
      `<div class="card-sub">生成通常需要 15–35 秒，进度会随实际执行步骤更新</div></div>` +
      `<button type="button" class="btn btn-sm" id="lst-cancel">取消</button></div>` +
      `<div class="progress is-indeterminate mt-3"><div class="progress-bar"></div></div>` +
      `<div class="mt-3" id="lst-steps"></div></div>`;
    window.CPIcon.hydrate(container);

    const stepsBox = container.querySelector("#lst-steps");
    stepsBox.innerHTML = AR.stepList([], plan);

    AR.poller({
      taskId: taskId,
      onUpdate: function (detail) {
        stepsBox.innerHTML = AR.stepList(detail.steps || [], plan);
      },
      onDone: function (detail) {
        const task = detail.task || {};
        const listing = (detail.result || {}).listing;
        if (task.status === "succeeded" && listing) {
          renderListing(container, listing, taskId);
          U.toast("Listing 已生成并保存", "ok");
        } else if (task.status === "cancelled") {
          container.innerHTML = `<div class="card card-pad"><div class="callout callout-warn">${U.icon("info")}` +
            `<div>任务已取消，未保存草稿。</div></div></div>`;
        } else {
          container.innerHTML = `<div class="card card-pad"><div class="callout callout-danger">${U.icon("alert")}` +
            `<div><strong>生成失败</strong><br>${U.esc(task.error_message || "未知错误")}</div></div></div>`;
        }
      },
      onError: function (err) {
        container.innerHTML = `<div class="card card-pad"><div class="callout callout-danger">${U.icon("alert")}` +
          `<div>进度查询失败：${U.esc(err.message)}</div></div></div>`;
      },
    });

    const cancel = container.querySelector("#lst-cancel");
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
  }


  async function loadListing(result, listingId) {
    result.innerHTML = `<div class="card card-pad"><div class="skeleton skeleton-line"></div></div>`;
    try {
      const listing = await A.get(`/api/listings/${encodeURIComponent(listingId)}`);
      renderListing(result, listing);
    } catch (err) {
      result.innerHTML = `<div class="card card-pad"><div class="callout callout-danger">${U.icon("alert")}` +
        `<div>草稿加载失败：${U.esc(err.message)}</div></div></div>`;
    }
  }

  function renderListing(container, listing, taskId) {
    const actions =
      `<div class="row gap-2 wrap">` +
      (taskId ? `<a class="btn btn-sm" href="/tasks/${U.esc(taskId)}" data-link>查看任务</a>` : "") +
      (listing.analysis_report_id
        ? `<a class="btn btn-sm" href="/competitors?report=${U.esc(listing.analysis_report_id)}" data-link>查看关联报告</a>`
        : "") +
      `<button type="button" class="btn btn-sm" data-versions="${U.esc(listing.listing_id)}">版本与差异</button>` +
      `<button type="button" class="btn btn-sm" data-recheck="${U.esc(listing.listing_id)}">复检</button>` +
      `<button type="button" class="btn btn-sm" data-export="${U.esc(listing.listing_id)}">导出</button>` +
      `<button type="button" class="btn btn-sm" data-request-approval="${U.esc(listing.listing_id)}" ` +
      `title="提交后由管理员审批">申请发布</button>` +
      `</div>`;
    container.innerHTML = `<div class="card card-pad">` + R.renderListing(listing, { actions }) +
      `<div id="lst-extra" class="mt-4"></div></div>`;
    window.CPIcon.hydrate(container);
    bindCopy(container);
    bindActions(container, listing);
  }

  function bindCopy(scope) {
    scope.querySelectorAll("[data-copy]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        U.copy(btn.getAttribute("data-copy"), "内容");
      });
    });
  }

  function bindActions(container, listing) {
    const extra = container.querySelector("#lst-extra");

    container.querySelectorAll("[data-request-approval]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        try {
          const approval = await A.post("/api/approvals", {
            kind: "publish_listing",
            listing_id: btn.getAttribute("data-request-approval"),
          });
          U.toast("已提交发布申请，等待管理员审批", "ok");
          btn.outerHTML = `<a class="btn btn-sm" href="/tasks/${U.esc(approval.task_id)}" data-link>` +
            `查看审批进度</a>`;
        } catch (err) {
          U.toast(err.message, "danger");
          btn.disabled = false;
        }
      });
    });

    // 版本与差异：列出同链上的所有版本，并可对相邻版本做 diff
    container.querySelectorAll("[data-versions]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const id = btn.getAttribute("data-versions");
        btn.disabled = true;
        try {
          const data = await A.get(`/api/listings/${encodeURIComponent(id)}/versions`);
          const items = data.items || [];
          extra.innerHTML =
            `<div class="t-section mb-2">版本链（共 ${items.length} 个）</div>` +
            `<div class="table-wrap"><table class="table"><thead><tr>` +
            `<th>版本</th><th>标题</th><th>创建</th><th>操作</th>` +
            `</tr></thead><tbody>` +
            items.map(function (v) {
              const current = v.listing_id === id;
              return `<tr><td class="num">v${U.esc(v.version)}` +
                (current ? ' <span class="badge badge-brand">当前</span>' : "") + `</td>` +
                `<td class="truncate" style="max-width:320px">${U.esc(v.title || "—")}</td>` +
                `<td class="t-muted num">${U.esc(U.fmtTime(v.created_at))}</td>` +
                `<td>` +
                (current ? `<span class="t-xs t-faint">—</span>`
                  : `<a class="btn btn-sm btn-quiet" href="/listings?listing=${U.esc(v.listing_id)}" data-link>打开</a>` +
                    `<button type="button" class="btn btn-sm btn-quiet" data-diff="${U.esc(v.listing_id)}">与当前对比</button>`) +
                `</td></tr>`;
            }).join("") +
            `</tbody></table></div>` +
            `<div id="lst-diff" class="mt-3"></div>`;
          window.CPIcon.hydrate(extra);
          extra.querySelectorAll("[data-diff]").forEach(function (diffBtn) {
            diffBtn.addEventListener("click", function () {
              showDiff(extra, id, diffBtn.getAttribute("data-diff"));
            });
          });
        } catch (err) {
          extra.innerHTML = `<div class="callout callout-danger">${U.icon("alert")}` +
            `<div>版本加载失败：${U.esc(err.message)}</div></div>`;
        } finally {
          btn.disabled = false;
        }
      });
    });

    // 复检：编辑后必须重新跑事实对齐质检
    container.querySelectorAll("[data-recheck]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const id = btn.getAttribute("data-recheck");
        btn.disabled = true;
        btn.textContent = "复检中…";
        try {
          const data = await A.post(`/api/listings/${encodeURIComponent(id)}/check`, {});
          const qc = data.quality_check || {};
          const stored = listing.quality_check || {};
          const differs = Boolean(stored.passed) !== Boolean(qc.passed);
          extra.innerHTML =
            `<div class="t-section mb-2">复检结果</div>` +
            `<div class="callout ${qc.passed ? "callout-info" : "callout-warn"}">${U.icon("shield")}` +
            `<div><strong>本次复检：${qc.passed ? "通过" : "存在问题"}</strong>` +
            (qc.issues && qc.issues.length
              ? `<ul class="limit-list mt-2">` + qc.issues.map(function (i) {
                  return `<li>${U.esc(i.message || "")}</li>`;
                }).join("") + `</ul>`
              : `<br>未发现问题。`) +
            `</div></div>` +
            (differs
              ? `<div class="callout callout-warn mt-2">${U.icon("info")}<div>` +
                `这次复检的结论和保存草稿时不一样（当时：${stored.passed ? "通过" : "存在问题"}）。` +
                `草稿保存时的检查结果会一直保留，复检则按当前内容重新判断，两者都如实列出。` +
                `</div></div>`
              : "") +
            `<p class="t-xs t-muted mt-2">复检只重新计算质检，不改写草稿内容。</p>`;
          window.CPIcon.hydrate(extra);
          extra.scrollIntoView({ block: "nearest" });
        } catch (err) {
          extra.innerHTML = `<div class="callout callout-warn">${U.icon("alert")}` +
            `<div>复检失败：${U.esc(err.message)}</div></div>`;
        } finally {
          btn.disabled = false;
          btn.textContent = "复检";
        }
      });
    });

    // 导出：md / json / txt
    container.querySelectorAll("[data-export]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const id = btn.getAttribute("data-export");
        extra.innerHTML =
          `<div class="t-section mb-2">导出</div>` +
          `<div class="row gap-2 wrap">` +
          ["md", "json", "txt"].map(function (fmt) {
            return `<a class="btn btn-sm" href="/api/listings/${encodeURIComponent(id)}/export?format=${fmt}">` +
              `${U.icon("download")}${fmt.toUpperCase()}</a>`;
          }).join("") +
          `</div>` +
          `<p class="t-xs t-muted mt-2">导出内容来自已保存的草稿，不经过模型。</p>`;
        window.CPIcon.hydrate(extra);
      });
    });
  }

  async function showDiff(container, currentId, againstId) {
    const box = container.querySelector("#lst-diff");
    box.innerHTML = `<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line"></div>`;
    try {
      const data = await A.get(
        `/api/listings/${encodeURIComponent(currentId)}/diff?against=${encodeURIComponent(againstId)}`
      );
      const fields = (data.fields || []).filter(function (f) { return f.changed; });
      const lines = data.unified_diff || [];
      box.innerHTML =
        `<div class="t-section mb-2">字段差异（对比版本 v${U.esc((data.target || {}).version || "?")} → ` +
        `当前 v${U.esc((data.base || {}).version || "?")}）</div>` +
        (fields.length
          ? `<div class="table-wrap"><table class="table"><thead><tr>` +
            `<th>字段</th><th>对比版本</th><th>当前</th></tr></thead><tbody>` +
            fields.map(function (f) {
              const short = function (v) {
                const text = typeof v === "string" ? v : JSON.stringify(v);
                return (text || "—").slice(0, 140);
              };
              return `<tr><td>${U.esc(f.label || f.field)}</td>` +
                `<td class="t-xs">${U.esc(short(f.new))}</td>` +
                `<td class="t-xs">${U.esc(short(f.old))}</td></tr>`;
            }).join("") + `</tbody></table></div>`
          : `<p class="t-sm t-muted">结构化字段没有差异。</p>`) +
        (lines.length
          ? `<div class="t-section mt-3 mb-2">统一差异</div>` +
            `<pre class="raw-pre">${U.esc(lines.join("\n"))}</pre>`
          : "");
      window.CPIcon.hydrate(box);
    } catch (err) {
      box.innerHTML = `<div class="callout callout-danger">${U.icon("alert")}` +
        `<div>差异加载失败：${U.esc(err.message)}</div></div>`;
    }
  }

  function emptyResult(recent) {
    const items = recent || [];
    return (
      `<div class="card"><div class="empty"><span class="empty-icon">${U.icon("listing")}</span>` +
      `<p class="empty-title">还没有生成结果</p>` +
      `<p class="empty-desc">填写商品事实并生成；缺少的规格会进入「待确认」，不会被编造。</p>` +
      `</div></div>` +
      (items.length
        ? `<div class="card" style="margin-top:var(--sp-4)"><div class="card-head"><div>` +
          `<div class="card-title">最近的草稿</div>` +
          `<div class="card-sub">点击可直接打开查看版本、差异与复检</div></div>` +
          `<a class="btn btn-quiet btn-sm" href="/listings" data-link>刷新</a></div>` +
          `<div class="list">` + items.slice(0, 6).map(function (l) {
            return `<a class="list-row" href="/listings?listing=${U.esc(l.listing_id)}" data-link>` +
              `<span class="grow"><span class="t-sm">${U.esc(l.product_name)}</span>` +
              `<span class="t-xs">${U.esc(siteLabel(l.marketplace))} · ${U.esc(languageLabel(l.language))}` +
              (l.version ? ` · v${U.esc(l.version)}` : "") + `</span></span>` +
              (l.is_demo ? U.mockFlag() : "") +
              `<span class="t-xs t-faint">${U.esc(U.fmtTime(l.created_at))}</span></a>`;
          }).join("") + `</div></div>`
        : "")
    );
  }

  window.CPPageListings = { render, renderProgress };
})();
