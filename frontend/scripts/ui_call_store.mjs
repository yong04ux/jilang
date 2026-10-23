// 直接调用页面渲染函数，抓出真实异常
import { spawn } from 'node:child_process'
import { rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8300'
const PORT = 9800 + (Date.now() % 99)
const profile = join(tmpdir(), `cp-call-${Date.now()}`)
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
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
  }
  await new Promise((r) => (ws.onopen = r))
  const send = (method, params = {}) => new Promise((r) => { id += 1; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })) })
  const evaluate = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
    return r.result?.result?.value
  }
  await send('Page.enable'); await send('Runtime.enable')

  await send('Page.navigate', { url: `${BASE}/dashboard` })
  await sleep(2500)

  console.log('login:', await evaluate(`(async () => {
    const r = await fetch('/api/auth/login', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ username: 'guest_c7f46c00', password: 'dYgDoYuvmp650dpBlMv_ay4G' }) });
    const d = await r.json();
    window.dispatchEvent(new CustomEvent('cp:authenticated'));
    return d.user ? d.user.username : ('fail ' + r.status);
  })()`))
  await sleep(1200)

  console.log('authUser:', await evaluate(`window.CPAuth && window.CPAuth.user ? window.CPAuth.user.username : null`))
  console.log('gateVisible:', await evaluate(`(() => { const g = document.querySelector('#auth-gate'); return g ? !g.hidden : false })()`))

  console.log('manual render:', await evaluate(`(async () => {
    const root = document.getElementById('view-root');
    try {
      await window.CPPageStores.render(root, 'dashboard', {});
      return 'ok len=' + root.innerHTML.length;
    } catch (e) {
      return 'THROW: ' + (e && e.stack ? e.stack.split('\\n').slice(0,4).join(' | ') : e);
    }
  })()`))
  await sleep(2500)
  console.log('cards:', await evaluate(`document.querySelectorAll('.st-card').length`))
  console.log('metrics:', await evaluate(`document.querySelectorAll('.st-metric').length`))
  console.log('firstCardHTML:', String(await evaluate(`(document.querySelector('.st-card')||{}).outerHTML||'none'`)).slice(0, 260))
  console.log('stageHTML:', String(await evaluate(`(document.getElementById('st-stage')||{}).innerHTML||'no stage'`)).slice(0, 400))

  ws.close(); edge.kill(); await sleep(300)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
}
main().catch((e) => { console.error('FAIL', e.message); edge.kill(); process.exit(1) })
