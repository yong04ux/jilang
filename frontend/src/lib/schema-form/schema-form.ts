/**
 * 参数表单生成器 —— 把接口给的 JSON Schema 渲染成表单。逐条移植自 `js/schema-form.js`。
 *
 * 三条原则（原文注释保留在这里，因为它们解释了为什么长成这样）：
 *  1. 表单不手写：入参已经在服务端用 Pydantic 描述过，前端再抄一份必然漂移；
 *  2. 只做三件事：按 `x-ui` 选控件 / 把 DOM 读回普通对象 / 给一句「你需要准备什么」；
 *  3. 校验只看必填，类型与范围交给服务端 —— 两套规则必然对不上。
 *
 * 与 ui.ts 一样用相对路径 + `.ts` 扩展名，以便 Node 直接用桩对象做语义对照。
 */
import { esc, fmtTime, icon } from '../../lib/ui.ts'
import { field as labelField, site as labelSite, value as labelValue } from '../../lib/labels.ts'
import { api } from '../../lib/api.ts'

type Dict = Record<string, any>

/* schema 里的 $defs：现有实现挂在 window.__cpSchemaDefs 上，这里改成模块内变量。
   一次只渲染一张表单，不存在并发覆盖的问题。 */
let schemaDefs: Record<string, Dict> = {}

/* ------------------------------------------------------------ schema 解析 */

function resolve(prop: Dict | null | undefined): Dict {
  let node: Dict = prop || {}
  for (let i = 0; i < 5; i += 1) {
    if (node.$ref) {
      const name = String(node.$ref).replace('#/$defs/', '')
      node = schemaDefs[name] || {}
      continue
    }
    if (node.anyOf) {
      const inner = node.anyOf.filter((x: Dict | null) => x && x.type !== 'null')[0]
      if (inner) {
        node = inner
        continue
      }
    }
    break
  }
  return node
}

function xui(prop: Dict | null | undefined): string {
  return (prop && (prop['x-ui'] || (resolve(prop) || {})['x-ui'])) || ''
}

function titleOf(prop: Dict | null | undefined, name: string): string {
  return (prop && prop.title) || labelField(name) || name
}

function isRequired(parent: Dict | null | undefined, name: string): boolean {
  return ((parent && parent.required ? parent.required : []) as string[]).indexOf(name) !== -1
}

function reqMark(required: boolean): string {
  return required ? ' <span class="field-req">*</span>' : ''
}

function wrap(path: string, label: string, required: boolean, controlHtml: string, help?: string): string {
  return (
    `<label class="field" data-holder="${esc(path)}">` +
    `<span class="field-label">${esc(label)}${reqMark(required)}</span>` +
    controlHtml +
    (help ? `<span class="field-help">${esc(help)}</span>` : '') +
    `</label>`
  )
}

/* ---------------------------------------------------------------- 控件 */

/* 控件初值：用户没传就用接口声明的默认值。
   不这么做的话，站点、币种、履约方式这些「有合理默认」的字段会是一片空白。 */
function initialRaw(resolved: Dict, value: unknown): unknown {
  if (value !== undefined && value !== null && value !== '') return value
  const def = resolved.default
  if (def === undefined || def === null || def === '') return ''
  if (Array.isArray(def)) return def.length ? def : ''
  if (typeof def === 'object') return Object.keys(def).length ? def : ''
  return def
}

