// 只验证退出登录：确认旧页面被清空、登录门亮起（等请求真的完成，不拍半截）
import { spawn } from 'node:child_process'
import { rmSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = 'http://127.0.0.1:8300'
const USER = process.env.CP_USER || 'guest_c7f46c00'
const PASS = process.env.CP_PASS || 'dYgDoYuvmp650dpBlMv_ay4G'
const OUT = 'D:/my-project/CrossPilot/docs/shots'
const PORT = 9050 + (Date.now() % 90)
const profile = join(tmpdir(), `cp-logout-${Date.now()}`)
mkdirSync(OUT, { recursive: true })

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
    if (r.result?.exceptionDetails) return 'THROW ' + (r.result.exceptionDetails.exception?.description || '').slice(0, 400)
    return r.result?.result?.value
  }

  await send('Page.enable'); await send('Runtime.enable')
  await send('Page.navigate', { url: `${BASE}/stores` })
  await sleep(3000)
  console.log('login:', await evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({username:${JSON.stringify(USER)},password:${JSON.stringify(PASS)}})})
    .then(r=>r.json()).then(async d=>{ await window.CPAuth.load(); window.dispatchEvent(new CustomEvent('cp:authenticated')); return d.user?.username||'fail' })`))

  console.log('render:', await evaluate(`(async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < 180000) {
      if (document.querySelector('.st-card')) break;
      await new Promise(r => setTimeout(r, 200));
    }
    return JSON.stringify({
      title: (document.querySelector('.page-title')||{}).textContent || '',
      cards: document.querySelectorAll('.st-card').length,
      slots: document.querySelectorAll('#view-root .mount-slot').length,
    });
  })()`))

  // 等 logout 真正跑完（含 /api/auth/logout 往返），不拍半截
  console.log('logout:', await evaluate(`(async () => {
    const t0 = Date.now();
    await window.CPAuth.logout();
    // 再等一拍，让 cp:logout 的监听把 DOM 清干净
    await new Promise(r => setTimeout(r, 600));
    const gate = document.getElementById('auth-gate');
    return JSON.stringify({
      ms: Date.now() - t0,
      user: window.CPAuth.user,
      rootText: (document.getElementById('view-root')||{}).textContent?.length,
      slots: document.querySelectorAll('#view-root .mount-slot').length,
      gate: gate ? (gate.hasAttribute('hidden') || getComputedStyle(gate).display === 'none' ? 'hidden' : 'VISIBLE') : 'none',
      path: location.pathname,
    });
  })()`))

  const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  writeFileSync(join(OUT, 'switch-2-gate.png'), Buffer.from(cap.result.data, 'base64'))

  ws.close(); edge.kill(); await sleep(300)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
}
main().catch((e) => { console.error('FAIL', e.message); edge.kill(); process.exit(1) })
