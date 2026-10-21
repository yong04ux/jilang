// 登录后逐页截图：用 demo 账号登录，遍历核心页面，捕获控制台错误并截图。
// 用法：node scripts/ui_shots_auth_v2.mjs <base> <outDir>
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8200'
const OUT = process.argv[3] || join(tmpdir(), 'cp-shots')
const USER = process.argv[4] || 'demo'
const PASS = process.argv[5] || 'demo-pass-1234'
const PORT = 9350
const profile = join(tmpdir(), `cp-edge-auth-${Date.now()}`)

mkdirSync(OUT, { recursive: true })

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1440,960', 'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function main() {
  let target
  for (let i = 0; i < 80; i += 1) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()
      target = list.find((t) => t.type === 'page')
      if (target) break
    } catch {}
    await sleep(250)
  }
  if (!target) throw new Error('无法连接 Edge DevTools')

  const ws = new WebSocket(target.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  let errors = []
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
    if (m.method === 'Runtime.exceptionThrown') {
      errors.push(m.params.exceptionDetails.exception?.description || 'exception')
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      errors.push(m.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
    }
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

  // 1) 登录：直接用同源 fetch 建立 Cookie 会话（避免依赖表单时序）
  await send('Page.navigate', { url: BASE + '/dashboard' })
  await sleep(1500)
  const login = await ev(`fetch('/api/auth/login', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ${JSON.stringify(USER)}, password: ${JSON.stringify(PASS)} }),
  }).then(r => r.status)`)
  await sleep(800)
  await send('Page.navigate', { url: BASE + '/dashboard' })
  await sleep(2000)
  const loggedIn = await ev('!document.getElementById("auth-gate") || document.getElementById("auth-gate").hidden')
  console.log('login status:', login, '| logged in:', loggedIn)
  if (!loggedIn) {
    const msg = await ev('(document.querySelector("#auth-error")||{}).textContent || ""')
    console.log('login error:', msg)
  }

  const pages = ['/dashboard', '/workbench', '/tasks', '/competitors', '/listings', '/data', '/agents', '/skill', '/stores', '/settings']
  for (const path of pages) {
    const real = path === '/skill' ? '/skills' : path
    errors = []
    await send('Page.navigate', { url: BASE + real })
    await sleep(2200)
    const title = await ev('document.title')
    const bodyLen = await ev('document.body.innerText.length')
    const hasError = await ev('!!document.querySelector(".callout-danger")')
    const name = real.replace(/\//g, '') || 'root'
    const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(cap.result.data, 'base64'))
    console.log(`${real}  title=${title}  textLen=${bodyLen}  callout-danger=${hasError}  errors=${errors.length}`)
    if (errors.length) console.log('   ' + errors.slice(0, 3).join('\n   '))
  }

  ws.close(); edge.kill(); await sleep(400)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
  console.log('shots:', OUT)
}
main().catch((e) => { console.error('FAIL:', e.message); edge.kill(); process.exit(1) })
