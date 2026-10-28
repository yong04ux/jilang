#!/usr/bin/env node
/**
 * 原语层语义对照：旧 `js/{icons,ui,labels}.js` ↔ 新 `src/lib/{icons,ui,labels}.ts`。
 *
 * 为什么要这一层：这些函数产出的是**字符串**，直接写进 innerHTML。
 * 差一个空格、一个类名、一个全角括号，页面就变形或文案变样，而 DOM 探针
 * 未必覆盖得到。迁移期间两套实现并存（旧页面捕获旧引用、新代码用 TS），
 * 只有输出逐字节一致，才敢说「行为没变」。
 *
 * 用法：node scripts/primitives-parity.mjs
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = dirname(here)

/* ---- 旧实现：塞进假 window 里执行 IIFE ---- */
const legacyWindow = {}
const load = (file) =>
  new Function('window', readFileSync(resolve(root, 'js', file), 'utf8'))(legacyWindow)
load('icons.js')
load('ui.js')
load('labels.js')

const oldIcon = legacyWindow.CPIcon
const oldUi = legacyWindow.CPUi
const oldLabel = legacyWindow.CPLabel

const newIcons = await import(pathToFileURL(resolve(root, 'src/lib/icons.ts')).href)
const newUi = await import(pathToFileURL(resolve(root, 'src/lib/ui.ts')).href)
const newLabels = await import(pathToFileURL(resolve(root, 'src/lib/labels.ts')).href)

let failed = 0
let passed = 0

function cmp(label, a, b) {
  const eq = typeof a === 'string' || typeof b === 'string' ? a === b : JSON.stringify(a) === JSON.stringify(b)
  if (eq) {
    passed += 1
    return true
  }
  failed += 1
  console.log(`  FAIL  ${label}`)
  console.log(`        旧：${JSON.stringify(a)}`)
  console.log(`        新：${JSON.stringify(b)}`)
  return false
}

/* ---------------------------------------------------------------- 图标 */
console.log('\n图标（' + oldIcon.names.length + ' 个 key + 别名 + 未知）')
cmp('names 数量一致', oldIcon.names.length, newIcons.names.length)
cmp('names 集合一致', [...oldIcon.names].sort(), [...newIcons.names].sort())

const iconCases = [...oldIcon.names, 'check_circle', 'cross', 'does_not_exist', '']
for (const name of iconCases) {
  cmp(`svg(${JSON.stringify(name)})`, oldIcon.svg(name), newIcons.svg(name))
  cmp(`svg(${JSON.stringify(name)}, 24)`, oldIcon.svg(name, 24), newIcons.svg(name, 24))
  cmp(
    `svg(${JSON.stringify(name)}, null, "x")`,
    oldIcon.svg(name, null, 'x'),
    newIcons.svg(name, null, 'x'),
  )
}
for (const name of iconCases) {
  cmp(`has(${JSON.stringify(name)})`, oldIcon.has(name), newIcons.has(name))
}

/* ------------------------------------------------------------------ UI */
console.log('\nUI 工具')
const escCases = [
  '<script>alert(1)</script>',
  `"'&<>`,
  '正常中文',
  '',
  null,
  undefined,
  0,
  123.45,
  { a: 1 },
]
for (const v of escCases) cmp(`esc(${JSON.stringify(v)})`, oldUi.esc(v), newUi.esc(v))

const statuses = [
  'queued', 'running', 'awaiting_approval', 'waiting_for_input', 'waiting_for_review',
  'partial', 'succeeded', 'failed', 'cancelling', 'cancelled', 'pending', 'skipped',
  'unknown_status', '',
]
for (const s of statuses) {
  cmp(`statusBadge(${JSON.stringify(s)})`, oldUi.statusBadge(s), newUi.statusBadge(s))
  cmp(`statusLabel(${JSON.stringify(s)})`, oldUi.statusLabel(s), newUi.statusLabel(s))
}

