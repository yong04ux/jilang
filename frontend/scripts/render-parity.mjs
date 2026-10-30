#!/usr/bin/env node
/**
 * 渲染层语义对照：旧 `js/{schema-form,render}.js` ↔ 新 `src/lib/{schema-form,render}`。
 *
 * 这两个模块产出的是整块 HTML 字符串，直接塞进 innerHTML。
 * 少一个空格、错一个类名、漏一层转义，页面就变形或漏渲染，而探针只断言
 * 少数几个选择器，覆盖不到细节。所以这里对同一批输入逐字节比对输出。
 *
 * `read()` 用桩对象驱动（它只依赖 getAttribute / value / checked / disabled），
 * 因此「把 DOM 读回普通对象」这段最容易错的逻辑也能在 Node 里测。
 *
 * 用法：node scripts/render-parity.mjs
 */
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = dirname(here)

// 没有对照基线时跳过（脚本保留，fixture 仍有参考价值）
if (!existsSync(resolve(root, 'js'))) {
  console.log('\n跳过：frontend/js/ 已删除（），无对照基线\n')
  process.exit(0)
}

/* ---- 对照实现 ---- */
const legacyWindow = {}
const load = (file) =>
  new Function('window', readFileSync(resolve(root, 'js', file), 'utf8'))(legacyWindow)
load('icons.js')
load('ui.js')
load('labels.js')
load('api.js')
load('schema-form.js')
load('render.js')

const oldForm = legacyWindow.CPSchemaForm
const oldRender = legacyWindow.CPRender

const newForm = await import(
  pathToFileURL(resolve(root, 'src/lib/schema-form/schema-form.ts')).href
)
const newRender = await import(pathToFileURL(resolve(root, 'src/lib/render/render.ts')).href)

let failed = 0
let passed = 0

function same(label, a, b) {
  if (a === b) {
    passed += 1
    return true
  }
  failed += 1
  console.log(`  FAIL  ${label}`)
  console.log(`        旧：${JSON.stringify(typeof a === 'string' ? a.slice(0, 400) : a)}`)
  console.log(`        新：${JSON.stringify(typeof b === 'string' ? b.slice(0, 400) : b)}`)
  // 找第一个不同处，比整段更易读
  if (typeof a === 'string' && typeof b === 'string') {
    let i = 0
    while (i < Math.min(a.length, b.length) && a[i] === b[i]) i += 1
    console.log(`        首个差异在 ${i}：旧「${a.slice(i, i + 60)}」 新「${b.slice(i, i + 60)}」`)
  }
  return false
}

/* ==================================================================
   一、schema-form：覆盖每一种控件与分支
   ================================================================== */

const defsSchema = {
  $defs: {
    Price: { type: 'number', title: '价格', description: '含税单价' },
    Facts: {
      type: 'object',
      title: '商品事实',
      properties: {
        material: { type: 'string', title: '材质' },
        capacity: { type: 'string', title: '容量' },
      },
      required: ['material'],
    },
  },
}

const fullSchema = {
  type: 'object',
  $defs: defsSchema.$defs,
  required: ['product_name', 'own_price'],
  properties: {
    product_name: { type: 'string', title: '商品名称', maxLength: 120 },
    own_price: { $ref: '#/$defs/Price' },
    own_specs: { type: 'object', title: '你的规格', properties: { a: { type: 'string' } } },
    own_key_features: { type: 'array', items: { type: 'string' }, title: '你的卖点' },
    marketplace: { type: 'string', enum: ['US', 'JP', 'unknown_code'], default: 'US' },
    fulfillment: { type: 'string', enum: ['fba', 'fbm', 'self'], default: 'fba' },
    is_demo: { type: 'boolean', title: '示例数据' },
    rating: { type: 'number', title: '评分' },
    review_count: { type: 'integer', title: '评论数' },
    specs_text: { type: 'string', 'x-ui': 'kv-lines', title: '规格' },
    features_text: { type: 'string', 'x-ui': 'lines', title: '卖点逐行' },
    keywords_text: { type: 'string', 'x-ui': 'keyword-lines', title: '关键词' },
    competitors: { type: 'string', 'x-ui': 'competitor-lines', title: '竞品' },
    data_file: { type: 'string', 'x-ui': 'file', title: '数据文件' },
    report_id: { type: 'string', 'x-ui': 'report-picker', title: '分析报告' },
    listing_id: { type: 'string', 'x-ui': 'listing-picker', title: 'Listing' },
    hidden_field: { type: 'string', 'x-ui': 'hidden' },
    facts: { $ref: '#/$defs/Facts' },
    nullable_note: { anyOf: [{ type: 'string', title: '备注' }, { type: 'null' }] },
    same_desc: { type: 'string', title: '语气', description: '语气' },
    sentence_desc: { type: 'string', title: '语言', description: '语言。' },
    length_hint: { type: 'string', title: '篇幅', description: '最多 200 个字' },
    no_title_field: { type: 'string' },
  },
}

