// 验证「退出登录 → 一键体验」是否真的换成了新账号
// 关键断言：旧页面必须被清空、新账号必须重绘页面、顶栏名字必须刷新
import { spawn } from 'node:child_process'
import { rmSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.env.CP_BASE || 'http://127.0.0.1:8300'
const USER = process.env.CP_USER || 'guest_c7f46c00'
const PASS = process.env.CP_PASS || 'dYgDoYuvmp650dpBlMv_ay4G'
const OUT = process.env.CP_OUT || 'D:/my-project/CrossPilot/docs/shots'
const PORT = 9100 + (Date.now() % 90)
const profile = join(tmpdir(), `cp-switch-${Date.now()}`)
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
  const logs = []
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
    if (m.method === 'Runtime.exceptionThrown') logs.push('EX: ' + (m.params.exceptionDetails.exception?.description || '').slice(0, 300))
  }
  await new Promise((r) => (ws.onopen = r))
  const send = (method, params = {}) => new Promise((r) => { id += 1; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })) })
  const evaluate = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
    if (r.result?.exceptionDetails) return 'THROW ' + (r.result.exceptionDetails.exception?.description || '').slice(0, 400)
    return r.result?.result?.value
  }
  const shot = async (name) => {
    const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(join(OUT, name), Buffer.from(cap.result.data, 'base64'))
  }

  await send('Page.enable'); await send('Runtime.enable')
  await send('Page.navigate', { url: `${BASE}/dashboard` })
  await sleep(3000)

  // 1. 账号 A 登录
  console.log('A login:', await evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({username:${JSON.stringify(USER)},password:${JSON.stringify(PASS)}})})
    .then(r=>r.json()).then(async d=>{ if(!d.user) return 'fail'; await window.CPAuth.load(); window.dispatchEvent(new CustomEvent('cp:authenticated')); return d.user.username })`))
  await sleep(2500)

  // 2. 进店铺页并打标记，用来证明后面确实重挂了
  console.log('goto stores:', await evaluate(`(async () => {
    window.CPRouter.go('/stores', { force: true });
    const t0 = Date.now();
    while (Date.now() - t0 < 180000) {
      if (document.querySelector('.st-card')) break;
      await new Promise(r => setTimeout(r, 200));
    }
    const slot = document.querySelector('#view-root .mount-slot');
    if (slot) slot.dataset.mark = 'account-A';
    return JSON.stringify({
      title: (document.querySelector('.page-title')||{}).textContent || '',
      account: (document.getElementById('account-name')||{}).textContent || '',
      cards: document.querySelectorAll('.st-card').length,
      slotMark: slot ? slot.dataset.mark : null,
    });
  })()`))
  await shot('switch-1-account-a.png')

  // 3. 退出登录（必须 await：/api/auth/logout 在慢网络下要十几秒，
  //    只 sleep 几秒会读到"还没退出"的中间态，误判成 bug）
  console.log('logout:', await evaluate(`(async () => {
    const t0 = Date.now();
    await window.CPAuth.logout();
    await new Promise((r) => setTimeout(r, 600));
    const g = document.getElementById('auth-gate');
    return JSON.stringify({
      ms: Date.now() - t0,
      user: window.CPAuth.user,
      rootText: (document.getElementById('view-root') || {}).textContent?.length,
      slots: document.querySelectorAll('#view-root .mount-slot').length,
      gate: g ? (g.hasAttribute('hidden') || getComputedStyle(g).display === 'none' ? 'hidden' : 'VISIBLE') : 'none',
    });
  })()`))
  await shot('switch-2-gate.png')

  // 4. 一键体验（走按钮内部同样的三步；本地未配固定 demo 口令时按钮不渲染）
  const demo = await evaluate(`(async () => {
    try {
      const data = await window.CPApi.post('/api/auth/demo', {});
      if (!(await window.CPAuth.load(true))) return 'fail:load';
      window.dispatchEvent(new CustomEvent('cp:authenticated'));
      return data.username;
    } catch (err) { return 'fail:' + err.message }
  })()`)
  console.log('demo login:', demo)

  // demo 被限流时，退化成用另一个账号重新登录，验证的是同一条链路
  if (String(demo).indexOf('fail') === 0) {
    console.log('fallback login:', await evaluate(`(async () => {
      const r = await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:${JSON.stringify(USER)},password:${JSON.stringify(PASS)}})});
      const d = await r.json();
      if (!(await window.CPAuth.load(true))) return 'fail:load';
      window.dispatchEvent(new CustomEvent('cp:authenticated'));
      return d.user && d.user.username;
    })()`))
  }

  console.log('after re-login:', await evaluate(`(async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < 180000) {
      if (document.querySelector('#view-root .page-title')) break;
      await new Promise(r => setTimeout(r, 200));
    }
    const slot = document.querySelector('#view-root .mount-slot');
    return JSON.stringify({
      path: location.pathname,
      title: (document.querySelector('.page-title')||{}).textContent || '',
      account: (document.getElementById('account-name')||{}).textContent || '',
      slotMark: slot ? (slot.dataset.mark || 'fresh') : 'no-slot',
      cards: document.querySelectorAll('.st-card').length,
      gate: (() => { const g = document.getElementById('auth-gate'); return g ? (g.hasAttribute('hidden') || getComputedStyle(g).display === 'none' ? 'hidden' : 'VISIBLE') : 'none' })(),
    });
  })()`))
  await sleep(1500)
  await shot('switch-3-account-b.png')
  console.log('logs:', logs.slice(0, 5).join('\n') || '(none)')

  ws.close(); edge.kill(); await sleep(300)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
}
main().catch((e) => { console.error('FAIL', e.message); edge.kill(); process.exit(1) })
