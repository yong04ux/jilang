/* 激浪 · 数据资产：预览 → 字段映射 → 提交 → 错误 CSV
 *
 * 两步导入是真实接口：
 *   POST /api/import/preview  → 保存文件 + 识别列 + 逐行校验（不写业务数据）
 *   POST /api/import/commit   → 按映射重新解析并写入批次（不可重复提交）
 * 错误永远定位到「行 + 字段」，并可导出 CSV。
 */
(function () {
  "use strict";
  const U = window.CPUi;
  const A = window.CPApi;

  const state = {
    fileName: "",
    upload: false,
    result: null,
    mapping: {},
  };

  /* 可映射的目标字段（与后端 COLUMN_ALIASES 一致） */
  const TARGET_FIELDS = [
    { key: "", label: "（忽略此列）" },
    { key: "name", label: "商品名称" },
    { key: "brand", label: "品牌" },
    { key: "asin", label: "ASIN" },
    { key: "category", label: "商品类目" },
    { key: "price", label: "价格" },
    { key: "currency", label: "币种" },
    { key: "rating", label: "商品评分" },
    { key: "review_count", label: "评论总数" },
    { key: "key_features", label: "商品卖点" },
    { key: "specifications", label: "商品规格" },
    { key: "review_text", label: "评论内容" },
    { key: "review_rating", label: "评论星级" },
    { key: "review_title", label: "评论标题" },
    { key: "review_date", label: "评论日期" },
    { key: "is_demo", label: "是否为演示数据" },
    { key: "keyword", label: "关键词" },
    { key: "search_volume", label: "搜索量" },
    { key: "rank", label: "排名" },
  ];

  function uploadCard() {
    return (
      `<div class="card card-pad data-upload-panel">` +
      `<div class="row between"><div><div class="card-title">导入商品数据</div>` +
      `<div class="card-sub">CSV / JSON / Excel，先预览再提交</div></div>` +
      `<span class="t-xs t-muted">≤ 5 MB</span></div>` +
      `<label class="file-drop mt-4" id="data-drop">` +
      `<input type="file" id="data-file" accept=".csv,.json,.xlsx" />` +
      `${U.icon("upload")}` +
      `<span class="file-drop-title">点击选择文件</span>` +
      `<span class="file-drop-hint">支持 .csv / .json / .xlsx，单文件不超过 5 MB</span>` +
      `<span class="t-xs t-muted" id="data-filename">尚未选择文件</span>` +
      `</label>` +
      `<p class="callout callout-danger mt-3" id="data-error" hidden></p>` +
      `<div class="row gap-2 mt-3">` +
      `<button type="button" class="btn btn-primary" id="data-upload" disabled>${U.icon("upload")}开始导入</button>` +
      `<button type="button" class="btn btn-secondary" id="data-demo">${U.icon("download")}示例文件</button>` +
      `</div>` +
      `<p class="form-note t-xs t-muted mt-2">支持 CSV、JSON、Excel。导入前可预览并确认字段映射。</p>` +
      `</div>`
    );
  }

  function mappingCard(r) {
    const columns = r.columns || [];
    if (!columns.length) return "";
    const rows = columns.map(function (col) {
      const name = col.source || col.name || col.header || "";
      const detected = col.field || "";
      const current = state.mapping[name] !== undefined ? state.mapping[name] : detected;
      const options = TARGET_FIELDS.map(function (f) {
        return `<option value="${f.key}"${f.key === current ? " selected" : ""}>${U.esc(f.label)}</option>`;
      }).join("");
      const suggested = detected
        ? `<span class="badge badge-ok">已识别</span>`
        : `<span class="badge badge-warn">需映射</span>`;
      return (
        `<tr><td><span class="source-column-name">${U.esc(name)}</span></td>` +
        `<td>${suggested}</td>` +
        `<td><select data-map-col="${U.esc(name)}" style="max-width:260px">${options}</select></td></tr>`
      );
    }).join("");

    return (
      `<div class="card mt-4"><div class="card-head"><div>` +
      `<div class="card-title">字段映射</div>` +
      `<div class="card-sub">识别错的列可以手动改；选「忽略」的列不会进入数据</div></div></div>` +
      `<div class="card-body">` +
      `<div class="table-wrap"><table class="table"><thead><tr>` +
      `<th>文件列</th><th>识别结果</th><th>映射到</th>` +
      `</tr></thead><tbody>${rows}</tbody></table></div>` +
      `<div class="row gap-2 mt-4">` +
      `<button type="button" class="btn btn-primary" id="data-commit"${r.can_commit ? "" : " disabled"}>` +
      `提交导入</button>` +
      `<button type="button" class="btn" id="data-repreview">用新映射重新校验</button>` +
      `</div>` +
      (r.can_commit ? "" : `<p class="t-xs t-warn mt-2">当前有行级错误或未识别列，修正后才能提交。</p>`) +
      `</div></div>`
    );
  }

  function resultCard() {
    const r = state.result;
    if (!r) {
      return (
        `<div class="card"><div class="empty"><span class="empty-icon">${U.icon("table")}</span>` +
        `<p class="empty-title">还没有导入结果</p>` +
        `<p class="empty-desc">上传文件后，这里会先显示识别到的列与预览，再由你确认字段映射。</p></div></div>`
      );
    }
    if (state.upload) {
      return (
        `<div class="card"><div class="empty"><span class="empty-icon">${U.icon("upload")}</span>` +
        `<p class="empty-title">正在上传并校验</p>` +
        `<p class="empty-desc">大文件可能需要几秒钟。</p></div></div>`
      );
    }

    const errors = r.errors || [];
    const errorRows = errors.slice(0, 50).map(function (e) {
      return `<tr><td class="num">${e.row}</td><td><code>${U.esc(e.field || "")}</code></td>` +
        `<td>${U.esc(e.message || "")}</td>` +
        `<td class="t-muted">${e.value === null || e.value === undefined ? "" : U.esc(String(e.value))}</td></tr>`;
    }).join("");

    const preview = (r.preview || []).map(function (c) {
      return `<tr><td>${U.esc(c.name)}</td>` +
        `<td class="num">${c.price === null || c.price === undefined ? "—" : Number(c.price).toFixed(2)}</td>` +
        `<td class="num">${(c.reviews || []).length}</td>` +
        `<td>${c.is_demo ? '<span class="badge badge-warn">演示数据</span>' : '<span class="badge badge-ok">已导入</span>'}</td></tr>`;
    }).join("");

    const statusBadge =
      r.status === "validated" ? `<span class="badge badge-ok">校验通过</span>`
        : r.status === "imported" ? `<span class="badge badge-ok">已提交</span>`
        : r.status === "needs_mapping" ? `<span class="badge badge-warn">需要字段映射</span>`
        : r.status === "rejected" ? `<span class="badge badge-danger">有错误</span>`
        : `<span class="badge">${U.esc(r.status || "")}</span>`;

    return (
      `<div class="card">` +
      `<div class="card-head"><div><div class="card-title">校验结果</div>` +
      `<div class="card-sub">${U.esc(r.filename || r.source_name || "")} · ` +
      `${U.esc(r.format || r.source_format || "")} · 共 ${U.esc(r.total_rows || 0)} 行</div></div>` +
      statusBadge + `</div>` +
      `<div class="card-body">` +
      `<div class="metric-grid">` +
      `<div class="metric-cell"><div class="metric-label">有效竞品</div>` +
      `<div class="metric-value">${r.valid_rows || 0}</div></div>` +
      `<div class="metric-cell"><div class="metric-label">错误行</div>` +
      `<div class="metric-value">${errors.length}</div></div>` +
      `<div class="metric-cell"><div class="metric-label">总行数</div>` +
      `<div class="metric-value">${r.total_rows || 0}</div></div>` +
      `<div class="metric-cell"><div class="metric-label">识别字段</div>` +
      `<div class="metric-value">${(r.columns || []).length}</div></div>` +
      `</div>` +

      (preview
        ? `<div class="t-section mt-4">数据预览</div>` +
          `<div class="table-wrap"><table class="table"><thead><tr>` +
          `<th>名称</th><th class="num">价格</th><th class="num">评论样本</th><th>来源</th>` +
          `</tr></thead><tbody>${preview}</tbody></table></div>`
        : "") +

      (errorRows
        ? `<div class="t-section mt-4">逐行错误${errors.length > 50 ? `（显示前 50 条，共 ${errors.length} 条）` : ""}</div>` +
          `<div class="table-wrap"><table class="table"><thead><tr>` +
          `<th class="num">行</th><th>字段</th><th>原因</th><th>原值</th>` +
          `</tr></thead><tbody>${errorRows}</tbody></table></div>` +
          `<button type="button" class="btn btn-sm mt-2" id="data-export-errors">` +
          `${U.icon("download")}下载错误 CSV</button>`
        : "") +

      ((r.warnings || []).length
        ? `<div class="callout callout-warn mt-3">${U.icon("alert")}<div>` +
          r.warnings.map(function (w) { return U.esc(w); }).join("<br>") + `</div></div>`
        : "") +

      ((r.status === "imported" && (r.valid_rows || 0) > 0)
        ? `<div class="row gap-2 mt-4">` +
          `<a class="btn btn-primary btn-sm" href="/competitors" data-link>` +
          `${U.icon("competitors")}去竞品分析页使用</a>` +
          `<a class="btn btn-sm" href="/workbench" data-link>在 AI 助手里用这批数据</a>` +
          `</div>`
        : "") +
      `</div></div>`
    );
  }

  function sourceListCard(items) {
    if (!items.length) {
      return `<div class="data-source-empty"><span class="data-mini-icon">${U.icon("database")}</span>` +
        `<div><div class="card-title">数据集列表</div><p class="card-sub">导入并保存文件后，数据集会显示在这里。</p></div>` +
        `<span class="badge">暂无数据集</span></div>`;
    }
    return `<div class="data-source-table-wrap"><table class="table data-source-table"><thead><tr>` +
      `<th>数据集名称</th><th>记录数量</th><th>更新时间</th><th>数据来源</th><th>状态</th></tr></thead><tbody>` +
      items.map(function (s) {
        const status = s.status === "imported" ? `<span class="badge badge-ok">已导入</span>`
          : s.status === "needs_mapping" ? `<span class="badge badge-warn">待映射</span>`
          : s.status === "rejected" ? `<span class="badge badge-danger">需检查</span>`
          : `<span class="badge">${U.esc(s.status || "处理中")}</span>`;
        return `<tr><td><div class="data-dataset-name"><span class="data-file-icon">${U.icon("file")}</span>` +
          `<span><strong>${U.esc(s.name || "未命名数据集")}</strong><small>${U.esc((s.format || "文件").toUpperCase())}</small></span></div></td>` +
          `<td class="num">${U.esc(s.row_count || 0)} 条</td><td>${U.esc(U.fmtTime(s.created_at))}</td>` +
          `<td>文件导入</td><td>${status}</td></tr>`;
      }).join("") + `</tbody></table></div>`;
  }

  async function render(root) {
    state.result = null;
    state.mapping = {};
    state.upload = false;
    root.innerHTML = `<div class="view"><div class="page data-page"><div class="page-inner">` +
      `<section class="data-hero"><div class="data-hero-copy"><div class="data-eyebrow">CROSS-BORDER COMMERCE · DATA HUB</div>` +
      `<div class="data-title-row"><h1 class="page-title">数据资产</h1><span class="badge badge-brand">${U.icon("sparkles")}演示环境</span></div>` +
      `<p class="page-desc">管理商品数据、校验导入文件，并维护统一的数据字段。</p></div>` +
      `<div class="data-hero-note"><span class="data-hero-mark">${U.icon("database")}</span><div>` +
      `<strong>让数据成为运营决策的起点</strong><p>当前可通过文件导入体验数据校验与字段映射，真实平台数据将在完成连接后呈现。</p></div></div></section>` +
      `<section class="data-overview" aria-label="数据概览">` +
      `<div class="data-stat-card"><span class="data-stat-icon">${U.icon("data")}</span><div><span class="data-stat-label">已保存数据集</span><strong id="data-stat-sources">—</strong><small>个数据集</small></div></div>` +
      `<div class="data-stat-card"><span class="data-stat-icon">${U.icon("check")}</span><div><span class="data-stat-label">最近校验</span><strong id="data-stat-valid">待导入</strong><small>导入文件后自动更新</small></div></div>` +
      `<div class="data-stat-card"><span class="data-stat-icon">${U.icon("clock")}</span><div><span class="data-stat-label">最近导入</span><strong id="data-stat-latest">—</strong><small id="data-stat-latest-note">等待文件导入</small></div></div>` +
      `<div class="data-stat-card"><span class="data-stat-icon">${U.icon("layers")}</span><div><span class="data-stat-label">数据来源</span><strong>文件导入</strong><small>CSV · JSON · Excel</small></div></div></section>` +
      `<section class="data-main-grid"><div>${uploadCard()}</div><div class="card data-result-panel" id="data-result">${resultCard()}</div></section>` +
      `<section class="card data-source-panel"><div class="card-head"><div><div class="card-title">数据集列表</div>` +
      `<div class="card-sub">查看已保存的数据集与最近更新时间</div></div><span class="badge" id="data-source-count">0 个数据集</span></div>` +
      `<div id="data-sources-content">${sourceListCard([])}</div></section></div></div></div>`;
    window.CPIcon.hydrate(root);
    bind(root);

    A.get("/api/data-sources?limit=10").then(function (data) {
      const items = data.items || [];
      const content = root.querySelector("#data-sources-content");
      if (!content) return;
      content.innerHTML = sourceListCard(items);
      root.querySelector("#data-stat-sources").textContent = String(items.length);
      root.querySelector("#data-source-count").textContent = `${items.length} 个数据集`;
      const latest = items[0];
      if (latest) {
        root.querySelector("#data-stat-latest").textContent = U.fmtTime(latest.created_at) || "已记录";
        root.querySelector("#data-stat-latest-note").textContent = latest.name || "最近导入的数据集";
      }
      window.CPIcon.hydrate(content);
    }).catch(function () {
      const content = root.querySelector("#data-sources-content");
      if (content) content.innerHTML = `<div class="data-source-empty"><span class="data-mini-icon">${U.icon("database")}</span>` +
        `<div><div class="card-title">暂时无法读取数据集</div><p class="card-sub">请稍后刷新，或先导入一个文件。</p></div></div>`;
      window.CPIcon.hydrate(content || root);
    });
  }

  function collectMapping(root) {
    const mapping = {};
    root.querySelectorAll("[data-map-col]").forEach(function (select) {
      const column = select.getAttribute("data-map-col");
      const target = select.value;
      // 「本列名 -> 目标字段」；空表示忽略
      if (target) mapping[column] = target;
    });
    return mapping;
  }

  function bind(root) {
    const input = root.querySelector("#data-file");
    const nameEl = root.querySelector("#data-filename");
    const upload = root.querySelector("#data-upload");
    const error = root.querySelector("#data-error");
    const result = root.querySelector("#data-result");

    input.addEventListener("change", function () {
      const file = input.files && input.files[0];
      state.fileName = file ? file.name : "";
      nameEl.textContent = state.fileName || "未选择文件";
      upload.disabled = !file;
    });

    upload.addEventListener("click", async function () {
      const file = input.files && input.files[0];
      if (!file) return;
      error.hidden = true;
      state.upload = true;
      result.innerHTML = resultCard();
      window.CPIcon.hydrate(result);
      const form = new FormData();
      form.append("file", file);
      try {
        state.result = await A.postForm("/api/import/preview", form);
        state.upload = false;
        const validStat = root.querySelector("#data-stat-valid");
        if (validStat) validStat.textContent = state.result.status === "validated" ? "校验通过" : (state.result.errors || []).length ? "需检查" : "待映射";
        state.mapping = {};
        paintResult(root, result);
        const errs = (state.result.errors || []).length;
        U.toast(
          state.result.status === "needs_mapping"
            ? "需要先确认字段映射"
            : errs ? `校验完成，有 ${errs} 行错误` : "校验通过，可以提交",
          errs || state.result.status === "needs_mapping" ? "danger" : "ok"
        );
      } catch (err) {
        state.upload = false;
        error.hidden = false;
        error.textContent = err.message;
        if (err.detail && err.detail.errors) {
          state.result = {
            filename: file.name, total_rows: 0, valid_rows: 0,
            preview: [], columns: [], errors: err.detail.errors, status: "rejected",
          };
          paintResult(root, result);
        } else {
          result.innerHTML = resultCard();
        }
      } finally {
        upload.disabled = false;
        upload.textContent = "预览并校验";
      }
    });

    const demo = root.querySelector("#data-demo");
    if (demo) {
      demo.addEventListener("click", function () {
        U.toast("示例文件：examples/competitors_sample.csv（可直接选择该文件）", "ok");
      });
    }

    // 映射表单是动态插入的，事件委托到容器
    result.addEventListener("change", function (event) {
      if (event.target.closest("[data-map-col]")) {
        state.mapping = collectMapping(root);
      }
    });

    result.addEventListener("click", async function (event) {
      const repreview = event.target.closest("#data-repreview");
      if (repreview) {
        await repreviewWithMapping(root, result, repreview);
        return;
      }
      const commit = event.target.closest("#data-commit");
      if (commit) {
        await doCommit(root, result, commit);
        return;
      }
      const exportBtn = event.target.closest("#data-export-errors");
      if (exportBtn) exportErrors(root);
    });
  }

  function paintResult(root, container) {
    const saved = { ...state.mapping };
    container.innerHTML = resultCard() + mappingCard(state.result || {});
    window.CPIcon.hydrate(container);
    state.mapping = saved;
    // 恢复用户已经改过的选择
    requestAnimationFrame(function () {
      container.querySelectorAll("[data-map-col]").forEach(function (select) {
        const column = select.getAttribute("data-map-col");
        if (saved[column] !== undefined) select.value = saved[column];
      });
    });
  }

  async function repreviewWithMapping(root, container, button) {
    if (!state.result || !state.result.data_source_id) {
      U.toast("请先上传文件", "danger");
      return;
    }
    const mapping = collectMapping(root);
    if (!Object.keys(mapping).length) {
      U.toast("至少映射一列（通常是 name）", "danger");
      return;
    }
    button.disabled = true;
    button.textContent = "校验中…";
    try {
      const next = await A.post("/api/import/remap", {
        data_source_id: state.result.data_source_id,
        field_mapping: mapping,
      });
      state.mapping = mapping;
      state.result = next;
      paintResult(root, container);
      const errs = (next.errors || []).length;
      U.toast(
        next.status === "validated"
          ? "映射已生效，可以提交"
          : errs ? `仍有 ${errs} 行错误` : "映射不完整，请补全必填列",
        next.status === "validated" ? "ok" : "danger"
      );
    } catch (err) {
      button.disabled = false;
      button.textContent = "用新映射重新校验";
      U.toast(err.message, "danger");
    }
  }

  async function doCommit(root, container, button) {
    if (!state.result || !state.result.data_source_id) return;
    const mapping = collectMapping(root);
    if (!Object.keys(mapping).length) {
      U.toast("请先完成字段映射（至少 name）", "danger");
      return;
    }
    button.disabled = true;
    button.textContent = "提交中…";
    try {
      const committed = await A.post("/api/import/commit", {
        data_source_id: state.result.data_source_id,
        field_mapping: mapping,
      });
      state.result = {
        ...state.result,
        status: "imported",
        valid_rows: committed.valid_rows || committed.total_rows || 0,
        total_rows: committed.total_rows || state.result.total_rows,
        task_id: committed.task_id,
      };
      paintResult(root, container);
      U.toast(`导入完成：${state.result.valid_rows} 个竞品已写入批次`, "ok");
    } catch (err) {
      button.disabled = false;
      button.textContent = "提交导入";
      const detail = err.detail && err.detail.errors;
      if (detail) {
        state.result = { ...state.result, status: "rejected", errors: detail };
        paintResult(root, container);
      }
      U.toast(err.message, "danger");
    }
  }

  function exportErrors(root) {
    const errors = (state.result && state.result.errors) || [];
    if (!errors.length) return;
    const header = "row,field,message,value\n";
    const body = errors.map(function (e) {
      const quote = function (v) {
        const s = v === null || v === undefined ? "" : String(v);
        return '"' + s.replace(/"/g, '""') + '"';
      };
      return [e.row, quote(e.field), quote(e.message), quote(e.value)].join(",");
    }).join("\n");
    const blob = new Blob(["\uFEFF" + header + body], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "import-errors.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  window.CPPageData = { render };
})();