const formValues = {
  product_name: 'EcoSip 保温杯 <750ml>',
  own_price: 22.9,
  marketplace: 'JP',
  is_demo: true,
  rating: 4.5,
  review_count: 128,
  specs_text: { 容量: '750ml', 材质: '304 不锈钢' },
  features_text: ['a', 'b'],
  keywords_text: [{ keyword: 'water bottle', search_volume: 12000, rank: 8 }],
  competitors: [
    { name: 'A', price: 25.99, rating: 4.2, review_count: 380, reviews: [{ text: '漏水' }] },
    { name: 'B' },
  ],
  facts: { material: '不锈钢', capacity: '750ml' },
}

console.log('\nschema-form.render（覆盖全部控件类型）')
same(
  'render(fullSchema, formValues)',
  oldForm.render(fullSchema, formValues),
  newForm.render(fullSchema, formValues),
)
same('render(fullSchema) 无值', oldForm.render(fullSchema), newForm.render(fullSchema))
same('render(null)', oldForm.render(null), newForm.render(null))
same('render({})', oldForm.render({}), newForm.render({}))
same(
  'render(空 properties)',
  oldForm.render({ type: 'object', properties: {} }),
  newForm.render({ type: 'object', properties: {} }),
)
same('render(全隐藏字段)', oldForm.render({ properties: { a: { 'x-ui': 'hidden', type: 'string' } } }),
  newForm.render({ properties: { a: { 'x-ui': 'hidden', type: 'string' } } }))

console.log('\nschema-form.describe')
for (const opts of [undefined, { max: 2 }, { max: 10 }]) {
  same(
    `describe(fullSchema, ${JSON.stringify(opts)})`,
    oldForm.describe(fullSchema, opts),
    newForm.describe(fullSchema, opts),
  )
}
same('describe(null)', oldForm.describe(null), newForm.describe(null))
same(
  'describe(无 required)',
  oldForm.describe({ properties: { a: { title: '甲' }, b: { type: 'string' } } }),
  newForm.describe({ properties: { a: { title: '甲' }, b: { type: 'string' } } }),
)

console.log('\nschema-form 竞品文本互转')
const competitorTexts = [
  '',
  'A | 25.99 | 4.2 | 380 | 盖子漏水',
  'A | 25.99 | 4.2 | 380 | 盖子漏水\nB | 18.5',
  'C\n\n  D  |  abc | 4  ',
  '   | 1 | 2 | 3 | 4 ',
  'E|31|4.6|2310|Started leaking after a month.\nF|0|0|0|',
]
for (const text of competitorTexts) {
  same(
    `parseCompetitors(${JSON.stringify(text)})`,
    JSON.stringify(oldForm.parseCompetitors(text)),
    JSON.stringify(newForm.parseCompetitors(text)),
  )
}
const competitorLists = [
  [],
  [{ name: 'A', price: 25.99, rating: 4.2, review_count: 380, reviews: [{ text: 'x' }] }],
  [{ name: 'B', rating: 4.1 }],
  [{ name: 'C', reviews: [] }],
  [{ name: 'D', price: 0, rating: 0 }],
]
for (const list of competitorLists) {
  same(
    `competitorsToText(${JSON.stringify(list)})`,
    oldForm.competitorsToText(list),
    newForm.competitorsToText(list),
  )
}

/* ---------------------------------------------------------------- read() */

const stubEl = (attrs, props = {}) => ({
  getAttribute: (name) => (Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null),
  value: props.value,
  disabled: props.disabled,
  checked: props.checked,
})

