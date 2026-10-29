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
  // 工作台改用 shadcn Card 后不再有 .kpi/.dash-grid：按语义属性断言
  const dashReady = await waitFor(`!!document.querySelector('[data-kpi]')`)
  check(dashReady, 'KPI 行已渲染')
  // 趋势图由 useEffect 在提交后绘制，取样要等它落地（否则会读到空容器）
  // 图表是 lazy chunk：骨架屏也算子节点，所以不能只等「有子节点」，
  // 要等到真的出 svg 或明确空态文案
  await waitFor(
    `(() => { const h = document.querySelector('#dash-trend'); if (!h) return false; return !!h.querySelector('svg') || !!h.querySelector('.cp-chart-empty') })()`,
    15000,
  )
  const dash = JSON.parse(
    await ev(`JSON.stringify({
      title: (document.querySelector('.page-title') || {}).textContent || '',
      desc: (document.querySelector('.page-desc') || {}).textContent || '',
      kpis: document.querySelectorAll('[data-kpi]').length,
      kpiLabels: Array.from(document.querySelectorAll('[data-kpi-label]')).map((e) => e.textContent),
      trend: !!document.querySelector('#dash-trend'),
      trendLen: (document.querySelector('#dash-trend') || {}).innerHTML ? document.querySelector('#dash-trend').innerHTML.length : -1,
      trendSvg: document.querySelectorAll('#dash-trend svg').length,
      trendEmpty: !!document.querySelector('#dash-trend .cp-chart-empty'),
      cards: document.querySelectorAll('[data-dash-card]').length,
      taskTable: document.querySelectorAll('[data-task-table] tbody tr').length,
      devwords: /TODO|Mock|placeholder|未接入|暂未实现/i.test(document.body.textContent || ''),
    })`),
  )
  check(dash.title === '工作台', '标题正确', dash.title)
  // 示例数据提示条：内容来自 /api/demo/dataset，用户必须能一眼看出这不是自己的经营数据
  check(
    await ev(`!document.getElementById('source-banner').hidden`),
    '数据来源提示条可见',
  )
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

  /* ---------------- 侧栏导航：点导航项应改地址、重挂页面，且不整页刷新 ----------------
     这条原先只在 ui_flows_v2 里有，而那个脚本的选择器是迁移前的前端
     （.kpi-row / svg.trend / /competitors），早已失效。搬到统一入口后，
     其他断言由本文件与 ui_*_v2 各自覆盖。 */
  console.log('\n侧栏导航')
  await ev(`window.__navStamp = 42; 1`)
  await ev(`(() => { const el = document.querySelector('.sidebar-nav [data-nav="tasks"]'); if (el) el.click(); return !!el })()`)
  const navigated = await waitFor(`location.pathname === '/tasks'`)
  check(navigated, '点「任务中心」导航项跳转到 /tasks', await ev('location.pathname'))
  check((await ev('window.__navStamp')) === 42, '导航是前端跳转，没有整页刷新')
  const activeNav = await ev(
    `(document.querySelector('.sidebar-nav .nav-item[aria-current="page"]') || {}).getAttribute && document.querySelector('.sidebar-nav .nav-item[aria-current="page"]').getAttribute('data-nav')`,
  )
  check(activeNav === 'tasks', '当前导航项标为选中', activeNav)

  /* ---------------- 任务中心 ---------------- */
  console.log('\n/tasks')
  await ev(`window.CPRouter.go('/tasks', { force: true })`)
  const tasksReady = await waitFor(`!!document.querySelector('#task-body table tbody tr')`)
  check(tasksReady, '任务表已渲染')
  const tlist = JSON.parse(
    await ev(`JSON.stringify({
      title: (document.querySelector('.page-title') || {}).textContent || '',
      chips: document.querySelectorAll('#task-filters .chip').length,
      rows: document.querySelectorAll('#task-body table tbody tr').length,
      count: (document.querySelector('#task-count') || {}).textContent || '',
      cols: Array.from(document.querySelectorAll('#task-body table thead th')).map((e) => e.textContent),
    })`),
  )
  check(tlist.title === '任务中心', '标题正确', tlist.title)
  check(tlist.chips === 9, '状态筛选有 9 个 chip', tlist.chips)
  check(tlist.rows > 0, '任务表有行', tlist.rows)
  check(tlist.count === `共 ${tlist.rows} 条`, '计数与行数一致', tlist.count)
  check(
    tlist.cols.join('|') === '任务|类型|来源|状态|创建|结果',
    '表头列正确',
    tlist.cols,
  )

  // 筛选：切到「已完成」后仍应有行（种子任务就是 succeeded）
  const filtered = await ev(`(async () => {
    const chip = Array.from(document.querySelectorAll('#task-filters .chip')).find((c) => c.textContent === '已完成');
    if (!chip) return 'no-chip';
    chip.click();
    const t0 = Date.now();
    while (Date.now() - t0 < 10000) {
      const active = document.querySelector('#task-filters .chip.is-active');
      const rows = document.querySelectorAll('#task-body table tbody tr').length;
      if (active && active.textContent === '已完成' && rows > 0) return 'ok:' + rows;
      await new Promise((r) => setTimeout(r, 150));
    }
    return 'timeout' })()`)
  check(String(filtered).indexOf('ok:') === 0, '筛选切换后仍有结果', filtered)
  await ev(`(() => { const c = Array.from(document.querySelectorAll('#task-filters .chip')).find((x) => x.textContent === '全部'); if (c) c.click(); return 1 })()`)
  await waitFor(`document.querySelectorAll('#task-body table tbody tr').length > 0`)

  // 打开抽屉：URL 要变，但列表不能被重挂（原实现的 replaceState 语义）
  const drawer = await ev(`(async () => {
    const row = document.querySelector('#task-body table tbody tr');
    if (!row) return 'no-row';
    const id = row.getAttribute('data-task-row');
    document.querySelector('#task-body table').__mark = 1;
    row.click();
    const t0 = Date.now();
    while (Date.now() - t0 < 15000) {
      if (document.querySelector('#task-drawer-body') && !document.querySelector('#task-drawer-body .skeleton')) break;
      await new Promise((r) => setTimeout(r, 150));
    }
    const table = document.querySelector('#task-body table');
    return JSON.stringify({
      id,
      path: location.pathname,
      hasDrawer: !!document.querySelector('.drawer.is-wide'),
      hasScrim: !!document.querySelector('#task-drawer-scrim'),
      listKept: table ? table.__mark === 1 : false,
      steps: document.querySelectorAll('#task-drawer-body .timeline-item, #task-drawer-body .step').length,
      bodyLen: (document.querySelector('#task-drawer-body') || {}).textContent ? document.querySelector('#task-drawer-body').textContent.length : -1,
    }) })()`)
  const d = JSON.parse(drawer)
  check(d.path === `/tasks/${d.id}`, '抽屉打开后 URL 变成 /tasks/{id}', d.path)
  check(d.hasDrawer && d.hasScrim, '抽屉与遮罩都在')
  check(d.listKept === true, '列表没有被重挂（replaceState 语义）')
  check(d.bodyLen > 0, '抽屉内容已加载', d.bodyLen)

  const closed = await ev(`(async () => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    const t0 = Date.now();
    while (Date.now() - t0 < 8000) {
      if (!document.querySelector('.drawer.is-wide')) return 'closed:' + location.pathname;
      await new Promise((r) => setTimeout(r, 100));
    }
    return 'still-open' })()`)
  check(String(closed).indexOf('closed:/tasks') === 0, 'Esc 关闭抽屉并还原地址', closed)

  /* 深链：整页加载 /tasks/{id} → 列表 + 抽屉 */
  const taskId = d.id
  await send('Page.navigate', { url: `${BASE}/tasks/${taskId}` })
  await sleep(2500)
  await ev(`(async () => { const u = await window.CPAuth.load(); if (u) window.dispatchEvent(new CustomEvent('cp:authenticated')); return 1 })()`)
  const deepReady = await waitFor(`!!document.querySelector('.drawer.is-wide #task-drawer-body')`)
  check(deepReady, '深链 /tasks/{id} 直接展开抽屉')
  // 列表与抽屉是两次独立请求，抽屉先回来是正常的 —— 等列表落地再断言
  await waitFor(`document.querySelectorAll('#task-body table tbody tr').length > 0`, 8000)
  const deep = JSON.parse(
    await ev(`JSON.stringify({
      rows: document.querySelectorAll('#task-body table tbody tr').length,
      path: location.pathname,
    })`),
  )
  check(deep.rows > 0, '深链下列表同时存在（不是整页跳转）', deep.rows)
  check(deep.path === `/tasks/${taskId}`, '深链地址保持不变', deep.path)

  /* ---------------- 数据资产 ---------------- */
  console.log('\n/data')
  await ev(`window.CPRouter.go('/data', { force: true })`)
  const dataReady = await waitFor(`!!document.getElementById('data-file')`)
  check(dataReady, '数据资产页渲染')
  const dp = JSON.parse(
    await ev(`JSON.stringify({
      title: (document.querySelector('.page-title') || {}).textContent || '',
      stats: document.querySelectorAll('.data-stat-card').length,
      uploadDisabled: (document.getElementById('data-upload') || {}).disabled,
      errorHidden: (document.getElementById('data-error') || {}).hidden,
      sources: !!document.getElementById('data-sources-content'),
      sourceCount: (document.getElementById('data-source-count') || {}).textContent || '',
      resultPanel: !!document.getElementById('data-result'),
      emptyText: (document.querySelector('#data-result .empty-title') || {}).textContent || '',
    })`),
  )
  check(dp.title === '数据资产', '标题正确', dp.title)
  check(dp.stats === 4, '概览 4 张统计卡', dp.stats)
  check(dp.uploadDisabled === true, '未选文件时「开始导入」不可点', dp.uploadDisabled)
  check(dp.errorHidden === true, '错误提示默认隐藏', dp.errorHidden)
  check(dp.sources && dp.resultPanel, '结果区与数据集区都在')
  check(dp.emptyText === '还没有导入结果', '未导入时是空态', dp.emptyText)

  /* ---------------- 技能：慢能力必须走后台任务 + 轮询 ----------------
     不用「DOM 上是否看到 loading」来断言：规则引擎跑得快时那个状态只存在一两百毫秒，
     采样必然漏（ui_skills_shot 就是这么误报的）。这里直接看网络调用。 */
  console.log('\n/skills（慢能力走异步）')
  await ev(`window.CPRouter.go('/skills?skill=competitor_analysis', { force: true })`)
  const skillFormReady = await waitFor(`!!document.querySelector('#sk-form')`)
  check(skillFormReady, '技能详情表单已渲染')
  const skillRun = await ev(`(async () => {
    window.__net = [];
    const f = window.fetch;
    window.fetch = async (...a) => {
      const u = typeof a[0] === 'string' ? a[0] : a[0].url;
      const r = await f.apply(window, a);
      window.__net.push(r.status + ' ' + u);
      return r;
    };
    const set = (sel, v) => { const el = document.querySelector(sel); if (!el) return false;
      el.value = v; el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true })); return true };
    set('input[data-path="product_name"]', 'EcoSip 保温杯 750ml');
    set('input[data-path="own_price"]', '22.9');
    set('textarea[data-type="competitors"]', 'AquaPeak | 25.99 | 4.4 | 1842 | lid leaked');
    const btn = document.querySelector('#sk-run');
    if (!btn) return 'no-run';
    btn.click();
    const t0 = Date.now();
    while (Date.now() - t0 < 120000) {
      if (document.querySelector('#sk-result .report-block') && !document.querySelector('#sk-result .sk-loading')) {
        return JSON.stringify({ ok: true, net: window.__net.filter((x) => x.indexOf('async_run') !== -1 || x.indexOf('api/tasks') !== -1) });
      }
      const danger = document.querySelector('#sk-result .callout-danger');
      if (danger) return 'err:' + danger.textContent.trim().slice(0, 80);
      await new Promise((r) => setTimeout(r, 100));
    }
    return 'timeout' })()`)
  let runInfo = {}
  try { runInfo = JSON.parse(skillRun) } catch {}
  check(runInfo.ok === true, '竞品分析跑出报告', String(skillRun).slice(0, 120))
  const calls = runInfo.net || []
  check(calls.some((c) => c.indexOf('async_run=true') !== -1), '慢能力走的是异步接口', calls)
  check(calls.some((c) => c.indexOf('/api/tasks/') !== -1), '确实在轮询任务状态', calls)

  /* ---------------- 设置 ---------------- */
  console.log('\n/settings')
  await ev(`window.CPRouter.go('/settings?section=model', { force: true })`)
  const settingsReady = await waitFor(`!!document.getElementById('section-model')`)
  check(settingsReady, '设置页渲染')
  const st = JSON.parse(
    await ev(`JSON.stringify({
      title: (document.querySelector('.page-title') || {}).textContent || '',
      sections: ['account','model','data','team'].map((k) => !!document.getElementById('section-' + k)),
      auditCard: !!document.getElementById('section-audit'),
      canInvite: !!document.getElementById('btn-invite'),
      teamHint: (document.querySelector('#section-team .callout') || {}).textContent || '',
      activeLine: Array.from(document.querySelectorAll('#section-model .t-xs.t-muted')).map((e) => e.textContent).find((t) => t.indexOf('当前生效') === 0) || '',
      addBtn: (document.getElementById('prov-new') || {}).disabled,
    })`),
  )
  check(st.title === '设置', '标题正确', st.title)
  check(st.sections.every(Boolean), '账号/模型/数据源/团队四张卡都在', st.sections)
  check(st.activeLine.indexOf('当前生效：') === 0, '「当前生效」一行存在', st.activeLine)
  check(
    st.canInvite || /只有 admin \/ owner/.test(st.teamHint),
    '团队卡按角色给出邀请入口或只读说明',
    { canInvite: st.canInvite, hint: st.teamHint.slice(0, 20) },
  )
  check(st.auditCard === st.canInvite, '审计卡只对管理员出现', { audit: st.auditCard, invite: st.canInvite })

  /* ---------------- Agent 市场 ---------------- */
  console.log('\n/agents')
  await ev(`window.CPRouter.go('/agents', { force: true })`)
  // 迁移到 shadcn Card 后不再有 .card 类：按语义钩子断言，不绑样式类名
  const agentsReady = await waitFor(`!!document.querySelector('[data-agent-card]')`)
  check(agentsReady, 'Agent 卡片已渲染')
  const agents = await ev(`JSON.stringify({
    title: (document.querySelector('.page-title') || {}).textContent || '',
    desc: (document.querySelector('.page-desc') || {}).textContent || '',
    cards: document.querySelectorAll('[data-agent-card]').length,
    withRunBtn: document.querySelectorAll('[data-agent-card] [data-agent-run]').length,
    firstName: (document.querySelector('[data-agent-name]') || {}).textContent || '',
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
    const btn = document.querySelector('[data-agent-card] [data-agent-run]');
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
