#!/usr/bin/env node
/**
 * 串行跑前端探针。任一失败即为非零退出。
 *
 * 用法：node scripts/probe-all.mjs [base] [filter]
 *   base    默认 http://127.0.0.1:8200（与多数探针的默认端口一致）
 *   filter  只跑文件名包含该子串的探针
 *
 * 说明：这些探针是「无第三方依赖的 Edge CDP 脚本」（Node >= 22 的原生 WebSocket +
 * 本机 Microsoft Edge headless）。它们断言的是 DOM 契约，所以只要 id/class
 * 不变就应当继续通过 —— 这正是「无功能回退」的自动化证据。
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const base = process.argv[2] || 'http://127.0.0.1:8200'
const filter = process.argv[3] || ''

/** 接受 base 作为第一个参数的探针（顺序大致按页面） */
const PROBES = [
  'ui_workbench_home.mjs',
  'ui_workbench_v2.mjs',
  'ui_flows_v2.mjs',
  'ui_interactions.mjs',
  'ui_data_flow_v2.mjs',
  'ui_listing_flow_v2.mjs',
  'ui_settings_models.mjs',
  'ui_skills_shot.mjs',
  'ui_store_shot.mjs',
]

/** 端口硬编码在脚本里、不接受 base 的探针（单独提示，不参与本次汇总） */
const HARDCODED = ['ui_check_logout.mjs', 'ui_check_account_switch.mjs', 'ui_diag_store.mjs']

const run = (file) =>
  new Promise((resolve) => {
    const child = spawn(process.execPath, [join(here, file), base], {
      stdio: 'inherit',
      env: { ...process.env, CP_BASE: base },
    })
    child.on('exit', (code) => resolve(code ?? 1))
  })

const list = PROBES.filter((f) => f.includes(filter) && existsSync(join(here, f)))
if (!list.length) {
  console.error(`没有匹配的探针${filter ? `（filter=${filter}）` : ''}`)
  process.exit(1)
}

console.log(`\n探针目标：${base}`)
console.log(`共 ${list.length} 个：${list.join(' ')}\n`)

const failed = []
for (const file of list) {
  console.log('\n' + '='.repeat(60))
  console.log('▶ ' + file)
  console.log('='.repeat(60))
  const code = await run(file)
  if (code !== 0) failed.push(file)
}

console.log('\n' + '='.repeat(60))
if (failed.length) {
  console.log(`探针未通过 ${failed.length}/${list.length}：`)
  for (const f of failed) console.log('  - ' + f)
  const skipped = HARDCODED.filter((f) => existsSync(join(here, f)))
  if (skipped.length) {
    console.log(`\n另有端口写死的探针需手动单独跑：${skipped.join(', ')}`)
  }
  process.exit(1)
}
console.log(`全部通过 ${list.length}/${list.length}`)
const skipped = HARDCODED.filter((f) => existsSync(join(here, f)))
if (skipped.length) {
  console.log(`\n另有端口写死的探针需手动单独跑：${skipped.join(', ')}`)
}
