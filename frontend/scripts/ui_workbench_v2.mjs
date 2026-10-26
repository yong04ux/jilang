// 工作台「运行态」验收：载入示例 → 执行 → 左对话/右结果两栏 + 三个结果 Tab
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8200'
const OUT = process.argv[3] || join(tmpdir(), 'cp-wb')
const PORT = 9358
const profile = join(tmpdir(), `cp-edge-wb-${Date.now()}`)
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
  const goto = async (path) => { await send('Page.navigate', { url: BASE + path }); await sleep(2000) }
  const waitFor = async (expr, timeout = 30000) => {
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
  /* 「一键体验」按 IP 限流 5 次/小时，撞上了就注册个临时账号兜底 */
  const demoStatus = await ev(`fetch('/api/auth/demo', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:'{}'}).then(r=>r.status)`)
  if (demoStatus !== 200) {
    const uname = 'probe' + Date.now()
    await ev(`fetch('/api/auth/register', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:${JSON.stringify(uname)}, password:'Probe!23456', display_name:'验收探针'})}).then(r=>r.status)`)
  }
  await goto('/workbench')
  await waitFor('!!document.querySelector(".wb-hero-title")', 10000)

  // 空态 → 用示例数据 → 参数确认
  await ev('document.querySelector(\'[data-act="demo"]\').click()')
  await waitFor('!!document.getElementById("wb-product")', 10000)
  check('参数确认页出现', await ev('!!document.getElementById("wb-product")'))
  check('示例数据已填充', ((await ev('document.getElementById("wb-product").value')) || '').length > 0)

  // 关闭 Listing（临时账号未配 Key，Listing 会被 BYOK 拦），执行
  await ev('(() => { const c = document.getElementById("wb-with-listing"); if (c) c.checked = false; return true })()')
  await ev('document.getElementById("wb-run").click()')

  const runMode = await waitFor('!!document.getElementById("wb-run")', 15000)
  check('进入左对话 + 右结果两栏', runMode)
  check('有右侧结果面板', await ev('!!document.getElementById("wb-res-pane")'))
  check('结果 Tab 两个（步骤 / 数据）', (await ev('document.querySelectorAll("[data-res-tab]").length')) === 2)

  const done = await waitFor('!document.querySelector(".badge-running") && !!document.getElementById("wb-run")', 40000)
  check('执行完成', done)
  check('步骤来自真实 task_steps', (await ev('document.querySelectorAll(".timeline-item").length')) >= 4)

  // 切到「数据」Tab 看结果块
  await ev('document.querySelector(\'[data-res-tab="data"]\').click()')
  await sleep(600)
  check('数据 Tab 渲染结果块', (await ev('document.querySelectorAll(".result-block").length')) >= 2)
  await shot('workbench-run-data')

  // 切回「步骤」Tab
  await ev('document.querySelector(\'[data-res-tab="steps"]\').click()')
  await sleep(400)
  await shot('workbench-run-steps')

  console.log(errors.length ? `\nCONSOLE ERRORS:\n${errors.slice(0, 5).join('\n')}` : '\nno console errors')
  ws.close(); edge.kill(); await sleep(300)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
  console.log(failures ? `\n${failures} FAILED` : '\nALL WORKBENCH CHECKS PASSED')
  console.log('shots:', OUT)
  process.exit(failures ? 1 : 0)
}
main().catch((e) => { console.error('FAIL:', e.message); edge.kill(); process.exit(1) })
