// 登录后逐页截图：自动注册临时账号，捕获真实数据界面
// 用法：node scripts/ui_shots_auth.mjs <base> <outDir>
import { spawn } from 'node:child_process'
import { writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8000'
const OUT_DIR = process.argv[3] || join(tmpdir(), 'cp-shots')
const PAGES = (process.argv[4] || '/workbench,/dashboard,/tasks,/competitors,/listings,/data,/skills')
  .split(',').map((s) => s.trim()).filter(Boolean)
const PORT = 9339
const profile = join(tmpdir(), `cp-edge-shots-${Date.now()}`)
mkdirSync(OUT_DIR, { recursive: true })

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1440,960', 'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function main() {
  let target
  for (let i = 0; i < 60; i += 1) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
      target = list.find((t) => t.type === 'page')
      if (target) break
    } catch {}
    await sleep(250)
  }
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
  }
  await new Promise((r) => (ws.onopen = r))
  const send = (method, params = {}) => new Promise((resolve) => {
    id += 1; pending.set(id, resolve); ws.send(JSON.stringify({ id, method, params }))
  })
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description)
    return r.result?.result?.value
  }

  await send('Page.enable'); await send('Runtime.enable')
  await send('Page.navigate', { url: BASE + '/workbench' })
  await sleep(1800)

  const loginUser = process.env.CROSSPILOT_SHOT_USER
  const loginPassword = process.env.CROSSPILOT_SHOT_PASSWORD
  const username = loginUser || 'shot_' + Date.now().toString(36)
  if (loginUser) {
    const status = await ev(`fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: ${JSON.stringify(loginUser)}, password: ${JSON.stringify(loginPassword || '')} })
    }).then(r => r.status)`)
    if (status !== 200) throw new Error('登录失败，检查 CROSSPILOT_SHOT_USER / PASSWORD')
  } else {
    await ev(`fetch('/api/auth/register', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: ${JSON.stringify(username)}, password: 'shot-password-123' })
    }).then(r => r.status)`)
  }

  // 造一条真实任务，让 Dashboard / 任务中心有数据可看
  await ev(`fetch('/api/demo/dataset').then(r => r.json()).then(d => fetch('/api/analyze', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...d.analysis_request, product_name: 'EcoSip Insulated Water Bottle' })
  })).then(r => r.status)`)

  for (const raw of PAGES) {
    // 支持 "/workbench#drawer" 这种写法：进页面后打开导航抽屉再截图
    const openDrawer = raw.endsWith('#drawer')
    const path = openDrawer ? raw.slice(0, -'#drawer'.length) : raw
    await send('Page.navigate', { url: BASE + path })
    await sleep(2200)
    if (openDrawer) {
      await ev('document.getElementById("nav-open").click()')
      await sleep(500)
    }
    const suffix = openDrawer ? '-drawer' : ''
    const pathOnly = path.split('?')[0].split('#')[0]
    const name = (pathOnly === '/' ? 'root' : pathOnly.replace(/\//g, '_').replace(/^_/, '')) + suffix + '.png'
    const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(join(OUT_DIR, name), Buffer.from(cap.result.data, 'base64'))
    console.log('shot', raw, '->', join(OUT_DIR, name))
  }

  console.log('user:', username)
  ws.close(); edge.kill(); await sleep(300)
  try { (await import('node:fs')).rmSync(profile, { recursive: true, force: true }) } catch {}
  console.log('SHOTS OK')
}
main().catch((e) => { console.error('SHOTS FAIL:', e.message); edge.kill(); process.exit(1) })
