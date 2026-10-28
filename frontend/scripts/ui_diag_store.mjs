// 单页诊断：抓控制台异常 + view-root 内容 + 网络失败
import { spawn } from 'node:child_process'
import { rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8300'
const PAGE = process.argv[3] || '/stores'
const PORT = 9900 + (Date.now() % 90)
const profile = join(tmpdir(), `cp-diag-${Date.now()}`)

const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1440,1000', 'about:blank'],
  { stdio: 'ignore' })

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
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  const logs = []
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails
      logs.push('EXCEPTION: ' + (d.exception?.description || d.text))
    }
    if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(m.params.type)) {
      logs.push(m.params.type.toUpperCase() + ': ' + m.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
    }
    if (m.method === 'Network.loadingFailed') logs.push('NETFAIL: ' + m.params.errorText)
    if (m.method === 'Network.responseReceived' && m.params.response.status >= 400) {
      logs.push('HTTP ' + m.params.response.status + ' ' + m.params.response.url)
    }
  }
  await new Promise((r) => (ws.onopen = r))
  const send = (method, params = {}) => new Promise((r) => { id += 1; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })) })
  const evaluate = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
    return r.result?.result?.value
  }

  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable')
  await send('Page.navigate', { url: `${BASE}/dashboard` })
  await sleep(1500)
  console.log('login:', await evaluate(`fetch('/api/auth/demo',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(r=>r.json()).then(d=>{ window.dispatchEvent(new CustomEvent('cp:authenticated')); return d.username||'fail' })`))

  console.log('t0', Date.now())
  await send('Page.navigate', { url: `${BASE}${PAGE}` })
  console.log('navigated', Date.now())
  await sleep(3000)

  console.log('--- logs ---')
  console.log(logs.slice(0, 25).join('\n') || '(none)')
  console.log('--- dom ---')
  console.log('rootHTML:', String(await evaluate(`(document.getElementById('view-root')||{}).innerHTML||''`)).slice(0, 300))
  console.log('hasShell:', await evaluate(`!!document.querySelector('.sidebar')`))
  console.log('user:', await evaluate(`JSON.stringify(window.CPAuth && window.CPAuth.user || null).slice(0,120)`))
  console.log('pages:', await evaluate(`['dashboard','workbench','tasks','data','agents','skills','stores','settings'].join(',')`))
  console.log('hasStoresStage:', await evaluate(`!!document.getElementById('st-stage')`))
  console.log('path:', await evaluate(`location.pathname + location.search`))

  ws.close(); edge.kill(); await sleep(300)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
}
main().catch((e) => { console.error('FAIL', e.message); edge.kill(); process.exit(1) })