function control(prop: Dict, path: string, value: unknown, required: boolean): string {
  const resolved = resolve(prop)
  const ui = xui(prop)
  const type = resolved.type || (resolved.properties ? 'object' : 'string')
  const raw = initialRaw(resolved, value)

  if (ui === 'file') {
    return (
      `<span class="file-drop">` +
      `<input type="file" data-path="${esc(path)}" data-type="file" ` +
      `data-filename-path="filename" accept=".csv,.json,.xlsx" />` +
      `${icon('upload')}` +
      `<span class="file-drop-title">选择文件</span>` +
      `<span class="file-drop-hint">CSV / JSON / Excel，不超过 5 MB</span>` +
      `</span>` +
      `<span class="field-help" data-file-name>还没有选择文件</span>`
    )
  }

  if (ui === 'competitor-lines') {
    return (
      `<textarea rows="6" spellcheck="false" data-path="${esc(path)}" data-type="competitors" ` +
      `placeholder="竞品 A | 25.99 | 4.2 | 380 | 盖子漏水&#10;竞品 B">${esc(competitorsToText(raw))}</textarea>`
    )
  }

  if (ui === 'kv-lines') {
    return (
      `<textarea rows="3" spellcheck="false" data-path="${esc(path)}" data-type="kv" ` +
      `placeholder="容量: 750ml&#10;材质: 304 不锈钢">${esc(kvToText(raw))}</textarea>`
    )
  }

  if (ui === 'keyword-lines') {
    return (
      `<textarea rows="3" spellcheck="false" data-path="${esc(path)}" data-type="keywords" ` +
      `placeholder="insulated water bottle | 12000 | 8&#10;leak proof bottle">${esc(keywordsToText(raw))}</textarea>`
    )
  }

  if (ui === 'lines') {
    return (
      `<textarea rows="3" data-path="${esc(path)}" data-type="lines">` +
      `${esc(Array.isArray(raw) ? raw.join('\n') : raw)}</textarea>`
    )
  }

  if (ui === 'report-picker' || ui === 'listing-picker') {
    const kind = ui === 'report-picker' ? 'reports' : 'listings'
    return (
      `<select data-path="${esc(path)}" data-type="text" data-picker="${kind}">` +
      `<option value="">读取中…</option></select>`
    )
  }

  if (resolved.enum) {
    const options = (resolved.enum as unknown[])
      .map((v) => {
        const selected = String(raw) === String(v) ? ' selected' : ''
        return `<option value="${esc(v)}"${selected}>${esc(labelValue(v))}</option>`
      })
      .join('')
    return `<select data-path="${esc(path)}" data-type="text">${options}</select>`
  }

  if (type === 'boolean') {
    return (
      `<label class="row gap-2 t-sm" style="height:32px">` +
      `<input type="checkbox" data-path="${esc(path)}" data-type="checkbox"` +
      `${raw === true ? ' checked' : ''} /> <span>${esc(titleOf(prop, path))}</span></label>`
    )
  }

  if (type === 'number' || type === 'integer') {
    const step = type === 'integer' ? '1' : 'any'
    return (
      `<input type="number" step="${step}" data-path="${esc(path)}" data-type="number" ` +
      `value="${raw === '' ? '' : esc(raw)}" placeholder="0" />`
    )
  }

  if (type === 'array' || type === 'object') {
    return (
      `<textarea rows="3" spellcheck="false" data-path="${esc(path)}" data-type="json" ` +
      `placeholder="[{ }]">${raw === '' ? '' : esc(JSON.stringify(raw, null, 2))}</textarea>`
    )
  }

  const maxLength = resolved.maxLength ? ` maxlength="${resolved.maxLength}"` : ''
  return `<input data-path="${esc(path)}" data-type="text" value="${esc(raw)}"${maxLength} />`
}

/* ---------------------------------------------------------------- 渲染 */

function renderFields(schema: Dict | null | undefined, _parent: unknown, prefix: string, values: Dict): string {
  const props: Dict = (schema && schema.properties) || {}
  return Object.keys(props)
    .filter((name) => xui(props[name]) !== 'hidden')
    .map((name) => {
      const prop = props[name]
      const path = prefix ? `${prefix}.${name}` : name
      const resolved = resolve(prop)
      const required = isRequired(schema, name)
      const value = values ? values[name] : undefined

      // 嵌套对象（例如 Listing 的商品事实）：平铺在同一张网格里，path 带上前缀
      if (resolved.properties && !xui(prop)) {
        const inner = renderFields(resolved, resolved, path, value || {})
        return (
          `<div class="field-span-2 schema-group"><div class="field-label">` +
          `${esc(titleOf(prop, name))}${reqMark(required)}</div>` +
          `<div class="grid-2">${inner}</div></div>`
        )
      }

      const help = helpOf(resolved, prop, name)
      const wide = isWide(prop)
      const cell = wrap(path, titleOf(prop, name), required, control(prop, path, value, required), help)
      return wide ? cell.replace('class="field"', 'class="field field-span-2"') : cell
    })
    .join('')
}

function isWide(prop: Dict): boolean {
  const ui = xui(prop)
  if (ui === 'file' || ui === 'competitor-lines' || ui === 'kv-lines' || ui === 'keyword-lines') return true
  const resolved = resolve(prop)
  return resolved.type === 'array' || resolved.type === 'object'
}