const readCases = [
  {
    label: '文本 + 数字 + 空值',
    els: [
      stubEl({ 'data-path': 'title', 'data-type': 'text' }, { value: '  你好  ' }),
      stubEl({ 'data-path': 'price', 'data-type': 'number' }, { value: ' 22.9 ' }),
      stubEl({ 'data-path': 'bad_number', 'data-type': 'number' }, { value: 'abc' }),
      stubEl({ 'data-path': 'empty', 'data-type': 'text' }, { value: '   ' }),
      stubEl({ 'data-path': 'integer', 'data-type': 'number' }, { value: '12' }),
    ],
  },
  {
    label: '嵌套路径',
    els: [
      stubEl({ 'data-path': 'product.name', 'data-type': 'text' }, { value: '杯子' }),
      stubEl({ 'data-path': 'product.specs.material', 'data-type': 'text' }, { value: '钢' }),
      stubEl({ 'data-path': 'simple', 'data-type': 'text' }, { value: 'v' }),
    ],
  },
  {
    label: '多行 / 键值 / 竞品 / 关键词',
    els: [
      stubEl({ 'data-path': 'lines', 'data-type': 'lines' }, { value: ' a \n\n b ' }),
      stubEl({ 'data-path': 'kv', 'data-type': 'kv' }, { value: '容量: 750ml\n材质: 304\n无冒号行' }),
      stubEl({ 'data-path': 'comps', 'data-type': 'competitors' }, { value: 'A | 25.99\nB' }),
      stubEl({ 'data-path': 'kws', 'data-type': 'keywords' }, { value: 'bottle | 12000 | 8\nproof' }),
      stubEl({ 'data-path': 'empty_lines', 'data-type': 'lines' }, { value: '   ' }),
    ],
  },
  {
    label: 'JSON / 布尔 / 文件 / 禁用',
    els: [
      stubEl({ 'data-path': 'obj', 'data-type': 'json' }, { value: '{"a":1,"b":[2]}' }),
      stubEl({ 'data-path': 'arr', 'data-type': 'json' }, { value: '[1,2]' }),
      stubEl({ 'data-path': 'flag', 'data-type': 'checkbox' }, { checked: true }),
      stubEl({ 'data-path': 'flag2', 'data-type': 'checkbox' }, { checked: false }),
      stubEl(
        { 'data-path': 'file_data', 'data-type': 'file', 'data-base64': 'QUJD', 'data-filename-path': 'filename', 'data-filename': 'a.csv' },
        {},
      ),
      stubEl({ 'data-path': 'no_data_file', 'data-type': 'file' }, {}),
      stubEl({ 'data-path': 'off', 'data-type': 'text' }, { value: 'ignored', disabled: true }),
      stubEl({ 'data-path': 'sel', 'data-type': 'text' }, { value: 'US' }),
    ],
  },
]

console.log('\nschema-form.read（桩对象驱动）')
for (const c of readCases) {
  const scope = { querySelectorAll: () => c.els }
  same(`read: ${c.label}`, JSON.stringify(oldForm.read(scope)), JSON.stringify(newForm.read(scope)))
}
same('read(null)', JSON.stringify(oldForm.read(null)), JSON.stringify(newForm.read(null)))

/* 非法 JSON 必须抛同一句话、同一个 field */
{
  const scope = { querySelectorAll: () => [stubEl({ 'data-path': 'x.y', 'data-type': 'json' }, { value: '{bad' })] }
  let oldErr = ''
  let newErr = ''
  try {
    oldForm.read(scope)
  } catch (e) {
    oldErr = `${e.message}|${e.field}`
  }
  try {
    newForm.read(scope)
  } catch (e) {
    newErr = `${e.message}|${e.field}`
  }
  same('read: 非法 JSON 的报错', oldErr, newErr)
}

/* ==================================================================
   二、render.js：报告与 Listing
   ================================================================== */

const reportFull = {
  product_name: 'EcoSip 保温杯 750ml',
  platform: 'amazon',
  marketplace: 'US',
  created_at: '2026-10-28T08:00:00Z',
  engine: 'deepseek',
  data_provenance: { is_demo: false, competitor_count: 3, review_sample_count: 5, keyword_count: 4 },
  price_analysis: {
    min_price: 18.5,
    median_price: 25.99,
    max_price: 31,
    own_price: 22.9,
    currency: 'USD',
    own_position: 'within_range',
    compared_count: 3,
    claims: [
      {
        evidence_kind: 'fact',
        statement: '自有价格落在竞品区间内',
        evidence: [
          { competitor: 'AquaPeak', field: 'price', quote: '25.99' },
          { competitor: 'TrailMate', field: 'review_count' },
          { competitor: 'X' },
          { competitor: 'Y', quote: '被截断的第 4 条' },
        ],
      },
    ],
  },
  competitor_snapshots: [
    {
      name: 'AquaPeak', is_demo: true, brand: 'Aqua', missing_fields: ['material', 'certifications'],
      price: 25.99, currency: 'USD', rating: 4.4, review_count: 1842, review_samples: 12,
      data_completeness: 0.83,
    },
    { name: 'Bare', is_demo: false, rating: null, review_count: null, review_samples: 0, data_completeness: 0 },
  ],
  review_insights: {
    total_samples: 5,
    pain_points: [
      {
        label: '漏水', frequency: 3, share: 0.6, description: '盖子密封差',
        samples: [{ competitor: 'A', quote: '漏水' }, { competitor: 'B', quote: '漏' }, { competitor: 'C', quote: '第三条' }],
      },
    ],
    low_rating_themes: [{ label: '清洗难', frequency: 2, share: 0.4, description: '口径窄', samples: [] }],
    needs: [], purchase_concerns: [],
    limitations: [],
  },
  keyword_analysis: {
    available: true, total_keywords: 4, with_metrics: 2,
    opportunities: [
      { keyword: 'insulated bottle', search_volume: 12000, rank: 8, opportunity_score: 7.25, basis: '搜索量高' },
      { keyword: 'leak proof', search_volume: null, rank: null, opportunity_score: null, basis: '' },
    ],
  },
  differentiation_opportunities: [
    { angle: '密封', priority: 'high', confidence: 'medium', rationale: '痛点集中', requires_confirmation: true },
    { angle: '轻量', priority: 'low', confidence: 'low', rationale: '', requires_confirmation: false },
  ],
  content_recommendations: [
    { evidence_kind: 'inference', area: 'title', recommendation: '强调防漏', rationale: '评论显示' },
  ],
  warnings: ['样本偏少', '价格含税与否不明'],
  limitations: ['竞品数据来自手动录入', '未核验真实销量'],
}

