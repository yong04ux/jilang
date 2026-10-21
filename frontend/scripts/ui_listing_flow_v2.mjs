// Listing 工作室验收：打开种子草稿 → 版本与差异 → 复检 → 导出入口
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8200'
const OUT = process.argv[3] || join(tmpdir(), 'cp-lst')
const PORT = 9362
const profile = join(tmpdir(), `cp-edge-lst-${Date.now()}`)
mkdirSync(OUT, { recursive: true })

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1440,960', 'about:blank',
], { stdio: 'ignore' })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let failures = 0
function check(name, cond, detail = '') {
  console.log(`[${cond ? 'PASS' : 'FAIL'}] ${name}${detail ? ' — ' + detail : ''}`)
  if (!cond) failures += 1
}

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
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  const errors = []
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
    if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || 'exception')
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
  const goto = async (path) => { await send('Page.navigate', { url: BASE + path }); await sleep(1800) }
  const waitFor = async (expr, timeout = 25000) => {
    const end = Date.now() + timeout
    while (Date.now() < end) { if (await ev(expr)) return true; await sleep(250) }
    return false
  }
  const shot = async (name) => {
    const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(cap.result.data, 'base64'))
  }

  await send('Page.enable'); await send('Runtime.enable')
  await goto('/dashboard')
  await ev(`fetch('/api/auth/login', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:'demo', password:'demo-pass-1234'})}).then(r=>r.status)`)

  // 打开种子草稿
  await goto('/listings?listing=seed-listing-1')
  const loaded = await waitFor('!!document.querySelector("[data-versions]")', 20000)
  check('草稿加载并渲染操作条', loaded)
  check('有复检入口', await ev('!!document.querySelector("[data-recheck]")'))
  check('有导出入口', await ev('!!document.querySelector("[data-export]")'))
  await shot('listing-detail')

  // 复检
  await ev('document.querySelector("[data-recheck]").click()')
  const rechecked = await waitFor('document.body.innerText.includes("复检结果")', 15000)
  check('复检返回结果', rechecked)
  await shot('listing-recheck')

  // 版本链
  await ev('document.querySelector("[data-versions]").click()')
  const versions = await waitFor('document.body.innerText.includes("版本链")', 15000)
  check('版本链可用', versions)

  // 导出
  await ev('document.querySelector("[data-export]").click()')
  await sleep(400)
  check('导出格式 md/json/txt',
    (await ev('document.querySelectorAll("[data-export]").length')) >= 1 &&
    (await ev('document.body.innerText.includes("MD")')) &&
    (await ev('document.body.innerText.includes("TXT")')))
  await shot('listing-export')

  // 直接验证导出接口
  const exportStatus = await ev(`fetch('/api/listings/seed-listing-1/export?format=md', {credentials:'same-origin'}).then(r=>r.status)`)
  check('导出接口 200', exportStatus === 200, String(exportStatus))

  console.log(errors.length ? `\nCONSOLE ERRORS:\n${errors.slice(0, 5).join('\n')}` : '\nno console errors')
  ws.close(); edge.kill(); await sleep(300)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
  console.log(failures ? `\n${failures} FAILED` : '\nALL LISTING CHECKS PASSED')
  console.log('shots:', OUT)
  process.exit(failures ? 1 : 0)
}
main().catch((e) => { console.error('FAIL:', e.message); edge.kill(); process.exit(1) })