function helpOf(resolved: Dict, prop: Dict, _name: string): string {
  const ui = xui(prop)
  if (ui === 'competitor-lines') {
    return '按「名称 | 价格 | 评分 | 评论数 | 一条评论」写，只有名称必填。'
  }
  if (ui === 'keyword-lines') return '按「关键词 | 搜索量 | 排名」写，只填关键词也可以。'
  if (ui === 'kv-lines') return '每行一条，格式「键: 值」。'
  if (ui === 'lines') return '每行一条。'
  if (ui === 'report-picker') return '选一份已经跑出来的竞品分析报告。'
  if (ui === 'listing-picker') return '选一份已经生成的 Listing 草稿。'
  // 下拉框的选项本身就是说明，再补一句描述只是噪音。
  if (resolved.enum) return ''
  // 说明和标签一字不差就别印第二遍（纯噪音）
  const desc = String(resolved.description || '').trim()
  const label = String(resolved.title || '').trim()
  if (!desc) return ''
  if (desc === label || desc === label + '。') return ''
  return desc
}

export function render(schema: Dict | null | undefined, value?: Dict): string {
  schemaDefs = (schema && schema.$defs) || {}
  if (!schema || !schema.properties) return ''
  return `<div class="grid-2 schema-form">${renderFields(schema, schema, '', value || {})}</div>`
}

/* ---------------------------------------------------------------- 读回 */

export function read(scope: ParentNode | null | undefined, schema?: Dict): Dict {
  const out: Dict = {}
  if (!scope) return out
  schemaDefs = (schema && schema.$defs) || {}

  scope.querySelectorAll('[data-path]').forEach((el) => {
    const node = el as unknown as HTMLInputElement & {
      getAttribute(name: string): string | null
      disabled?: boolean
      checked?: boolean
      value?: string
    }
    const path = node.getAttribute('data-path') || ''
    const kind = node.getAttribute('data-type') || 'text'
    if (node.disabled) return

    if (kind === 'file') {
      const data = node.getAttribute('data-base64')
      if (!data) return
      setPath(out, path, data)
      const fileNamePath = node.getAttribute('data-filename-path')
      const fileName = node.getAttribute('data-filename')
      if (fileNamePath && fileName) setPath(out, fileNamePath, fileName)
      return
    }

    if (kind === 'checkbox') {
      setPath(out, path, Boolean(node.checked))
      return
    }

    const raw = String(node.value === undefined ? '' : node.value).trim()

    if (kind === 'number') {
      if (raw === '' || isNaN(Number(raw))) return
      setPath(out, path, Number(raw))
      return
    }
    if (kind === 'lines') {
      const list = splitLines(raw)
      if (list.length) setPath(out, path, list)
      return
    }
    if (kind === 'kv') {
      const obj: Record<string, string> = {}
      splitLines(raw).forEach((line) => {
        const at = line.indexOf(':')
        if (at > 0) obj[line.slice(0, at).trim()] = line.slice(at + 1).trim()
      })
      if (Object.keys(obj).length) setPath(out, path, obj)
      return
    }
    if (kind === 'competitors') {
      const list = parseCompetitors(raw)
      if (list.length) setPath(out, path, list)
      return
    }
    if (kind === 'keywords') {
      const list = parseKeywords(raw)
      if (list.length) setPath(out, path, list)
      return
    }
    if (kind === 'json') {
      if (raw === '') return
      try {
        setPath(out, path, JSON.parse(raw))
      } catch {
        throw fieldError(path, '这一格需要是合法的 JSON')
      }
      return
    }

    // 文本 / 下拉：空值不提交，交给服务端判断「必填」
    if (raw === '') return
    setPath(out, path, raw)
  })

  return out
}

function setPath(target: Dict, path: string, value: unknown): void {
  const parts = String(path).split('.')
  let node: Dict = target
  for (let i = 0; i < parts.length - 1; i += 1) {
    if (!node[parts[i]] || typeof node[parts[i]] !== 'object') node[parts[i]] = {}
    node = node[parts[i]]
  }
  node[parts[parts.length - 1]] = value
}

function fieldError(path: string, message: string): Error {
  const err = new Error(message) as Error & { field?: string }
  err.field = path
  return err
}

