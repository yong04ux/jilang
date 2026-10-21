// 交互验收：登录 → 任务抽屉 → 竞品分析异步 → 设置页厂商配置表单 → 数据源
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8200'
const OUT = process.argv[3] || join(tmpdir(), 'cp-flows')
const USER = process.argv[4] || 'demo'
const PASS = process.argv[5] || 'demo-pass-1234'
const PORT = 9356
const profile = join(tmpdir(), `cp-edge-flow-${Date.now()}`)
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
  if (!target) throw new Error('无法连接 Edge DevTools')

  const ws = new WebSocket(target.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  const errors = []
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
    if (m.method === 'Runtime.exceptionThrown') {
      errors.push(m.params.exceptionDetails.exception?.description || 'exception')
    }
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
  const shot = async (name) => {
    const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(cap.result.data, 'base64'))
  }
  const waitFor = async (expr, timeout = 25000) => {
    const end = Date.now() + timeout
    while (Date.now() < end) {
      if (await ev(expr)) return true
      await sleep(250)
    }
    return false
  }

  await send('Page.enable'); await send('Runtime.enable')

  // 登录
  await goto('/dashboard')
  const status = await ev(`fetch('/api/auth/login', {
    method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({username:${JSON.stringify(USER)}, password:${JSON.stringify(PASS)}})
  }).then(r=>r.status)`)
  check('登录', status === 200, String(status))
  await goto('/dashboard')
  check('登录门已隐藏', await ev('(document.getElementById("auth-gate")||{}).hidden !== false'))

  // 侧栏：文字侧栏 + 收起按钮
  check('文字侧栏渲染', (await ev('document.querySelectorAll(".sidebar-nav .nav-item").length')) >= 12)
  check('数据来源提示条', await ev('!document.getElementById("source-banner").hidden'))
  check('KPI 行 5 格', (await ev('document.querySelectorAll(".kpi-row .kpi").length')) === 5)
  check('趋势图 SVG', await ev('!!document.querySelector("svg.trend")'))
  await shot('dashboard')

  // 任务中心：抽屉
  await goto('/tasks')
  check('任务表格有行', (await ev('document.querySelectorAll("[data-task-row]").length')) >= 1)
  await ev('document.querySelector("[data-task-row]").click()')
  const drawerOpen = await waitFor('!!document.querySelector(".drawer .timeline-item")')
  check('点击行打开右侧抽屉', drawerOpen)
  check('抽屉 URL 深链', (await ev('location.pathname')).startsWith('/tasks/'))
  check('抽屉显示真实步骤', (await ev('document.querySelectorAll(".drawer .timeline-item").length')) >= 2)
  await shot('task-drawer')
  await ev('document.getElementById("task-drawer-close").click()')
  await sleep(400)
  check('抽屉可关闭', (await ev('!!document.getElementById("task-drawer-scrim")')) === false &&
    (await ev('document.querySelectorAll("aside.drawer").length')) === 0)

  // 深链直接打开
  await goto('/tasks/seed-task-report-1')
  const deep = await waitFor('!!document.querySelector(".drawer .timeline-item")', 15000)
  check('深链 /tasks/{id} 直接展开抽屉', deep)

  // 竞品分析：异步
  await goto('/competitors')
  await ev('document.getElementById("cmp-demo").click()')
  await sleep(1200)
  check('示例数据已填充', ((await ev('document.querySelector(\'[name="competitors"]\').value')) || '').length > 10)
  await ev('document.querySelector("#cmp-form button[type=submit]").click()')
  const progress = await waitFor('!!document.getElementById("cmp-steps")', 10000)
  check('提交后出现真实步骤面板', progress)
  check('未伪造百分比', (await ev('document.body.innerText.includes("%")')) === false ||
        (await ev('!!document.querySelector(".progress.is-indeterminate")')))
  const done = await waitFor('!!document.querySelector(".report-block")', 30000)
  check('异步分析完成并渲染报告', done)
  check('报告带示例标记', await ev('!!document.querySelector(".mock-flag")'))
  await shot('competitor-result')

  // 设置页：demo 账号应禁止新增配置（BYOK 共享账号约束）
  await goto('/settings')
  await waitFor('!!document.getElementById("prov-new")', 15000)
  check('预置厂商入口存在', await ev('!!document.getElementById("prov-new")'))
  check('demo 账号新增配置被禁用', await ev('document.getElementById("prov-new").disabled === true'))
  check('demo 账号看到共享账号提示', await ev('document.body.innerText.includes("共享账号")'))
  check('数据源区块存在', await ev('!!document.getElementById("section-data")'))
  await shot('settings-demo')

  // 换成一键体验的临时账号，配置表单应可用
  const guestStatus = await ev(`fetch('/api/auth/demo', {
    method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: '{}'
  }).then(r=>r.status)`)
  check('一键体验创建临时账号', guestStatus === 200, String(guestStatus))
  await goto('/settings')
  await waitFor('!!document.getElementById("prov-new")', 15000)
  check('临时账号可新增配置', await ev('document.getElementById("prov-new").disabled === false'))
  await ev('document.getElementById("prov-new").click()')
  await waitFor('!!document.getElementById("prov-form")', 8000)
  check('打开新增配置表单', await ev('!!document.getElementById("prov-form")'))
  check('厂商下拉有 9 个预置', (await ev('document.querySelectorAll("#prov-provider option").length')) === 9)
  check('自定义 base_url 需显式勾选', await ev('!!document.querySelector("#prov-custom-row input[disabled]")'))
  await ev('document.getElementById("prov-form").scrollIntoView({ block: "center" })')
  await sleep(300)
  await shot('settings-form')

  // 切换平台时 base_url 自动填厂商默认值
  await ev(`(() => {
    const sel = document.getElementById('prov-provider');
    sel.value = 'moonshot';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`)
  await sleep(300)
  check('切换厂商自动填 base_url',
    (await ev('document.querySelector(\'#prov-form [name="base_url"]\').value')).includes('moonshot'))

  // 预置厂商之外的地址应被后端拒绝（前端拿到 400 并显示）
  const ssrf = await ev(`(() => {
    const f = document.getElementById('prov-form')
    f.base_url.value = 'http://169.254.169.254/v1'
    f.model.value = 'deepseek-flash'
    f.api_key.value = 'sk-test-1234567890'
    f.provider.value = 'deepseek'
    f.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    return true
  })()`)
  await sleep(1200)
  check('自定义地址被白名单拦截', await ev('document.getElementById("prov-error") && !document.getElementById("prov-error").hidden'))
  await ev('document.getElementById("prov-form").scrollIntoView({ block: "center" })')
  await sleep(300)
  await shot('settings-ssrf-blocked')

  // 店铺：Mock 连接徽章
  await goto('/stores')
  check('数据源标记为未接入/Mock', await ev('document.body.innerText.includes("Mock") || document.body.innerText.includes("未接入")'))
  await shot('stores')

  console.log(errors.length ? `\nCONSOLE ERRORS:\n${errors.slice(0, 5).join('\n')}` : '\nno console errors')
  ws.close(); edge.kill(); await sleep(300)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
  console.log(failures ? `\n${failures} FAILED` : '\nALL FLOW CHECKS PASSED')
  console.log('shots:', OUT)
  process.exit(failures ? 1 : 0)
}
main().catch((e) => { console.error('FAIL:', e.message); edge.kill(); process.exit(1) })
