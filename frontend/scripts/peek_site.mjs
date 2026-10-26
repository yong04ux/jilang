// 通用外部站点勘察探针：渲染、截图、导出结构
// 用法：node scripts/peek_site.mjs <url> <outPng> [waitMs]
import { spawn } from 'node:child_process'
import { writeFileSync, mkdirSync } from 'node:fs'
import { dirname } from 'node:path'

const URL_ = process.argv[2]
const OUT = process.argv[3] || 'peek.png'
const WAIT = Number(process.argv[4] || 9000)
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const PORT = 9800 + (Date.now() % 150)
const PROXY = 'http://127.0.0.1:55795'
const W = 1512
const H = 1200

mkdirSync(dirname(OUT), { recursive: true })

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
  `--proxy-server=${PROXY}`,
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${process.env.TEMP || '/tmp'}/cp-peek-${Date.now()}`,
  `--window-size=${W},${H}`, 'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function main() {
  let target
  for (let i = 0; i < 120; i += 1) {
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
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
  }
  await new Promise((r) => (ws.onopen = r))
  const send = (method, params = {}) => new Promise((res) => {
    id += 1; pending.set(id, res)
    ws.send(JSON.stringify({ id, method, params }))
  })
  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || 'eval failed')
    return r.result?.result?.value
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Page.navigate', { url: URL_ })
  await sleep(WAIT)

  const info = await evaluate(`(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2 && r.top < 4000; };
    const pick = (sel, n) => Array.from(document.querySelectorAll(sel)).filter(vis).slice(0, n).map((el) => (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 160));
    return {
      title: document.title,
      h: document.body.scrollHeight,
      h1: pick('h1', 4),
      h2: pick('h2', 8),
      h3: pick('h3', 12),
      tabs: pick('[role="tab"], .tab, [class*="tab"]', 20),
      buttons: pick('button, a[role="button"], [class*="btn"]', 30),
      cards: pick('[class*="card"], [class*="skill"], li', 20),
      inputs: pick('input, textarea', 10),
      text: (document.body.innerText || '').replace(/\\n{2,}/g, '\\n').slice(0, 2500),
    };
  })()`)
  console.log(JSON.stringify(info, null, 2))

  const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  writeFileSync(OUT, Buffer.from(cap.result.data, 'base64'))
  console.log('screenshot -> ' + OUT)
  ws.close(); edge.kill(); process.exit(0)
}

main().catch((e) => { console.error('探针异常:', e.message); try { edge.kill() } catch {}; process.exit(1) })
