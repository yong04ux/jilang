// 调试：登录后打开某页，打印 DOM/控制台状态，定位白屏或卡在登录门的原因
import { spawn } from 'node:child_process'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8200'
const PATH = process.argv[3] || '/dashboard'
const PORT = 9352
const profile = join(tmpdir(), `cp-edge-dbg-${Date.now()}`)

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run',
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
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  const logs = []
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
    if (m.method === 'Runtime.exceptionThrown') {
      logs.push('EXC: ' + (m.params.exceptionDetails.exception?.description || 'exception'))
    }
    if (m.method === 'Runtime.consoleAPICalled') {
      logs.push(`LOG[${m.params.type}]: ` + m.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
    }
    if (m.method === 'Network.responseReceived') {
      const r = m.params.response
      if (r.url.includes('/api/')) logs.push(`NET ${r.status} ${r.url}`)
    }
  }
  await new Promise((r) => (ws.onopen = r))
  const send = (method, params = {}) => new Promise((resolve) => {
    id += 1; pending.set(id, resolve); ws.send(JSON.stringify({ id, method, params }))
  })
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
    if (r.result?.exceptionDetails) return 'EVAL_ERR: ' + (r.result.exceptionDetails.exception?.description || '')
    return r.result?.result?.value
  }

  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable')

  // 登录
  await send('Page.navigate', { url: BASE + '/probe' })
  await sleep(1500)
  const submitResult = await ev(`(() => {
    const gate = document.getElementById('auth-gate')
    const f = document.querySelector('#auth-form')
    if (!f) return 'no form; gate=' + (gate ? 'present' : 'missing')
    f.username.value = 'demo'; f.password.value = 'demo-pass-1234'; f.requestSubmit(); return 'submitted'
  })()`)
  logs.push('submit: ' + submitResult)
  const direct = await ev(`fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin', body: JSON.stringify({username:'demo', password:'demo-pass-1234'})}).then(r => r.status + ' ' + r.headers.get('set-cookie'))`)
  logs.push('direct login: ' + direct)
  await sleep(2000)
  logs.push('--- after login, status: ' + (await ev(`fetch('/api/auth/status',{credentials:'same-origin'}).then(r=>r.text())`)))

  logs.push('--- navigate ' + PATH)
  await send('Page.navigate', { url: BASE + PATH })
  await sleep(3000)

  console.log('pathname:', await ev('location.pathname'))
  console.log('gate hidden:', await ev('(document.getElementById("auth-gate")||{}).hidden'))
  console.log('gate html len:', await ev('(document.getElementById("auth-gate")||{}).innerHTML?.length'))
  console.log('view-root children:', await ev('document.getElementById("view-root").children.length'))
  console.log('body text len:', await ev('document.body.innerText.length'))
  console.log('CPAuth.user:', await ev('JSON.stringify(window.CPAuth && window.CPAuth.user)'))
  console.log('modules:', await ev('[!!window.CPShell,!!window.CPAuth,!!window.CPRouter,!!window.CPPageDashboard].join(",")'))
  console.log('auth error text:', await ev('(document.querySelector("#auth-error")||{}).textContent || ""'))
  console.log('\n--- logs ---')
  console.log(logs.join('\n'))

  ws.close(); edge.kill()
}
main().catch((e) => { console.error('FAIL', e.message); edge.kill(); process.exit(1) })
