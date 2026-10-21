// 原型截图探针：逐页打开、捕获控制台错误、截图
// 用法：node scripts/ui_shot.mjs <url> <out.png> [width] [height]
import { spawn } from 'node:child_process'
import { writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const URL_ARG = process.argv[2] || 'http://127.0.0.1:8200/workbench'
const OUT = process.argv[3] || join(tmpdir(), 'cp_shot.png')
const W = Number(process.argv[4] || 1440)
const H = Number(process.argv[5] || 960)
const PORT = 9334
const profile = join(tmpdir(), `cp-edge-shot-${Date.now()}`)

mkdirSync(dirname(OUT), { recursive: true })

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  `--window-size=${W},${H}`, 'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function getJson(path) {
  const res = await fetch(`http://127.0.0.1:${PORT}${path}`)
  return res.json()
}

async function main() {
  let target
  for (let i = 0; i < 60; i += 1) {
    try {
      const list = await getJson('/json/list')
      target = list.find((t) => t.type === 'page')
      if (target) break
    } catch {}
    await sleep(250)
  }
  if (!target) throw new Error('无法连接 Edge DevTools')

  const ws = new WebSocket(target.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  const errors = []
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id) }
    if (msg.method === 'Runtime.exceptionThrown') {
      errors.push(msg.params.exceptionDetails.exception?.description || 'unknown exception')
    }
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
      errors.push(msg.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
    }
  }
  await new Promise((resolve) => (ws.onopen = resolve))

  const send = (method, params = {}) => new Promise((resolve) => {
    id += 1; pending.set(id, resolve)
    ws.send(JSON.stringify({ id, method, params }))
  })

  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || 'eval failed')
    return r.result?.result?.value
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Page.navigate', { url: URL_ARG })
  await sleep(2200)

  const title = await evaluate('document.title')
  const hasHero = await evaluate('!!document.querySelector(".wb-hero-title, .page-title")')
  const cardCount = await evaluate('document.querySelectorAll(".skill-card").length')
  const railCount = await evaluate('document.querySelectorAll(".rail-item").length')
  const bodyH = await evaluate('document.body.scrollHeight')
  const viewportH = await evaluate('window.innerHeight')

  console.log('url:', URL_ARG)
  console.log('title:', title, '| hero:', hasHero, '| skill cards:', cardCount, '| rail items:', railCount)
  console.log('body height:', bodyH, '| viewport:', viewportH)
  if (errors.length) console.log('CONSOLE ERRORS:\n' + errors.join('\n'))

  const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  writeFileSync(OUT, Buffer.from(cap.result.data, 'base64'))
  console.log('screenshot:', OUT)

  ws.close(); edge.kill(); await sleep(400)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
  if (errors.length) { console.log('SHOT DONE WITH ERRORS'); process.exit(2) }
  console.log('SHOT OK')
}

main().catch((e) => { console.error('SHOT FAIL:', e.message); edge.kill(); process.exit(1) })
