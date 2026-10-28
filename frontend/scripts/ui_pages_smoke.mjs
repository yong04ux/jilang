#!/usr/bin/env node
/**
 * 页面冒烟探针：针对「已迁到 React 的页面」做结构与交互断言。
 *
 * 与 ui_*.mjs 那批老探针的分工：老探针按业务场景走（工作台跑任务、技能页跑表单），
 * 这个只问「这一页还在不在、该有的元素有没有、点了会不会去对地方」。
 * 每迁完一页就往 SECTIONS 里加一段。
 *
 * 用法：node scripts/ui_pages_smoke.mjs [base]
 */
import { spawn } from 'node:child_process'
import { rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8200'
const PORT = 9100 + (Date.now() % 90)
const profile = join(tmpdir(), `cp-smoke-${Date.now()}`)

const edge = spawn(
  EDGE,
  [
    '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
    '--window-size=1440,1000', 'about:blank',
  ],
  { stdio: 'ignore' },
)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let failed = 0
const check = (ok, label, detail = '') => {
  if (ok) console.log(`  PASS  ${label}${detail !== '' ? '  ' + JSON.stringify(detail) : ''}`)
  else {
    failed += 1
    console.log(`  FAIL  ${label}${detail !== '' ? '  ' + JSON.stringify(detail) : ''}`)
  }
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
  if (!target) throw new Error('拿不到 Edge 调试目标')

  const ws = new WebSocket(target.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  const errors = []
  const consoleErrors = []
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m)
      pending.delete(m.id)
      return
    }
    if (m.method === 'Runtime.exceptionThrown') {
      errors.push((m.params.exceptionDetails?.exception?.description || '').slice(0, 200))
    }
    // React 会把渲染期错误吞成 console.error，只抓 exceptionThrown 会漏掉
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErrors.push(
        m.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300),
      )
    }
  }
  await new Promise((r) => (ws.onopen = r))
  const send = (method, params = {}) =>
    new Promise((r) => {
      id += 1
      pending.set(id, r)
      ws.send(JSON.stringify({ id, method, params }))
    })
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', {
      expression: expr,
      awaitPromise: true,
      returnByValue: true,
    })
    if (r.result?.exceptionDetails) {
      return 'THROW ' + (r.result.exceptionDetails.exception?.description || '').slice(0, 300)
    }
    return r.result?.result?.value
  }
  const waitFor = async (expr, ms = 15000) => {
    const t0 = Date.now()
    while (Date.now() - t0 < ms) {
      if (await ev(expr)) return true
      await sleep(150)
    }
    return false
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Page.navigate', { url: `${BASE}/agents` })
  await sleep(2500)

  // 新注册账号，避开 /api/auth/demo 的按 IP 限流
  const user = 'smoke_' + Date.now().toString(36)
  const login = await ev(`(async () => {
    const r = await fetch('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: ${JSON.stringify(user)}, password: 'password123' }) });
    if (!r.ok) return 'register:' + r.status;
    const u = await window.CPAuth.load();
    if (!u) return 'gate-still-up';
    window.dispatchEvent(new CustomEvent('cp:authenticated'));
    return u.username })()`)
  check(typeof login === 'string' && !/^(register|gate)/.test(login), '登录并关闭登录门', login)
  await sleep(1200)

  /* ---------------- 先造一条真实任务 ----------------
     工作台的两条分支必须分开验：新账号走空态，有数据才走到趋势图 SVG 与任务表。
     这里用示例数据跑一次异步竞品分析（规则引擎即可，不依赖模型 Key）。 */
  console.log('\n准备：造一条任务（用于验证趋势图与任务表）')
  const seeded = await ev(`(async () => {
    const ds = await (await fetch('/api/demo/dataset', { credentials: 'same-origin' })).json();
    const ar = ds.analysis_request || {};
    const r = await fetch('/api/agent/runs', { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_key: 'main', goal: null, product_name: ar.product_name,
        platform: 'amazon', marketplace: 'US', competitors: ar.competitors || [], keywords: [],
        own_specs: {}, own_key_features: [], own_price: null, with_listing: false,
        listing_language: 'en-US', data_source: 'manual', async_run: true }) });
    if (!r.ok) return 'run:' + r.status + ' ' + (await r.text()).slice(0, 100);
    const d = await r.json();
    const id = d.task_id;
    const t0 = Date.now();
    while (Date.now() - t0 < 120000) {
      const t = await (await fetch('/api/tasks/' + id, { credentials: 'same-origin' })).json();
      const st = (t.task || {}).status;
      if (['succeeded','failed','partial','cancelled','waiting_for_input','awaiting_approval'].indexOf(st) !== -1) {
        return 'done:' + st;
      }
      await new Promise((res) => setTimeout(res, 500));
    }
    return 'timeout' })()`)
  check(String(seeded).indexOf('done:') === 0, '任务已跑完（用于后续断言）', seeded)

  /* ---------------- 工作台 ---------------- */
  console.log('\n/dashboard')
  await ev(`window.CPRouter.go('/dashboard', { force: true })`)
  const dashReady = await waitFor(`!!document.querySelector('.dash-kpi .kpi')`)
  check(dashReady, 'KPI 行已渲染')
  // 趋势图由 useEffect 在提交后绘制，取样要等它落地（否则会读到空容器）
  await waitFor(`(() => { const h = document.querySelector('#dash-trend'); return !!h && h.children.length > 0 })()`)
  const dash = JSON.parse(
    await ev(`JSON.stringify({
      title: (document.querySelector('.page-title') || {}).textContent || '',
      desc: (document.querySelector('.page-desc') || {}).textContent || '',
      kpis: document.querySelectorAll('.dash-kpi .kpi').length,
      kpiLabels: Array.from(document.querySelectorAll('.dash-kpi .kpi-label')).map((e) => e.textContent),
      trend: !!document.querySelector('#dash-trend'),
      trendLen: (document.querySelector('#dash-trend') || {}).innerHTML ? document.querySelector('#dash-trend').innerHTML.length : -1,
      trendSvg: document.querySelectorAll('#dash-trend svg').length,
      trendEmpty: !!document.querySelector('#dash-trend .cp-chart-empty'),
      cards: document.querySelectorAll('.dash-grid .card').length,
      taskTable: document.querySelectorAll('.dash-grid table.table tbody tr').length,
      devwords: /TODO|Mock|placeholder|未接入|暂未实现/i.test(document.body.textContent || ''),
    })`),
  )
  check(dash.title === '工作台', '标题正确', dash.title)
  check(dash.desc.length > 0, '有页面说明', dash.desc.slice(0, 20))
  check(dash.kpis === 5, 'KPI 5 格', dash.kpis)
  check(
    dash.kpiLabels.join('|') === '任务总数|进行中|报告|Listing|待审批',
    'KPI 标签顺序正确',
    dash.kpiLabels,
  )
  check(dash.cards >= 3, '主区卡片已渲染', dash.cards)
  check(dash.trend && (dash.trendSvg > 0 || dash.trendEmpty), '趋势区有图或明确空态', {
    svg: dash.trendSvg,
    empty: dash.trendEmpty,
    len: dash.trendLen,
    consoleErrors: consoleErrors.slice(-2),
  })
  check(dash.trendSvg > 0, '有任务时趋势图真的画出来了', dash.trendSvg)
  check(dash.taskTable > 0, '近期任务表有行', dash.taskTable)
  check(dash.devwords === false, '无开发标记/内部标识')

  /* ---------------- Agent 市场 ---------------- */
  console.log('\n/agents')
  await ev(`window.CPRouter.go('/agents', { force: true })`)
  const agentsReady = await waitFor(`!!document.querySelector('.card-grid-3 .card')`)
  check(agentsReady, 'Agent 卡片已渲染')
  const agents = await ev(`JSON.stringify({
    title: (document.querySelector('.page-title') || {}).textContent || '',
    desc: (document.querySelector('.page-desc') || {}).textContent || '',
    cards: document.querySelectorAll('.card-grid-3 .card').length,
    withRunBtn: document.querySelectorAll('.card-grid-3 [data-agent-run]').length,
    firstName: (document.querySelector('.card-grid-3 .t-section') || {}).textContent || '',
    slots: document.querySelectorAll('#view-root > .mount-slot').length,
    hasView: !!document.querySelector('#view-root > .mount-slot > .view'),
  })`)
  const a = JSON.parse(agents)
  check(a.title === 'Agent 市场', '标题正确', a.title)
  check(a.cards > 0, '至少一张卡片', a.cards)
  check(a.withRunBtn === a.cards, '每张卡都有「用此 Agent 运行」', `${a.withRunBtn}/${a.cards}`)
  check(a.firstName.length > 0, '卡片有名称', a.firstName)
  check(a.slots === 1 && a.hasView, 'DOM 形状是 .view-root > .mount-slot > .view')

  const nav = await ev(`(async () => {
    const btn = document.querySelector('.card-grid-3 [data-agent-run]');
    if (!btn) return 'no-btn';
    btn.click();
    const t0 = Date.now();
    while (Date.now() - t0 < 15000) {
      if (location.pathname === '/workbench' && location.search.indexOf('agent=') !== -1) {
        return 'ok:' + location.pathname + location.search;
      }
      await new Promise((r) => setTimeout(r, 150));
    }
    return 'timeout:' + location.pathname + location.search })()`)
  check(String(nav).indexOf('ok:/workbench?agent=') === 0, '点运行会带 agent 参数跳到 AI 助手', nav)

  /* ---------------- 404 ----------------
     注意：必须用「后端 SPA_ROUTES 已登记、但前端没有对应路由」的路径。
     随便编一个未登记路径（如 /not-a-real-route）会直接拿到后端 JSON 404 ——
     meta.py 刻意没有 catch-all 回落，否则会吞掉 /api 与 /docs。 */
  console.log('\n404（/operations：后端登记了外壳，前端无路由）')
  await send('Page.navigate', { url: `${BASE}/operations` })
  await sleep(2500)
  await ev(`(async () => { const u = await window.CPAuth.load(); if (u) window.dispatchEvent(new CustomEvent('cp:authenticated')); return 1 })()`)
  const notFoundReady = await waitFor(`!!document.querySelector('.empty-title')`)
  check(notFoundReady, '404 页已渲染')
  const nf = JSON.parse(
    await ev(`JSON.stringify({
      title: (document.querySelector('.page-title') || {}).textContent || '',
      empty: (document.querySelector('.empty-title') || {}).textContent || '',
      desc: (document.querySelector('.empty-desc') || {}).textContent || '',
      back: (document.querySelector('.page-actions a') || {}).getAttribute ? (document.querySelector('.page-actions a') || {}).getAttribute('href') : '',
      devwords: /TODO|Mock|mock|placeholder|未接入|暂未实现/i.test(document.body.textContent || ''),
    })`),
  )
  check(nf.title === '页面不存在', '标题正确', nf.title)
  check(nf.empty === '没有找到这个页面', '空态标题正确', nf.empty)
  check(nf.back === '/dashboard', '有「回到工作台」链接', nf.back)
  check(nf.devwords === false, '无开发标记/内部标识')

  check(errors.length === 0, '无 JS 异常', errors.slice(0, 3))
  check(consoleErrors.length === 0, '无 console.error', consoleErrors.slice(0, 3))

  console.log('─'.repeat(56))
  ws.close()
  edge.kill()
  await sleep(300)
  try {
    rmSync(profile, { recursive: true, force: true })
  } catch {}

  if (failed) {
    console.error(`\n页面冒烟失败：${failed} 项\n`)
    process.exit(1)
  }
  console.log('\n页面冒烟全部通过\n')
}

main().catch((e) => {
  console.error('FAIL', e.message)
  edge.kill()
  process.exit(1)
})
