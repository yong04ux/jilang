#!/usr/bin/env node
/**
 * 本轮动效改造的运行时回归（Edge headless + CDP，无第三方依赖）。
 *
 * 覆盖：11 路由截图与控制台零错误、抽屉/弹窗退场（退场中节点仍在、播完卸载）、
 * 设置竖墨条与店铺横墨条、busy spinner、工作台轮询不再整块重绘（页签节点身份稳定）、
 * Radix Sheet 退场、reduced-motion 立即落终态、768/1024 无横向溢出。
 *
 * 用法：node scripts/ui_motion_check.mjs [base]
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8000'
const OUT = resolve(here, '../../docs/shots-motion')
const PORT = 9400 + (Date.now() % 80)
const profile = join(tmpdir(), `cp-motion-check-${Date.now()}`)
mkdirSync(OUT, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1440,1000', 'about:blank',
], { stdio: 'ignore' })

let ws, id = 0
const pending = new Map()
const consoleErrors = []
const fails = []
const notes = []
function send(method, params = {}) {
  return new Promise((res, rej) => {
    const mid = ++id
    pending.set(mid, { res, rej })
    ws.send(JSON.stringify({ id: mid, method, params }))
    setTimeout(() => { if (pending.has(mid)) { pending.delete(mid); rej(new Error('timeout ' + method)) } }, 25000)
  })
}
async function ev(expression) {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
  if (r.exceptionDetails) throw new Error('eval: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text))
  return r.result.value
}
function check(ok, label, detail = '') {
  if (ok) notes.push(`PASS  ${label}${detail ? '  ' + detail : ''}`)
  else fails.push(`${label}${detail ? ' — ' + detail : ''}`)
}
async function shot(name) {
  const { data } = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(join(OUT, name + '.png'), Buffer.from(data, 'base64'))
}
async function go(path, wait = 1300) {
  await ev(`window.CPRouter.go(${JSON.stringify(path)}, { force: true })`)
  await sleep(wait)
}
async function waitFor(expr, timeout = 12000) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeout) {
    if (await ev(expr)) return true
    await sleep(150)
  }
  return false
}

try {
  let targets
  for (let i = 0; i < 40; i++) {
    try { targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); if (targets.length) break } catch {}
    await sleep(250)
  }
  ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl)
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j })
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id); pending.delete(m.id)
      m.error ? rej(new Error(m.error.message)) : res(m.result)
    } else if (m.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text)
    } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErrors.push(m.params.args.map((a) => a.value ?? a.description).join(' '))
    }
  }
  await send('Runtime.enable')
  await send('Page.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
  await send('Page.navigate', { url: `${BASE}/dashboard` })
  await sleep(2000)
  // 新注册账号，避开 /api/auth/demo 的按 IP 每小时限流（与 ui_pages_smoke 同口径）
  const user = 'motion_' + Date.now().toString(36)
  const login = await ev(`(async () => {
    const r = await fetch('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: ${JSON.stringify(user)}, password: 'password123' }) });
    if (!r.ok) return 'register:' + r.status;
    const u = await window.CPAuth.load();
    if (!u) return 'gate-still-up';
    window.dispatchEvent(new CustomEvent('cp:authenticated'));
    return u.username })()`)
  check(typeof login === 'string' && !/^(register|gate)/.test(login), '注册并关闭登录门', String(login))
  await sleep(1200)

  /* demo 账号可能没有任务：造一条，抽屉/任务表才有得测（与 ui_pages_smoke 同口径） */
  const seeded = await ev(`(async () => {
    const ds = await (await fetch('/api/demo/dataset', { credentials: 'same-origin' })).json();
    const ar = ds.analysis_request || {};
    const r = await fetch('/api/agent/runs', { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_key: 'main', goal: null, product_name: ar.product_name,
        platform: 'amazon', marketplace: 'US', competitors: ar.competitors || [], keywords: [],
        own_specs: {}, own_key_features: [], own_price: null, with_listing: false,
        listing_language: 'en-US', data_source: 'manual', async_run: true }) });
    if (!r.ok) return 'run:' + r.status;
    const d = await r.json();
    const t0 = Date.now();
    while (Date.now() - t0 < 90000) {
      const t = await (await fetch('/api/tasks/' + d.task_id, { credentials: 'same-origin' })).json();
      const st = (t.task || {}).status;
      if (st && !/running|queued|pending/.test(st)) return 'done:' + st;
      await new Promise((r2) => setTimeout(r2, 800));
    }
    return 'timeout';
  })()`)
  check(String(seeded).indexOf('done:') === 0, '造一条任务供抽屉/任务表断言', String(seeded))

  /* ---------------- 11 路由 ---------------- */
  const routes = ['dashboard', 'workbench', 'tasks', 'data', 'agents', 'skills', 'stores', 'stores/authorize', 'stores/product', 'stores/ledger', 'settings']
  for (const r of routes) {
    await go('/' + r)
    const st = await ev(`(() => ({
      overflow: document.documentElement.scrollWidth > innerWidth,
      title: (document.querySelector('.page-title') || {}).textContent || '',
      ink: document.querySelectorAll('.tab-ink, .set-ink').length
    }))()`)
    check(!st.overflow, `/${r} 无横向溢出`)
    check(st.title.length > 0 || r === 'workbench', `/${r} 页面已渲染`, st.title)
    await shot('route-' + r.replace(/\//g, '-'))
  }

  /* ---------------- 墨条 ---------------- */
  await go('/settings')
  const setInk0 = await ev(`(() => { const i = document.querySelector('.set-ink'); return i ? { h: parseFloat(i.style.height), t: i.style.transform } : null })()`)
  check(setInk0 && setInk0.h > 10, '设置竖墨条已量出高度', JSON.stringify(setInk0))
  await ev(`document.querySelectorAll('.set-nav-item')[2].click()`)
  await sleep(500)
  const setInk1 = await ev(`document.querySelector('.set-ink').style.transform`)
  check(setInk1 !== setInk0.t, '设置竖墨条滑到新分区', `${setInk0.t} → ${setInk1}`)
  await shot('state-set-ink')

  await go('/stores')
  const stInk = await ev(`(() => { const i = document.querySelector('.st-tabs .tab-ink'); return i ? parseFloat(i.style.width) : -1 })()`)
  check(stInk > 10, '店铺横墨条已量出宽度', `${stInk}px`)

  /* ---------------- 抽屉退场 ---------------- */
  await go('/tasks')
  check(await waitFor(`document.querySelectorAll('#task-body table tbody tr').length > 0`), '任务表有行')
  await ev(`document.querySelector('#task-body table tbody tr').click()`)
  check(await waitFor(`!!document.querySelector('#task-drawer-body')`), '抽屉打开')
  check(await ev(`document.querySelector('.drawer.is-wide').getAttribute('data-state')`) === 'open', '抽屉 data-state=open')
  await shot('state-drawer-open')
  await ev(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`)
  await sleep(80)
  const mid = await ev(`(() => { const d = document.querySelector('.drawer.is-wide'); return d ? d.getAttribute('data-state') : 'gone' })()`)
  check(mid === 'closed', 'Esc 后退场中节点仍在且 data-state=closed', mid)
  await shot('state-drawer-exit')
  check(await waitFor(`!document.querySelector('.drawer.is-wide')`, 4000), '退场播完节点卸载')

  /* ---------------- 弹窗退场 ---------------- */
  await go('/settings')
  await ev(`document.getElementById('btn-audit').click()`)
  check(await waitFor(`!!document.getElementById('audit-modal')`), '审计弹窗打开')
  check(await ev(`document.getElementById('audit-modal').getAttribute('data-state')`) === 'open', '弹窗 data-state=open')
  await ev(`document.getElementById('audit-modal').click()`)
  await sleep(60)
  const mmid = await ev(`(() => { const m = document.getElementById('audit-modal'); return m ? m.getAttribute('data-state') : 'gone' })()`)
  check(mmid === 'closed', '弹窗退场中节点仍在', mmid)
  check(await waitFor(`!document.getElementById('audit-modal')`, 4000), '弹窗退场播完卸载')

  /* ---------------- busy spinner（demo 账号禁存 Key，用技能运行按钮） ---------------- */
  await go('/skills?skill=competitor_analysis')
  check(await waitFor(`!!document.querySelector('#sk-form')`), '技能表单已渲染')
  await ev(`document.querySelector('#sk-run').click()`)
  const sawSpin = await waitFor(`!!document.querySelector('#sk-run .cp-spin')`, 4000)
  check(sawSpin, '技能运行按钮 busy 期间有 cp-spin')
  await sleep(1500)

  /* ---------------- Radix Sheet 退场 ---------------- */
  await go('/agents')
  await ev(`document.querySelector('[data-agent-detail]').click()`)
  const sheetOpen = await waitFor(`!!document.querySelector('[data-slot="sheet-content"][data-state="open"]')`)
  check(sheetOpen, 'Agent Sheet 打开')
  if (sheetOpen) {
    const anim = await ev(`getComputedStyle(document.querySelector('[data-slot="sheet-content"]')).animationName`)
    check(anim !== 'none', 'Sheet 内容层有进场动画', anim)
    await shot('state-sheet-open')
    await ev(`document.querySelector('[data-slot="sheet-content"] [aria-label="关闭"]').click()`)
    await sleep(60)
    const sexit = await ev(`(() => { const s = document.querySelector('[data-slot="sheet-content"]'); return s ? getComputedStyle(s).animationName : 'gone' })()`)
    check(sexit !== 'gone' && sexit !== 'none', 'Sheet 退场动画在播（Radix 等动画结束才卸载）', sexit)
    check(await waitFor(`!document.querySelector('[data-slot="sheet-content"]')`, 4000), 'Sheet 退场后卸载')
  }

  /* ---------------- 工作台轮询不 churn ---------------- */
  await go('/workbench')
  await ev(`(() => { const i = document.querySelector('#composer-input'); i.value = '分析 EcoSip 750ml 的竞品'; i.dispatchEvent(new Event('input', { bubbles: true })); return 1 })()`)
  await sleep(300)
  await ev(`document.querySelector('#composer-send').click()`)
  const paramsUp = await waitFor(`!!document.querySelector('#wb-run-task')`, 10000)
  check(paramsUp, 'composer 提交后进入参数确认卡')
  if (paramsUp) {
    // runFlow 校验商品名与竞品：先载入示例数据把必填项填上
    await ev(`document.querySelector('#wb-demo').click()`)
    await sleep(400)
    await ev(`document.querySelector('#wb-run-task').click()`)
  }
  const tabsUp = await waitFor(`!!document.querySelector('.res-tabs')`, 15000)
  check(tabsUp, '工作台进入 run 态出现结果页签')
  if (tabsUp) {
    // runFlow 在 POST 前后各整页 render 一次（启动期一次性重绘）；等它落定再埋点，
    // 否则会把启动期的第二次 render 误判成轮询 churn
    await sleep(800)
    /* 运行期间轮询只该 patch 段内内容：pane 直接子节点与 .res-tabs 身份都不该变。
       任务完成时 onDone 会整页重绘一次，那是预期行为，不算 churn。 */
    await ev(`(() => {
      window.__tabsNode = document.querySelector('.res-tabs');
      window.__wholesale = 0;
      window.__headSwap = 0;
      const pane = document.querySelector('#wb-res-pane');
      window.__mo = new MutationObserver((rs) => {
        if (!document.querySelector('.progress.is-indeterminate')) return;
        for (const r of rs) {
          if (r.target !== pane) continue;
          const gone = Array.from(r.removedNodes);
          // 整块重写的特征：页签条或滚动容器被一起移除；定向换 head 不算
          if (gone.some((n) => n.nodeType === 1 && (n.matches('.res-tabs') || n.matches('.res-body')))) window.__wholesale++;
          else window.__headSwap++;
        }
      });
      window.__mo.observe(pane, { childList: true });
      return 1;
    })()`)
    let stableMs = 0
    let churnWhileRunning = false
    let completedRemount = false
    for (let i = 0; i < 60; i++) {
      const s = await ev(`(() => ({
        run: !!document.querySelector('.progress.is-indeterminate'),
        same: document.querySelector('.res-tabs') === window.__tabsNode,
        wholesale: window.__wholesale,
        headSwap: window.__headSwap
      }))()`)
      if (s.wholesale > 0 || (s.run && !s.same)) { churnWhileRunning = true; break }
      if (!s.same) { completedRemount = true; break }
      if (s.run) stableMs += 250
      if (!s.run && stableMs > 0) { completedRemount = true; break }
      await sleep(250)
    }
    const swaps = await ev(`({ wholesale: window.__wholesale, headSwap: window.__headSwap })`)
    await ev(`window.__mo.disconnect()`)
    check(!churnWhileRunning, '运行期间无整块重绘（页签/滚动容器未被移除）', JSON.stringify(swaps))
    check(stableMs >= 1000 || completedRemount, '观察窗口覆盖到运行期或完成重绘', `stable=${stableMs}ms completed=${completedRemount}`)
    const inkOk = await waitFor(
      `(() => {
        if (!document.querySelector('.res-tabs')) return false;
        const i = document.querySelector('.res-tabs .tab-ink');
        return !!i && parseFloat(i.style.width || '0') > 10;
      })()`,
      4000,
    )
    const inkState = await ev(`(() => ({
      tabs: !!document.querySelector('.res-tabs'),
      n: document.querySelectorAll('.res-tabs .tab-ink').length,
      w: parseFloat((document.querySelector('.res-tabs .tab-ink') || { style: {} }).style.width || '0')
    }))()`)
    if (inkState.tabs) check(inkOk && inkState.n === 1, '墨条只有一条且已量出宽度', JSON.stringify(inkState))
    else notes.push('INFO  结果页签为空（本轮任务无可用页签），跳过墨条断言')
    await ev(`(() => { const b = document.querySelectorAll('.res-tabs .res-tab')[1]; if (b) b.click(); return !!b })()`)
    await sleep(500)
    await shot('state-workbench-run')
  }

  /* ---------------- 第二批：走纸切页 ---------------- */
  await go('/tasks', 900) // 预热目标页，保证 lazy 已解析，才能验同步契约
  const travel = await ev(`(() => {
    window.CPRouter.go('/settings', { force: true });
    return {
      title: (document.querySelector('.page-title') || {}).textContent || '',
      path: location.pathname,
      ghost: !!document.querySelector('.cp-page-ghost'),
      feed: document.documentElement.dataset.cpFeed === '1'
    };
  })()`)
  check(travel.title === '设置', '走纸：go() 返回时已是新页（同步契约不变）', JSON.stringify(travel))
  check(travel.ghost, '走纸：旧页克隆层已就位')
  check(travel.feed, '走纸：过渡标记存在')
  await sleep(110)
  const ghostMid = await ev(`(() => { const g = document.querySelector('.cp-page-ghost'); return g ? getComputedStyle(g).transform : 'gone' })()`)
  check(ghostMid !== 'none' && ghostMid !== 'gone', '走纸：旧页正在向左抽走', String(ghostMid).slice(0, 42))
  await shot('state-page-feed')
  check(
    await waitFor(`(() => { const g = document.querySelector('.cp-page-ghost'); return !g || getComputedStyle(g).display === 'none' })()`, 3000),
    '走纸：播完克隆层已收起',
  )
  check(await ev(`!document.querySelector('.view.view--fed') || getComputedStyle(document.querySelector('.view')).animationName === 'none'`), '走纸：新页没有叠第二层 CSS 进场')

  /* ---------------- 第二批：列表 FLIP ---------------- */
  await go('/tasks', 1200)
  await waitFor(`document.querySelectorAll('#task-body table tbody tr').length > 1`, 8000)
  const rowCount = await ev(`document.querySelectorAll('#task-body table tbody tr').length`)
  if (rowCount > 1) {
    await ev(`(() => { const s = document.getElementById('task-sort'); s.value = 'asc'; s.dispatchEvent(new Event('change', { bubbles: true })); return 1 })()`)
    await sleep(60)
    const moved = await ev(`[...document.querySelectorAll('#task-body table tbody tr')].some(tr => getComputedStyle(tr).transform !== 'none')`)
    check(moved, 'FLIP：任务行换序时在中途位移（不是瞬移）', `${rowCount} 行`)
    await sleep(500)
    const settled = await ev(`[...document.querySelectorAll('#task-body table tbody tr')].every(tr => { const t = getComputedStyle(tr).transform; return t === 'none' || t === 'matrix(1, 0, 0, 1, 0, 0)' })`)
    check(settled, 'FLIP：位移播完归位')
    await shot('state-flip-tasks')
  } else {
    notes.push('INFO  任务行不足 2 条，跳过 FLIP 位移断言')
  }

  await go('/skills', 1200)
  const flipKeys = await ev(`document.querySelectorAll('.sk-grid .sk-card[data-flip-key]').length`)
  check(flipKeys > 0, '技能墙卡片带 FLIP key', `${flipKeys} 张`)
  if (flipKeys > 1) {
    const before = await ev(`document.querySelectorAll('.sk-grid .sk-card').length`)
    await ev(`(() => {
      const chips = document.querySelectorAll('[data-facet] .chip, [data-facet] button');
      if (chips.length) { chips[1].click(); return 1 }
      const s = document.getElementById('sk-search');
      if (s) { s.value = 'a'; s.dispatchEvent(new Event('input', { bubbles: true })); return 2 }
      return 0
    })()`)
    await sleep(60)
    const skMoved = await ev(`[...document.querySelectorAll('.sk-grid .sk-card')].some(c => getComputedStyle(c).transform !== 'none')`)
    const after = await ev(`document.querySelectorAll('.sk-grid .sk-card').length`)
    check(skMoved || after === before, 'FLIP：技能墙过滤时卡片有位移补间或集合未变', `${before} → ${after} moved=${skMoved}`)
    await sleep(500)
  }

  /* ---------------- 第二批：骨架显影（限速 + 禁用缓存，逼出慢 chunk） ---------------- */
  await send('Network.enable')
  await send('Network.setCacheDisabled', { cacheDisabled: true })
  await send('Network.emulateNetworkConditions', {
    offline: false, latency: 700, downloadThroughput: 400 * 1024, uploadThroughput: 400 * 1024,
  })
  await send('Page.reload', { ignoreCache: true })
  const booted = await waitFor(`!!document.querySelector('.page-title') && (!document.getElementById('auth-gate') || document.getElementById('auth-gate').hidden)`, 40000)
  check(booted, '显影：限速下页面仍能启动')
  if (booted) {
    await ev(`window.CPRouter.go('/stores/ledger', { force: true })`)
    const veilUp = await waitFor(`!!document.querySelector('.page-veil')`, 5000)
    check(veilUp, '显影：慢 chunk 时骨架层出现')
    if (veilUp) {
      await sleep(380) // 等骨架淡入与旧页克隆交接完成再截图
      await shot('state-veil')
      const veilGone = await waitFor(`!document.querySelector('.page-veil')`, 30000)
      check(veilGone, '显影：内容落地后骨架层收起')
      check(await waitFor(`!!document.querySelector('.page-title')`, 15000), '显影：目标页内容已渲染')
    }
  }
  await send('Network.setCacheDisabled', { cacheDisabled: false })
  await send('Network.emulateNetworkConditions', {
    offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1,
  })

  /* ---------------- 第三批：套准 ---------------- */
  const reg = await ev(`(async () => {
    const find = () => {
      const t = document.querySelector('.page-title');
      return t && t.textContent.includes('数据资产') ? t : null;
    };
    const read = (t) => {
      const shadow = getComputedStyle(t).textShadow || '';
      const m = shadow.match(/(-?[\\d.]+)px/);
      return m ? parseFloat(m[1]) : null;
    };
    window.CPRouter.go('/data', { force: true });
    let title = null;
    for (let i = 0; i < 40 && !title; i++) { await new Promise((r) => setTimeout(r, 50)); title = find(); }
    if (!title) return { missing: true };
    const anim = getComputedStyle(title).animationName;
    const first = read(title);
    let last = first;
    for (let i = 0; i < 15; i++) {
      await new Promise((r) => setTimeout(r, 100));
      last = read(find() || title);
      if (last !== null && last <= 3.6) break;
    }
    return { first, last, anim };
  })()`)
  check(!reg.missing && reg.anim === 'mis-settle', '套准：标题进场播 mis-settle', JSON.stringify(reg))
  check(reg.last !== null && reg.last <= 3.6, '套准：洋红版最终归位 3px', String(reg.last))
  check(reg.first === null || reg.last === null || reg.first >= reg.last, '套准：起点比终点更偏', `${reg.first} → ${reg.last}`)

  /* ---------------- 第三批：盖章 ---------------- */
  await go('/tasks', 1200)
  check(await ev(`document.querySelectorAll('.stamp-slam').length === 0`), '盖章：进页面不播（只在状态变更时触发）')
  check(
    await ev(`(() => {
      const probe = document.createElement('span');
      probe.className = 'badge badge-ok stamp-slam';
      document.body.appendChild(probe);
      const name = getComputedStyle(probe).animationName;
      probe.remove();
      return name === 'stamp-slam';
    })()`),
    '盖章：stamp-slam 动画已接上',
  )

  /* ---------------- 第三批：指标计数 ----------------
     用 MutationObserver 记录数字的每一次变化：采样会太晚，420ms 的滚动早跑完了 */
  const counter = await ev(`(async () => {
    window.CPRouter.go('/dashboard', { force: true });
    const seen = new Map();
    const mo = new MutationObserver(() => {
      document.querySelectorAll('[data-count-up]').forEach((n, i) => {
        if (!seen.has(i)) seen.set(i, new Set());
        seen.get(i).add(n.textContent);
      });
    });
    mo.observe(document.getElementById('view-root'), { childList: true, subtree: true, characterData: true });
    await new Promise((r) => setTimeout(r, 1800));
    mo.disconnect();
    const rows = [];
    seen.forEach((set, i) => rows.push([...set]));
    const final = [...document.querySelectorAll('[data-count-up]')].map((n) => n.textContent);
    return { rows, final };
  })()`)
  const rolling = counter.rows.some((values) => values.length >= 3)
  check(rolling, '计数：数字逐帧滚到终值（中途有多种值）', JSON.stringify(counter.rows.map((v) => v.length)))
  check(counter.final.every((v) => /^\d+$/.test(v)), '计数：终值是纯数字', counter.final.join('/'))
  await shot('state-count-up')

  /* ---------------- 第三批：图表生长 ---------------- */
  const chartMotion = await ev(`(() => {
    if (!window.CPChart) return { has: false };
    const bars = document.createElement('div');
    bars.style.cssText = 'position:fixed;left:-9999px;top:0;width:640px';
    document.body.appendChild(bars);
    window.CPChart.bars(bars, { series: [{ label: 'a', value: 3 }, { label: 'b', value: 9 }, { label: 'c', value: 5 }], height: 160 });
    const bar = bars.querySelector('.cp-bar');
    const barAnims = bar ? bar.getAnimations().length : -1;
    const origin = bar ? getComputedStyle(bar).transformOrigin : '';
    const lineHost = document.createElement('div');
    lineHost.style.cssText = 'position:fixed;left:-9999px;top:200px;width:640px';
    document.body.appendChild(lineHost);
    window.CPChart.line(lineHost, { series: [{ label: '1', value: 2 }, { label: '2', value: 5 }, { label: '3', value: 3 }], height: 160 });
    const line = lineHost.querySelector('.cp-chart-line');
    const dash = line ? line.style.strokeDasharray : '';
    bars.remove(); lineHost.remove();
    return { has: true, barAnims, origin, dash };
  })()`)
  check(chartMotion.has && chartMotion.barAnims > 0, '图表：手写柱体首绘在生长', JSON.stringify(chartMotion))
  check(String(chartMotion.dash).length > 0, '图表：手写折线在描出', String(chartMotion.dash))

  /* ---------------- 第三批：滚动揭示 ---------------- */
  await go('/settings', 1400)
  const reveal = await ev(`(() => {
    const nodes = [...document.querySelectorAll('#view-root [data-reveal]')];
    return { total: nodes.length, hidden: nodes.filter(n => getComputedStyle(n).opacity === '0').length };
  })()`)
  check(reveal.total >= 3, '揭示：设置页挂了揭示标记', String(reveal.total))
  if (reveal.hidden > 0) {
    await shot('state-reveal-before')
    await ev(`window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' })`)
    await sleep(1000)
    const shown = await ev(`[...document.querySelectorAll('#view-root [data-reveal]')].filter(n => parseFloat(getComputedStyle(n).opacity) > 0.9).length`)
    check(shown === reveal.total, '揭示：滚过后全部显形（瞬移到底也不漏）', `${shown}/${reveal.total}`)
    await ev(`window.scrollTo({ top: 0, behavior: 'instant' })`)
  } else {
    notes.push('INFO  设置页首屏覆盖全部揭示块，跳过滚动断言')
  }

  /* ---------------- reduced-motion ---------------- */
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] })
  await go('/tasks')
  await waitFor(`document.querySelectorAll('#task-body table tbody tr').length > 0`)
  await ev(`document.querySelector('#task-body table tbody tr').click()`)
  await waitFor(`!!document.querySelector('.drawer.is-wide')`)
  await ev(`document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`)
  await sleep(60)
  check(await ev(`!document.querySelector('.drawer.is-wide')`), 'reduced-motion：关闭立即卸载，不落中间态')
  const redInk = await ev(`(() => { const i = document.querySelector('.set-ink, .tab-ink'); return i ? getComputedStyle(i).transitionDuration : 'none' })()`)
  await go('/settings', 900)
  const redInk2 = await ev(`(() => { const i = document.querySelector('.set-ink'); return i ? { dur: getComputedStyle(i).transitionDuration, h: parseFloat(i.style.height) } : null })()`)
  check(redInk2 && redInk2.dur === '0s' && redInk2.h > 10, 'reduced-motion：墨条无过渡且直接落终态', JSON.stringify(redInk2))
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] })

  /* ---------------- 窄屏 ---------------- */
  for (const width of [1024, 768]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 1000, deviceScaleFactor: 1, mobile: false })
    for (const r of ['dashboard', 'tasks', 'settings', 'stores', 'data']) {
      await go('/' + r, 1000)
      check(!(await ev(`document.documentElement.scrollWidth > innerWidth`)), `${width}px /${r} 无横向溢出`)
    }
    await go('/settings', 900)
    await shot(`narrow-${width}-settings`)
    if (width === 768) {
      await go('/data', 1000)
      await shot('narrow-768-data')
    }
  }

  check(consoleErrors.length === 0, '全程控制台零错误', consoleErrors.slice(0, 3).join(' | '))
} catch (e) {
  fails.push('脚本异常：' + e.message)
} finally {
  try { ws && ws.close() } catch {}
  edge.kill()
  await sleep(400)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
}

console.log('\n动效改造运行时回归\n' + '─'.repeat(58))
notes.forEach((n) => console.log('  ' + n))
if (fails.length) {
  console.error('\n失败 ' + fails.length + ' 项：')
  fails.forEach((f) => console.error('  ✗ ' + f))
  process.exit(1)
}
console.log('\n全部通过 · 截图在 docs/shots-motion/\n')