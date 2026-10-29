/**
 * A/B 视觉基线：同一页面「带 tailwind.css」与「不带 tailwind.css」各截一张，
 * 逐字节比对。
 *
 * 用途：Tailwind 的 preflight 会给所有元素重设 margin/padding/border，
 * 而本项目 4526 行 CSS 是无层的、只在「自己写到的属性」上胜出 ——
 * 凡是原本依赖浏览器默认值的样式（标题字号、p 段间距、button 外观），
 * 都可能被 preflight 悄悄改掉。肉眼扫十张截图靠不住，这个脚本给的是确定答案。
 *
 * ⚠️ 定位：**接入期的一次性守卫**，不是常规检查。
 * 它成立的前提是「页面样式完全不依赖 Tailwind」。外壳与已迁移页面现在依赖
 * Tailwind，摘掉它必然有差异，所以别把它挂进 CI 或必跑清单 —— 它只在
 * 新接入某一层样式时，用来证明「引入这一层没有改动既有页面」。
 *
 * 用法：node scripts/tailwind-ab.mjs http://127.0.0.1:8000
 * 退出码 1 表示存在像素差异（需要人工看 before/after 图）。
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const BASE = process.argv[2] || 'http://127.0.0.1:8000'
const OUT = join(process.cwd(), '.ab')
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const PORT = 9210 + (Date.now() % 40)

const PAGES = [
  ['dashboard', '/dashboard'],
  ['settings', '/settings'],
  ['skills', '/skills'],
  ['workbench', '/workbench'],
  ['stores', '/stores'],
  ['tasks', '/tasks'],
  ['data', '/data'],
  ['agents', '/agents'],
]

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

mkdirSync(OUT, { recursive: true })
const profile = join(tmpdir(), `cp-ab-${Date.now()}`)
const edge = spawn(
  EDGE,
  [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    '--no-first-run',
    '--window-size=1440,1000',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    'about:blank',
  ],
  { stdio: 'ignore' },
)

let target
for (let i = 0; i < 100; i++) {
  try {
    const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
    target = list.find((t) => t.type === 'page')
    if (target) break
  } catch {
    /* 还没起来 */
  }
  await sleep(250)
}
if (!target) {
  console.error('无法连接浏览器调试端口')
  process.exit(2)
}

const ws = new WebSocket(target.webSocketDebuggerUrl)
let id = 0
const pending = new Map()
ws.onmessage = (e) => {
  const m = JSON.parse(e.data)
  if (m.id && pending.has(m.id)) {
    pending.get(m.id)(m)
    pending.delete(m.id)
  }
}
await new Promise((r) => (ws.onopen = r))
const send = (method, params = {}) =>
  new Promise((r) => {
    id += 1
    pending.set(id, r)
    ws.send(JSON.stringify({ id, method, params }))
  })
const ev = async (expr) => {
  const r = await send('Runtime.evaluate', {
    expression: expr,
    awaitPromise: true,
    returnByValue: true,
  })
  return r.result?.result?.value
}
const shot = async () => {
  const r = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  return r.result?.data || ''
}

await send('Page.enable')
await send('Runtime.enable')

// 登录：现注册，避免 /api/auth/demo 的 IP 限流把比对卡在登录门
await send('Page.navigate', { url: `${BASE}/dashboard` })
await sleep(2500)
const user = 'abcheck_' + Date.now().toString(36)
await ev(
  `fetch('/api/auth/register', {method:'POST', credentials:'same-origin',
     headers:{'Content-Type':'application/json'},
     body: JSON.stringify({ username: ${JSON.stringify(user)}, password: 'password123' }) }).then(r=>r.status)`,
)
await ev(`(async () => { await window.CPAuth.load(); window.dispatchEvent(new CustomEvent('cp:authenticated')); return 1 })()`)
await sleep(1200)

let diff = 0
const rows = []
for (const [name, path] of PAGES) {
  await send('Page.navigate', { url: BASE + path })
  await sleep(2600)

  const withTw = await shot()

  // 摘掉 tailwind.css 后再截
  await ev(`(() => {
    const links = Array.from(document.querySelectorAll('link[rel=stylesheet]'))
      .filter((l) => l.href.indexOf('/css/tailwind.css') !== -1)
    links.forEach((l) => l.remove())
    return links.length
  })()`)
  await sleep(500)
  const withoutTw = await shot()

  // 复原，避免影响下一页
  await ev(`(() => {
    const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '/css/tailwind.css?v=0'
    document.head.appendChild(l); return 1
  })()`)

  const same = withTw === withoutTw
  if (!same) {
    diff += 1
    writeFileSync(join(OUT, `${name}-with-tailwind.png`), Buffer.from(withTw, 'base64'))
    writeFileSync(join(OUT, `${name}-without-tailwind.png`), Buffer.from(withoutTw, 'base64'))
  }
  rows.push({ name, same, kb: Math.round(withTw.length / 1024) })
}

console.log('\n页面'.padEnd(14) + '带/不带 tailwind 是否一致'.padEnd(26) + '截图')
console.log('─'.repeat(58))
for (const r of rows) {
  console.log(r.name.padEnd(14) + (r.same ? '一致' : '有差异 → 见 .ab/').padEnd(24) + `${r.kb} KB`)
}
console.log('─'.repeat(58))
if (diff === 0) {
  console.log('\nA/B 视觉一致：preflight 未影响现有页面\n')
} else {
  console.log(`\n${diff} 个页面存在视觉差异，差异图已写入 ${OUT}\n`)
}

ws.close()
edge.kill()
await sleep(200)
try {
  rmSync(profile, { recursive: true, force: true })
} catch {
  /* 忽略 */
}
process.exit(diff === 0 ? 0 : 1)
