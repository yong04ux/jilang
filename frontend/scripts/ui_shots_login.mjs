// 登录页专项截图：默认态 / 密码错误 / 注册态 / 窄屏 / 密码可见
// 用法：node scripts/ui_shots_login.mjs <base> <outDir>
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8200'
const OUT = process.argv[3] || join(tmpdir(), 'cp-login')
const PORT = 9382
const profile = join(tmpdir(), `cp-edge-login-${Date.now()}`)

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
  const shot = async (name) => {
    const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(cap.result.data, 'base64'))
    console.log('  ->', name + '.png')
  }
  const viewport = (w, h) => send('Emulation.setDeviceMetricsOverride', {
    width: w, height: h, deviceScaleFactor: 2, mobile: false,
  })

  await send('Page.enable'); await send('Runtime.enable')

  await viewport(1440, 960)
  await send('Page.navigate', { url: BASE + '/' })
  await sleep(2200)

  const gateText = await ev('document.querySelector("#auth-gate")?.innerText.slice(0,300) || "NO GATE"')
  const hasReveal = await ev('document.querySelectorAll(".auth-reveal").length')
  const revealSvg = await ev('document.querySelector(".auth-reveal")?.innerHTML.length || 0')
  console.log('gate ok:', gateText.includes('登录'), '| reveal buttons:', hasReveal, '| icon len:', revealSvg)
  console.log('errors:', errors.length)
  await shot('01-login')

  // 密码可见性切换
  await ev(`document.querySelector('.auth-reveal').click()`)
  await sleep(320)
  const pwdType = await ev('document.querySelector("#auth-password").type')
  console.log('after reveal, input type =', pwdType)
  await shot('02-password-revealed')
  await ev(`document.querySelector('.auth-reveal').click()`)
  await sleep(200)

  // 密码错误
  await ev(`(() => {
    const f = document.getElementById('auth-form');
    f.username.value = 'demo';
    f.password.value = 'wrong-password-1';
    f.requestSubmit();
  })()`)
  await sleep(1800)
  const errText = await ev('document.querySelector("#auth-error")?.textContent || ""')
  const errHidden = await ev('document.querySelector("#auth-error")?.hidden')
  const btnText = await ev('document.querySelector(".auth-submit")?.textContent')
  console.log('error visible:', !errHidden, '| text:', errText, '| submit label back to:', btnText)
  await shot('03-login-error')

  // 注册态
  await ev(`document.querySelector('#auth-switch')?.click()`)
  await sleep(500)
  const regTitle = await ev('document.querySelector(".auth-title")?.textContent')
  const regFields = await ev('document.querySelectorAll("#auth-form input").length')
  console.log('register title:', regTitle, '| fields:', regFields)
  await shot('04-register')

  // 窄屏
  await ev(`document.querySelector('#auth-switch')?.click()`)
  await sleep(400)
  await viewport(760, 900)
  await sleep(600)
  const pitchHidden = await ev('getComputedStyle(document.querySelector(".auth-pitch")).display')
  console.log('narrow: pitch display =', pitchHidden)
  await shot('05-narrow')

  // 矮屏：确认卡片顶部不被裁掉
  await viewport(1440, 560)
  await sleep(600)
  const clip = await ev(`(() => {
    const c = document.querySelector('.auth-card').getBoundingClientRect();
    const g = document.getElementById('auth-gate');
    return JSON.stringify({ cardTop: Math.round(c.top), scrollH: g.scrollHeight, clientH: g.clientHeight, scrollTop: g.scrollTop });
  })()`)
  console.log('short viewport:', clip)
  await shot('06-short')

  // 正确凭据走表单提交：确认成功后 gate 收起、进入业务页
  await viewport(1440, 960)
  await send('Page.navigate', { url: BASE + '/' })
  await sleep(1800)
  await ev(`(() => {
    const f = document.getElementById('auth-form');
    f.username.value = 'demo';
    f.password.value = 'demo-pass-1234';
    f.requestSubmit();
  })()`)
  await sleep(2600)
  const gateGone = await ev('document.getElementById("auth-gate")?.hidden === true')
  const inApp = await ev('!!document.querySelector(".sidebar, .app-shell, .topbar")')
  console.log('correct login -> gate hidden:', gateGone, '| app shell rendered:', inApp)
  await shot('07-after-login')

  ws.close(); edge.kill(); await sleep(400)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
  console.log('shots:', OUT)
}
main().catch((e) => { console.error('FAIL:', e.message); edge.kill(); process.exit(1) })
