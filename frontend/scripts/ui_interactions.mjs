// 新界面端到端验收：真实登录 → 工作台执行 → 任务中心 → 详情
// 用示例数据 + 关闭 Listing 生成，避免真实模型调用（分析与校验都在本地完成）
import { spawn } from 'node:child_process'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8000'
const PORT = 9338
const profile = join(tmpdir(), `cp-edge-e2e-${Date.now()}`)

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run',
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
  for (let i = 0; i < 60; i += 1) {
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
  const goto = async (path) => { await send('Page.navigate', { url: BASE + path }); await sleep(1500) }
  const waitFor = async (expr, timeout = 20000) => {
    const end = Date.now() + timeout
    while (Date.now() < end) {
      if (await ev(expr)) return true
      await sleep(300)
    }
    return false
  }

  await send('Page.enable'); await send('Runtime.enable')

  // 1) 未登录 → 登录门
  await goto('/')
  check('根路径重定向到工作台', (await ev('location.pathname')) === '/workbench', await ev('location.pathname'))
  check('显示登录门', await ev('!document.getElementById("auth-gate").hidden'))

  // 2) 注册新账号
  const username = 'e2e_' + Date.now().toString(36)
  await ev(`(() => {
    const gate = document.getElementById('auth-gate');
    const sw = gate.querySelector('#auth-switch');
    if (sw) sw.click();
    return true;
  })()`)
  await sleep(300)
  const isRegister = await ev('!!document.querySelector("#auth-gate input[name=confirm]")')
  check('可切换到注册表单', isRegister)
  await ev(`(() => {
    const f = document.querySelector('#auth-form');
    f.username.value = ${JSON.stringify(username)};
    f.password.value = 'e2e-password-123';
    if (f.confirm) f.confirm.value = 'e2e-password-123';
    f.requestSubmit();
    return true;
  })()`)
  const loggedIn = await waitFor('document.getElementById("auth-gate").hidden === true', 15000)
  check('注册后自动登录并进入应用', loggedIn)
  check('侧栏渲染', (await ev('document.querySelectorAll(".rail-item").length')) >= 9)

  // 3) 工作台：输入目标 → 参数确认 → 载入示例 → 执行
  await goto('/workbench')
  check('工作台渲染 Hero', await ev('!!document.querySelector(".wb-hero-title")'))
  await ev(`(() => {
    const input = document.getElementById('composer-input');
    input.value = '分析示例竞品的价格与评论痛点';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()`)
  await sleep(200)
  check('发送按钮可用', (await ev('document.getElementById("composer-send").disabled')) === false)
  await ev('document.getElementById("composer-send").click()')
  await sleep(600)
  check('进入参数确认', await ev('!!document.getElementById("wb-product")'))

  await ev('document.getElementById("wb-demo").click()')
  await waitFor('(document.getElementById("wb-product")||{}).value', 8000)
  check('示例数据已填充', ((await ev('document.getElementById("wb-product").value')) || '').length > 0)

  // 关闭 Listing（避免真实模型调用），然后执行
  await ev(`(() => { const c = document.getElementById('wb-with-listing'); if (c) c.checked = false; return true; })()`)
  await ev('document.getElementById("wb-run").click()')
  const done = await waitFor(
    '!!document.querySelector(".wb-run") && !document.querySelector(".badge-running")',
    30000,
  )
  check('工作台执行完成', done)
  check('执行计划来自真实任务', (await ev('document.querySelectorAll(".timeline-item").length')) >= 4)
  check('渲染竞品分析结果', await ev('!!document.querySelector(".report-block")'))
  check('渲染市场机会总结', await ev('document.body.innerText.includes("市场机会总结")'))
  check('渲染数据完整性', await ev('document.body.innerText.includes("数据完整性")'))
  check('结果带示例标记', await ev('!!document.querySelector(".mock-flag")'))

  // 3.1) Agent / Skills 页读注册表
  await goto('/agents')
  check('Agent 页来自注册表', (await ev('document.querySelectorAll("[data-agent-run]").length')) >= 3)
  await goto('/skills')
  check('Skills 页来自注册表', (await ev('document.body.innerText.includes("competitor_analysis")')))

  // 4) 任务中心
  await goto('/tasks')
  check('任务列表有记录', (await ev('document.querySelectorAll("tbody tr").length')) >= 1)
  const before = await ev('document.querySelectorAll("tbody tr").length')
  await ev('document.querySelector(\'[data-status="succeeded"]\').click()')
  await sleep(800)
  const after = await ev('document.querySelectorAll("tbody tr").length')
  check('状态筛选生效', after <= before, `${before} -> ${after}`)

  // 5) 任务详情
  await ev('document.querySelector("tbody tr a").click()')
  await waitFor('!!document.querySelector(".timeline-item")', 10000)
  check('详情页显示真实步骤', (await ev('document.querySelectorAll(".timeline-item").length')) >= 3)
  check('详情页显示耗时', (await ev('document.body.innerText')).includes(' s') || (await ev('document.body.innerText')).includes('ms'))

  // 6) 旧界面确实已下线（服务端返回 404，不再有 /legacy 与 /static）
  const legacyStatus = await ev('fetch("/legacy").then(r => r.status)')
  const staticStatus = await ev('fetch("/static/app.js").then(r => r.status)')
  check('/legacy 已下线', legacyStatus === 404, 'got ' + legacyStatus)
  check('/static 已下线', staticStatus === 404, 'got ' + staticStatus)

  ws.close(); edge.kill(); await sleep(300)
  try { (await import('node:fs')).rmSync(profile, { recursive: true, force: true }) } catch {}
  if (errors.length) console.log('CONSOLE ERRORS:\n' + errors.slice(0, 8).join('\n'))
  console.log(failures ? `\n${failures} FAILED` : '\nALL E2E CHECKS PASSED')
  process.exit(failures ? 1 : 0)
}
main().catch((e) => { console.error('E2E FAIL:', e.message); edge.kill(); process.exit(1) })