for (const ms of [null, undefined, 0, 5, 999, 1000, 1234, 9999, 12345]) {
  cmp(`fmtMs(${ms})`, oldUi.fmtMs(ms), newUi.fmtMs(ms))
  cmp(`fmtDuration(${ms})`, oldUi.fmtDuration(ms), newUi.fmtDuration(ms))
}
for (const b of [0, 250, 1024]) cmp(`fmtBytes(${b})`, oldUi.fmtBytes(b), newUi.fmtBytes(b))
for (const t of ['', null, undefined, '中文', 'a'.repeat(10)]) {
  cmp(`byteLen(${JSON.stringify(t)})`, oldUi.byteLen(t), newUi.byteLen(t))
}
const times = [null, undefined, '', 'not-a-date', '2026-10-28T08:00:00Z', '2026-01-05T03:04:05Z']
for (const t of times) cmp(`fmtTime(${JSON.stringify(t)})`, oldUi.fmtTime(t), newUi.fmtTime(t))

cmp('mockFlag()', oldUi.mockFlag(), newUi.mockFlag())
cmp('STATUS 键集合', Object.keys(oldUi.STATUS).sort(), Object.keys(newUi.STATUS).sort())

/* -------------------------------------------------------------- 标签层 */
console.log('\n文案标签')
const siteCases = ['US', 'us', 'GB', 'UK', 'JP', 'XX', '', null, undefined]
for (const c of siteCases) cmp(`site(${JSON.stringify(c)})`, oldLabel.site(c), newLabels.site(c))

const langCases = ['en-US', 'en_GB', 'de-DE', 'es-MX', 'ja', 'zh', 'xx-YY', '', null]
for (const c of langCases) cmp(`language(${JSON.stringify(c)})`, oldLabel.language(c), newLabels.language(c))

const platformCases = ['amazon', 'AMAZON', 'ebay', 'walmart', 'shopee', 'mercadolibre', 'taobao', '', null]
for (const c of platformCases) {
  cmp(`platform(${JSON.stringify(c)})`, oldLabel.platform(c), newLabels.platform(c))
}

const levelCases = ['high', 'medium', 'low', 'HIGH', 'weird', '', null]
for (const c of levelCases) cmp(`level(${JSON.stringify(c)})`, oldLabel.level(c), newLabels.level(c))

const fieldCases = [
  'name', 'title', 'specifications.材质', 'bullet[1]', 'bullets[12]', 'own_price',
  'unknown_field', 'a.b.c', '', null,
]
for (const c of fieldCases) cmp(`field(${JSON.stringify(c)})`, oldLabel.field(c), newLabels.field(c))

const valueCases = [
  'zh-CN', 'en-US', 'short', 'medium', 'long', 'fba', 'fbm', 'self', 'manual', 'demo',
  'import', 'amazon', 'US', 'mystery', '', null, undefined,
]
for (const c of valueCases) cmp(`value(${JSON.stringify(c)})`, oldLabel.value(c), newLabels.value(c))

const taskTypes = [
  'competitor_analysis', 'listing_generation', 'data_import', 'agent_workflow',
  'skill_run', 'publish_listing', 'report_export', 'store_sync', 'nope',
]
for (const c of taskTypes) {
  cmp(`taskType(${c})`, oldLabel.taskType(c), newLabels.taskType(c))
  cmp(`taskResult(${c})`, oldLabel.taskResult(c), newLabels.taskResult(c))
}

const orderCases = ['pending', 'unshipped', 'partially_shipped', 'shipped', 'delivered',
  'cancelled', 'refunded', 'weird', '', null]
for (const c of orderCases) {
  cmp(`orderStatus(${JSON.stringify(c)})`, oldLabel.orderStatus(c), newLabels.orderStatus(c))
  cmp(`orderTone(${JSON.stringify(c)})`, oldLabel.orderTone(c), newLabels.orderTone(c))
}
const returnCases = ['pending', 'processing', 'refunded', 'rejected', 'weird', '', null]
for (const c of returnCases) {
  cmp(`returnStatus(${JSON.stringify(c)})`, oldLabel.returnStatus(c), newLabels.returnStatus(c))
  cmp(`returnTone(${JSON.stringify(c)})`, oldLabel.returnTone(c), newLabels.returnTone(c))
}

/* --------------------------------------------------------------- 汇总 */
console.log('─'.repeat(56))
if (failed) {
  console.error(`\n原语层不一致：${failed} 项（共 ${passed + failed} 项）\n`)
  process.exit(1)
}
console.log(`\n原语层输出逐字节一致：${passed} 项\n`)