const reportMinimal = {}
const reportNoPrice = { product_name: 'X', data_provenance: {}, review_insights: {}, keyword_analysis: {} }

const listingFull = {
  product_name: 'EcoSip 保温杯',
  platform: 'amazon',
  marketplace: 'US',
  language: 'en-US',
  created_at: '2026-10-28T08:00:00Z',
  title: 'EcoSip Insulated Bottle 750ml',
  bullets: [
    { headline: 'KEEPS COLD', body: '24 hours cold', character_count: 12 },
    { headline: '防漏', body: '密封圈', character_count: 6 },
  ],
  description: '第一段\n第二段',
  search_terms: 'insulated bottle leak proof',
  data_provenance: { is_demo: true },
  quality_check: {
    passed: false,
    issues: [
      { severity: 'error', location: 'bullets[1]', message: '出现禁用词', suggestion: '删掉' },
      { severity: 'warning', location: 'title', message: '偏长' },
      { severity: 'info', message: '仅提示' },
    ],
    section_lengths: [
      { section: 'title', length: 31, limit: 200, within_limit: true },
      { section: 'description', length: 400, limit: 300, within_limit: false },
      { section: 'search_terms', length: 30, limit: null, within_limit: true },
    ],
    policy_disclaimer: '禁词清单为内部示例',
  },
  pending_confirmations: ['材质需确认', '认证需确认'],
  fact_ledger: [
    { statement: '750ml', source: 'specifications.容量' },
    { statement: '304 不锈钢', source: 'material' },
  ],
  limitations: ['未经平台审核'],
}

const listingMinimal = {}

console.log('\nrender.renderReport')
same('报告（完整）', oldRender.renderReport(reportFull), newRender.renderReport(reportFull))
same(
  '报告（带 actions）',
  oldRender.renderReport(reportFull, { actions: '<button class="btn">导出</button>' }),
  newRender.renderReport(reportFull, { actions: '<button class="btn">导出</button>' }),
)
same('报告（空对象）', oldRender.renderReport(reportMinimal), newRender.renderReport(reportMinimal))
same('报告（无价格/无洞察）', oldRender.renderReport(reportNoPrice), newRender.renderReport(reportNoPrice))

console.log('\nrender.renderListing')
same('Listing（完整）', oldRender.renderListing(listingFull), newRender.renderListing(listingFull))
same(
  'Listing（带 actions）',
  oldRender.renderListing(listingFull, { actions: '<button class="btn">保存新版本</button>' }),
  newRender.renderListing(listingFull, { actions: '<button class="btn">保存新版本</button>' }),
)
same('Listing（空对象）', oldRender.renderListing(listingMinimal), newRender.renderListing(listingMinimal))

console.log('\nrender 小工具')
for (const [v, c] of [[null, undefined], [undefined, 'USD'], [22.9, 'USD'], [31, 'CNY'], [0, undefined]]) {
  same(`money(${v}, ${c})`, oldRender.money(v, c), newRender.money(v, c))
}
for (const k of ['fact', 'statistic', 'inference', 'assumption', 'unknown']) {
  same(`kindBadge(${k})`, oldRender.kindBadge(k), newRender.kindBadge(k))
}
same(
  'POSITION_LABEL 键集合',
  JSON.stringify(Object.keys(oldRender.POSITION_LABEL).sort()),
  JSON.stringify(Object.keys(newRender.POSITION_LABEL).sort()),
)

/* --------------------------------------------------------------- 汇总 */
console.log('─'.repeat(56))
if (failed) {
  console.error(`\n渲染层不一致：${failed} 项（共 ${passed + failed} 项）\n`)
  process.exit(1)
}
console.log(`\n渲染层输出逐字节一致：${passed} 项\n`)