function splitLines(text: unknown): string[] {
  return String(text || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
}

/* ------------------------------------------- 竞品与关键词的文本格式 */

export function parseCompetitors(text: unknown): Dict[] {
  return splitLines(text)
    .map((line) => {
      const parts = line.split('|').map((s) => s.trim())
      const item: Dict = { name: parts[0], is_demo: false }
      if (!item.name) return null
      if (parts[1] && !isNaN(Number(parts[1]))) item.price = Number(parts[1])
      if (parts[2] && !isNaN(Number(parts[2]))) item.rating = Number(parts[2])
      if (parts[3] && !isNaN(Number(parts[3]))) item.review_count = Number(parts[3])
      if (parts[4]) {
        const review: Dict = { text: parts[4] }
        if (item.rating && item.rating >= 1) review.rating = item.rating
        item.reviews = [review]
      }
      return item
    })
    .filter(Boolean) as Dict[]
}

export function competitorsToText(list: unknown): string {
  return ((list || []) as Dict[])
    .map((c) => {
      const parts: unknown[] = [c.name || '']
      if (c.price !== undefined && c.price !== null) parts.push(c.price)
      else if (c.rating !== undefined && c.rating !== null) parts.push('')
      if (c.rating !== undefined && c.rating !== null) parts.push(c.rating)
      if (c.review_count !== undefined && c.review_count !== null) parts.push(c.review_count)
      const review =
        Array.isArray(c.reviews) && c.reviews[0] ? c.reviews[0].text || '' : ''
      if (review) parts.push(review)
      return parts.join(' | ')
    })
    .join('\n')
}

export function parseKeywords(text: unknown): Dict[] {
  return splitLines(text)
    .map((line) => {
      const parts = line.split('|').map((s) => s.trim())
      if (!parts[0]) return null
      const item: Dict = { keyword: parts[0] }
      if (parts[1] && !isNaN(Number(parts[1]))) item.search_volume = Number(parts[1])
      if (parts[2] && !isNaN(Number(parts[2]))) item.rank = Number(parts[2])
      return item
    })
    .filter(Boolean) as Dict[]
}

export function keywordsToText(list: unknown): string {
  return ((list || []) as Dict[])
    .map((k) => {
      const parts: unknown[] = [k.keyword || '']
      if (k.search_volume !== undefined && k.search_volume !== null) parts.push(k.search_volume)
      else if (k.rank !== undefined && k.rank !== null) parts.push('')
      if (k.rank !== undefined && k.rank !== null) parts.push(k.rank)
      return parts.join(' | ')
    })
    .join('\n')
}

export function kvToText(obj: unknown): string {
  if (!obj || typeof obj !== 'object') return ''
  return Object.keys(obj as Dict)
    .map((k) => `${k}: ${(obj as Dict)[k]}`)
    .join('\n')
}

/* ------------------------------------------------------------ 选择器数据 */

export async function hydratePickers(scope: ParentNode | null | undefined): Promise<void> {
  if (!scope) return
  const picks = scope.querySelectorAll('[data-picker]')
  if (!picks.length) return

  const wanted: Record<string, boolean> = {}
  picks.forEach((el) => {
    wanted[el.getAttribute('data-picker') || ''] = true
  })

  if (wanted.reports) {
    await fillPicker(scope, 'reports', '/api/reports?limit=20', (row) => ({
      value: row.report_id,
      label: `${row.product_name || '未命名商品'} · ${labelSite(row.marketplace)} · ${fmtTime(row.created_at)}`,
    }))
  }
  if (wanted.listings) {
    await fillPicker(scope, 'listings', '/api/listings?limit=20', (row) => ({
      value: row.listing_id,
      label: `${row.product_name || '未命名商品'} · ${labelSite(row.marketplace)} · ${fmtTime(row.created_at)}`,
    }))
  }
}

async function fillPicker(
  scope: ParentNode,
  kind: string,
  url: string,
  mapper: (row: Dict) => { value: unknown; label: string },
): Promise<void> {
  let items: Dict[] = []
  try {
    const data = await api.get<{ items?: Dict[] }>(url)
    items = data.items || []
  } catch {
    items = []
  }
  scope.querySelectorAll(`[data-picker="${kind}"]`).forEach((node) => {
    const el = node as unknown as HTMLSelectElement
    if (!items.length) {
      // 没有可选内容时不留一个空下拉：换成普通输入框，用户可以手填编号外的内容
      el.innerHTML = `<option value="">还没有可选的${kind === 'reports' ? '分析报告' : 'Listing 草稿'}</option>`
      el.disabled = true
      return
    }
    el.innerHTML =
      `<option value="">请选择…</option>` +
      items
        .map((row) => {
          const item = mapper(row)
          return `<option value="${esc(item.value)}">${esc(item.label)}</option>`
        })
        .join('')
  })
}

/** 「你需要准备」：取必填项（没有必填就取前几项）拼成一句话 */
export function describe(schema: Dict | null | undefined, opts?: { max?: number }): string {
  const max = (opts && opts.max) || 4
  const props: Dict = (schema && schema.properties) || {}
  const required: string[] = (schema && schema.required) || []
  const names = (required.length ? required : Object.keys(props)).filter((n) => {
    return props[n] && xui(props[n]) !== 'hidden'
  })
  return names
    .slice(0, max)
    .map((n) => titleOf(props[n], n))
    .join(' · ')
}

export const schemaFormApi = {
  render,
  read,
  describe,
  hydratePickers,
  parseCompetitors,
  competitorsToText,
}
