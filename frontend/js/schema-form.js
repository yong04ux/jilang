/* 激浪 · 参数表单生成器
 *
 * 表单**不该手写**：每个技能的入参本来就已经在服务端用 Pydantic 描述了一遍
 * （必填项、类型、取值范围、可选值），前端再抄一份必然漂移。
 * 这里把接口给出的 JSON Schema 渲染成表单，只做三件事：
 *
 *   1. 按 `x-ui` 选控件（文件、逐行文本、竞品录入、报告选择…）；
 *   2. 把 DOM 读回普通对象，空值一律不提交（交给服务端的「必填」判断）；
 *   3. 给出「你需要准备什么」的一句话摘要。
 *
 * 校验只看必填，类型与范围都交给服务端——两套规则必然对不上。
 */
(function () {
  "use strict";
  const U = window.CPUi;
  const A = window.CPApi;
  const L = window.CPLabel;

  /* ---------- schema 解析 ---------- */

  function resolve(prop) {
    let node = prop || {};
    for (let i = 0; i < 5; i += 1) {
      if (node.$ref) {
        const name = String(node.$ref).replace("#/$defs/", "");
        const defs = window.__cpSchemaDefs || {};
        node = defs[name] || {};
        continue;
      }
      if (node.anyOf) {
        const inner = node.anyOf.filter(function (x) { return x && x.type !== "null"; })[0];
        if (inner) {
          node = inner;
          continue;
        }
      }
      break;
    }
    return node;
  }

  function xui(prop) {
    return (prop && (prop["x-ui"] || (resolve(prop) || {})["x-ui"])) || "";
  }

  function titleOf(prop, name) {
    return (prop && prop.title) || L.field(name) || name;
  }

  function isRequired(parent, name) {
    return (parent && parent.required ? parent.required : []).indexOf(name) !== -1;
  }

  function reqMark(required) {
    return required ? ' <span class="field-req">*</span>' : "";
  }

  function wrap(path, label, required, control, help) {
    return (
      `<label class="field" data-holder="${U.esc(path)}">` +
      `<span class="field-label">${U.esc(label)}${reqMark(required)}</span>` +
      control +
      (help ? `<span class="field-help">${U.esc(help)}</span>` : "") +
      `</label>`
    );
  }

  /* ---------- 控件 ---------- */

  /* 控件初值：用户没传就用接口声明的默认值。
   * 不这么做的话，站点、币种、履约方式这些「有合理默认」的字段会是一片空白，
   * 用户得自己去猜该填什么（填错还要等 422 才知道）。空数组 / 空对象不铺到界面上。 */
  function initialRaw(resolved, value) {
    if (value !== undefined && value !== null && value !== "") return value;
    const def = resolved.default;
    if (def === undefined || def === null || def === "") return "";
    if (Array.isArray(def)) return def.length ? def : "";
    if (typeof def === "object") return Object.keys(def).length ? def : "";
    return def;
  }

  function control(prop, path, value, required, root) {
    const resolved = resolve(prop);
    const ui = xui(prop);
    const type = resolved.type || (resolved.properties ? "object" : "string");
    const raw = initialRaw(resolved, value);

    if (ui === "file") {
      return (
        `<span class="file-drop">` +
        `<input type="file" data-path="${U.esc(path)}" data-type="file" ` +
        `data-filename-path="filename" accept=".csv,.json,.xlsx" />` +
        `${U.icon("upload")}` +
        `<span class="file-drop-title">选择文件</span>` +
        `<span class="file-drop-hint">CSV / JSON / Excel，不超过 5 MB</span>` +
        `</span>` +
        `<span class="field-help" data-file-name>还没有选择文件</span>`
      );
    }

    if (ui === "competitor-lines") {
      return (
        `<textarea rows="6" spellcheck="false" data-path="${U.esc(path)}" data-type="competitors" ` +
        `placeholder="竞品 A | 25.99 | 4.2 | 380 | 盖子漏水&#10;竞品 B">${U.esc(competitorsToText(raw))}</textarea>`
      );
    }

    if (ui === "kv-lines") {
      return (
        `<textarea rows="3" spellcheck="false" data-path="${U.esc(path)}" data-type="kv" ` +
        `placeholder="容量: 750ml&#10;材质: 304 不锈钢">${U.esc(kvToText(raw))}</textarea>`
      );
    }

    if (ui === "keyword-lines") {
      return (
        `<textarea rows="3" spellcheck="false" data-path="${U.esc(path)}" data-type="keywords" ` +
        `placeholder="insulated water bottle | 12000 | 8&#10;leak proof bottle">${U.esc(keywordsToText(raw))}</textarea>`
      );
    }

    if (ui === "lines") {
      return (
        `<textarea rows="3" data-path="${U.esc(path)}" data-type="lines">` +
        `${U.esc(Array.isArray(raw) ? raw.join("\n") : raw)}</textarea>`
      );
    }

    if (ui === "report-picker" || ui === "listing-picker") {
      const kind = ui === "report-picker" ? "reports" : "listings";
      return (
        `<select data-path="${U.esc(path)}" data-type="text" data-picker="${kind}">` +
        `<option value="">读取中…</option></select>`
      );
    }

    if (resolved.enum) {
      const options = resolved.enum.map(function (v) {
        const selected = String(raw) === String(v) ? " selected" : "";
        return `<option value="${U.esc(v)}"${selected}>${U.esc(L.value(v))}</option>`;
      }).join("");
      return `<select data-path="${U.esc(path)}" data-type="text">${options}</select>`;
    }

    if (type === "boolean") {
      return (
        `<label class="row gap-2 t-sm" style="height:32px">` +
        `<input type="checkbox" data-path="${U.esc(path)}" data-type="checkbox"` +
        `${raw === true ? " checked" : ""} /> <span>${U.esc(titleOf(prop, path))}</span></label>`
      );
    }

    if (type === "number" || type === "integer") {
      const step = type === "integer" ? "1" : "any";
      return (
        `<input type="number" step="${step}" data-path="${U.esc(path)}" data-type="number" ` +
        `value="${raw === "" ? "" : U.esc(raw)}" placeholder="0" />`
      );
    }

    if (type === "array" || type === "object") {
      return (
        `<textarea rows="3" spellcheck="false" data-path="${U.esc(path)}" data-type="json" ` +
        `placeholder="[{ }]">${raw === "" ? "" : U.esc(JSON.stringify(raw, null, 2))}</textarea>`
      );
    }

    const maxLength = resolved.maxLength ? ` maxlength="${resolved.maxLength}"` : "";
    return (
      `<input data-path="${U.esc(path)}" data-type="text" value="${U.esc(raw)}"${maxLength} />`
    );
  }

  /* ---------- 渲染 ---------- */

  function renderFields(schema, parent, prefix, values) {
    const props = (schema && schema.properties) || {};
    return Object.keys(props)
      .filter(function (name) { return xui(props[name]) !== "hidden"; })
      .map(function (name) {
        const prop = props[name];
        const path = prefix ? `${prefix}.${name}` : name;
        const resolved = resolve(prop);
        const required = isRequired(schema, name);
        const value = values ? values[name] : undefined;

        // 嵌套对象（例如 Listing 的商品事实）：平铺在同一张网格里，path 带上前缀
        if (resolved.properties && !xui(prop)) {
          const inner = renderFields(resolved, resolved, path, value || {});
          return (
            `<div class="field-span-2 schema-group"><div class="field-label">` +
            `${U.esc(titleOf(prop, name))}${reqMark(required)}</div>` +
            `<div class="grid-2">${inner}</div></div>`
          );
        }

        const help = helpOf(resolved, prop, name);
        const wide = isWide(prop);
        const cell = wrap(
          path,
          titleOf(prop, name),
          required,
          control(prop, path, value, required, schema),
          help
        );
        return wide ? cell.replace('class="field"', 'class="field field-span-2"') : cell;
      })
      .join("");
  }

  function isWide(prop) {
    const ui = xui(prop);
    if (ui === "file" || ui === "competitor-lines" || ui === "kv-lines" || ui === "keyword-lines") return true;
    const resolved = resolve(prop);
    return resolved.type === "array" || resolved.type === "object";
  }

  function helpOf(resolved, prop, name) {
    const ui = xui(prop);
    if (ui === "competitor-lines") {
      return "按「名称 | 价格 | 评分 | 评论数 | 一条评论」写，只有名称必填。";
    }
    if (ui === "keyword-lines") return "按「关键词 | 搜索量 | 排名」写，只填关键词也可以。";
    if (ui === "kv-lines") return "每行一条，格式「键: 值」。";
    if (ui === "lines") return "每行一条。";
    if (ui === "report-picker") return "选一份已经跑出来的竞品分析报告。";
    if (ui === "listing-picker") return "选一份已经生成的 Listing 草稿。";
    // 下拉框的选项本身就是说明，再补一句描述只是噪音。
    if (resolved.enum) return "";
    // 说明和标签一字不差就别印第二遍（纯噪音）；「最多 N 个字」同理，
    // 真超长时后端会告诉用户，不必在每个输入框下面挂一条。
    const desc = String(resolved.description || "").trim();
    const label = String(resolved.title || "").trim();
    if (!desc) return "";
    if (desc === label || desc === label + "。") return "";
    return desc;
  }

  function render(schema, value) {
    window.__cpSchemaDefs = (schema && schema.$defs) || {};
    if (!schema || !schema.properties) return "";
    return `<div class="grid-2 schema-form">${renderFields(schema, schema, "", value || {})}</div>`;
  }

  /* ---------- 读回 ---------- */

  function read(scope, schema) {
    const out = {};
    if (!scope) return out;
    const defs = (schema && schema.$defs) || {};
    window.__cpSchemaDefs = defs;

    scope.querySelectorAll("[data-path]").forEach(function (el) {
      const path = el.getAttribute("data-path");
      const kind = el.getAttribute("data-type") || "text";
      if (el.disabled) return;

      if (kind === "file") {
        const data = el.getAttribute("data-base64");
        if (!data) return;
        setPath(out, path, data);
        const fileNamePath = el.getAttribute("data-filename-path");
        const fileName = el.getAttribute("data-filename");
        if (fileNamePath && fileName) setPath(out, fileNamePath, fileName);
        return;
      }

      if (kind === "checkbox") {
        setPath(out, path, Boolean(el.checked));
        return;
      }

      const raw = String(el.value === undefined ? "" : el.value).trim();

      if (kind === "number") {
        if (raw === "" || isNaN(Number(raw))) return;
        setPath(out, path, Number(raw));
        return;
      }
      if (kind === "lines") {
        const list = splitLines(raw);
        if (list.length) setPath(out, path, list);
        return;
      }
      if (kind === "kv") {
        const obj = {};
        splitLines(raw).forEach(function (line) {
          const at = line.indexOf(":");
          if (at > 0) obj[line.slice(0, at).trim()] = line.slice(at + 1).trim();
        });
        if (Object.keys(obj).length) setPath(out, path, obj);
        return;
      }
      if (kind === "competitors") {
        const list = parseCompetitors(raw);
        if (list.length) setPath(out, path, list);
        return;
      }
      if (kind === "keywords") {
        const list = parseKeywords(raw);
        if (list.length) setPath(out, path, list);
        return;
      }
      if (kind === "json") {
        if (raw === "") return;
        try {
          setPath(out, path, JSON.parse(raw));
        } catch (err) {
          throw fieldError(path, "这一格需要是合法的 JSON");
        }
        return;
      }

      // 文本 / 下拉：空值不提交，交给服务端判断「必填」
      if (raw === "") return;
      setPath(out, path, raw);
    });

    return out;
  }

  function setPath(target, path, value) {
    const parts = String(path).split(".");
    let node = target;
    for (let i = 0; i < parts.length - 1; i += 1) {
      if (!node[parts[i]] || typeof node[parts[i]] !== "object") node[parts[i]] = {};
      node = node[parts[i]];
    }
    node[parts[parts.length - 1]] = value;
  }

  function fieldError(path, message) {
    const err = new Error(message);
    err.field = path;
    return err;
  }

  function splitLines(text) {
    return String(text || "")
      .split(/\r?\n/)
      .map(function (line) { return line.trim(); })
      .filter(Boolean);
  }

  /* ---------- 竞品与关键词的文本格式 ----------
   * 「名称 | 价格 | 评分 | 评论数 | 一条评论」比让人写 JSON 现实得多。
   * 工作台也用这两个函数，避免出现第三份解析。 */

  function parseCompetitors(text) {
    return splitLines(text)
      .map(function (line) {
        const parts = line.split("|").map(function (s) { return s.trim(); });
        const item = { name: parts[0], is_demo: false };
        if (!item.name) return null;
        if (parts[1] && !isNaN(Number(parts[1]))) item.price = Number(parts[1]);
        if (parts[2] && !isNaN(Number(parts[2]))) item.rating = Number(parts[2]);
        if (parts[3] && !isNaN(Number(parts[3]))) item.review_count = Number(parts[3]);
        if (parts[4]) {
          const review = { text: parts[4] };
          if (item.rating && item.rating >= 1) review.rating = item.rating;
          item.reviews = [review];
        }
        return item;
      })
      .filter(Boolean);
  }

  function competitorsToText(list) {
    return (list || []).map(function (c) {
      const parts = [c.name || ""];
      if (c.price !== undefined && c.price !== null) parts.push(c.price);
      else if (c.rating !== undefined && c.rating !== null) parts.push("");
      if (c.rating !== undefined && c.rating !== null) parts.push(c.rating);
      if (c.review_count !== undefined && c.review_count !== null) parts.push(c.review_count);
      const review = Array.isArray(c.reviews) && c.reviews[0] ? c.reviews[0].text || "" : "";
      if (review) parts.push(review);
      return parts.join(" | ");
    }).join("\n");
  }

  function parseKeywords(text) {
    return splitLines(text)
      .map(function (line) {
        const parts = line.split("|").map(function (s) { return s.trim(); });
        if (!parts[0]) return null;
        const item = { keyword: parts[0] };
        if (parts[1] && !isNaN(Number(parts[1]))) item.search_volume = Number(parts[1]);
        if (parts[2] && !isNaN(Number(parts[2]))) item.rank = Number(parts[2]);
        return item;
      })
      .filter(Boolean);
  }

  function keywordsToText(list) {
    return (list || []).map(function (k) {
      const parts = [k.keyword || ""];
      if (k.search_volume !== undefined && k.search_volume !== null) parts.push(k.search_volume);
      else if (k.rank !== undefined && k.rank !== null) parts.push("");
      if (k.rank !== undefined && k.rank !== null) parts.push(k.rank);
      return parts.join(" | ");
    }).join("\n");
  }

  function kvToText(obj) {
    if (!obj || typeof obj !== "object") return "";
    return Object.keys(obj).map(function (k) { return `${k}: ${obj[k]}`; }).join("\n");
  }

  /* ---------- 选择器数据 ---------- */

  async function hydratePickers(scope) {
    if (!scope) return;
    const picks = scope.querySelectorAll("[data-picker]");
    if (!picks.length) return;

    const wanted = {};
    picks.forEach(function (el) { wanted[el.getAttribute("data-picker")] = true; });

    if (wanted.reports) {
      await fillPicker(scope, "reports", "/api/reports?limit=20", function (row) {
        return {
          value: row.report_id,
          label: `${row.product_name || "未命名商品"} · ${L.site(row.marketplace)} · ${U.fmtTime(row.created_at)}`,
        };
      });
    }
    if (wanted.listings) {
      await fillPicker(scope, "listings", "/api/listings?limit=20", function (row) {
        return {
          value: row.listing_id,
          label: `${row.product_name || "未命名商品"} · ${L.site(row.marketplace)} · ${U.fmtTime(row.created_at)}`,
        };
      });
    }
  }

  async function fillPicker(scope, kind, url, mapper) {
    let items = [];
    try {
      items = (await A.get(url)).items || [];
    } catch (err) {
      items = [];
    }
    scope.querySelectorAll(`[data-picker="${kind}"]`).forEach(function (el) {
      if (!items.length) {
        // 没有可选内容时不留一个空下拉：换成普通输入框，用户可以手填编号外的内容
        el.innerHTML = `<option value="">还没有可选的${kind === "reports" ? "分析报告" : "Listing 草稿"}</option>`;
        el.disabled = true;
        return;
      }
      el.innerHTML =
        `<option value="">请选择…</option>` +
        items
          .map(function (row) {
            const item = mapper(row);
            return `<option value="${U.esc(item.value)}">${U.esc(item.label)}</option>`;
          })
          .join("");
    });
  }

  /** 「你需要准备」：取必填项（没有必填就取前几项）拼成一句话 */
  function describe(schema, opts) {
    const max = (opts && opts.max) || 4;
    const props = (schema && schema.properties) || {};
    const required = (schema && schema.required) || [];
    const names = (required.length ? required : Object.keys(props)).filter(function (n) {
      return props[n] && xui(props[n]) !== "hidden";
    });
    return names
      .slice(0, max)
      .map(function (n) { return titleOf(props[n], n); })
      .join(" · ");
  }

  window.CPSchemaForm = {
    render,
    read,
    describe,
    hydratePickers,
    parseCompetitors,
    competitorsToText,
  };
})();
