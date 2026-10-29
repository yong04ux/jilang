// 店铺经营助手四子页截图探针
// 用法：node scripts/ui_store_shot.mjs [baseUrl] [outDir] [filter]
// 先登录（首选 CP_USER/CP_PASS，避免 /api/auth/demo 撞 IP 限流），
// 再用应用内路由跳转（等同点击导航，避免整页刷新后 boot 时序问题），
// 页面内单次轮询等就绪元素，最后断言布局 + 截图。
import { spawn } from 'node:child_process'
import { writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8300'
const OUT_DIR = process.argv[3] || join(tmpdir(), 'cp-store-shots')
const ONLY = process.argv[4] || ''
const W = 1440
const H = 1000
const PORT = 9600 + (Date.now() % 300)
const profile = join(tmpdir(), `cp-edge-store-${Date.now()}`)

mkdirSync(OUT_DIR, { recursive: true })

const PAGES = [
  // 热身截图：就绪条件用「一定存在」的 KPI 行。
  // 原先等 .st-metric 是错的：未绑定店铺时 /api/marketplace/metrics 返回 409，
  // 工作台不会渲染「经营概览」，这个选择器永远等不到。
  { name: '0-workbench', path: '/dashboard', ready: '[data-kpi]' },
  { name: '1-dashboard', path: '/stores', ready: '.st-metric' },
  { name: '2-dashboard-orders', path: '/stores?seg=orders', ready: '.st-grid-2' },
  { name: '3-dashboard-ads', path: '/stores?seg=ads', ready: '.st-metrics--ads .st-metric' },
  { name: '4-dashboard-inventory', path: '/stores?seg=inventory', ready: '.st-breakdown-row' },
  { name: '5-dashboard-aftersales', path: '/stores?seg=aftersales', ready: '.st-table tbody tr' },
  { name: '6-product', path: '/stores/product', ready: '.st-table tbody tr' },
  // path 在登录后会按「该店铺真实的第一个 ASIN」重写：写死 ASIN 会因为目录不同而必然 MISS
  { name: '6b-product-detail', path: '/stores/product', ready: '.st-product-title' },
  { name: '7-ledger', path: '/stores/ledger', ready: '.st-table tbody tr' },
  { name: '8-ledger-orders', path: '/stores/ledger?kind=orders', ready: '.st-table tbody tr' },
  { name: '9-authorize', path: '/stores/authorize', ready: '.st-card' },
].filter((p) => !ONLY || ONLY.split(",").some((key) => p.name.includes(key.trim())))

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  `--window-size=${W},${H}`, 'about:blank',
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
  const errors = []
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id) }
    if (msg.method === 'Runtime.exceptionThrown') {
      errors.push('EXCEPTION: ' + (msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text))
    }
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
      errors.push('CONSOLE: ' + msg.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
    }
  }
  await new Promise((resolve) => (ws.onopen = resolve))

  const send = (method, params = {}) => new Promise((resolve) => {
    id += 1; pending.set(id, resolve)
    ws.send(JSON.stringify({ id, method, params }))
  })

  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || 'eval failed')
    return r.result?.result?.value
  }

  await send('Page.enable')
  await send('Runtime.enable')

  const USER = process.env.CP_USER || ''
  const PASS = process.env.CP_PASS || ''
  await send('Page.navigate', { url: `${BASE}/dashboard` })
  await sleep(2500)

  // 登录：库是跨境访问，偶尔会瞬断，重试几次再判定失败
  let loggedIn = ''
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    loggedIn = await evaluate(`(async () => {
      const payload = ${JSON.stringify({ username: USER, password: PASS })};
      const url = payload.username ? '/api/auth/login' : '/api/auth/demo';
      const body = payload.username ? payload : {};
      try {
        const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const d = await r.json().catch(() => ({}));
        if (!d.user) return 'fail:' + (d.detail || r.status);
        // 必须再走一次 CPAuth.load()：它才会把 currentUser 填上并 hide() 关掉登录门。
        // 只 fetch 登录的话，页面渲染在门后面，截出来全是门。
        const u = await window.CPAuth.load();
        if (!u) return 'gate-still-up';
        window.dispatchEvent(new CustomEvent('cp:authenticated'));
        return u.username;
      } catch (err) {
        return 'fail:' + err.message;
      }
    })()`)
    if (loggedIn && String(loggedIn).indexOf('fail') !== 0) break
    console.log(`  login attempt ${attempt}: ${loggedIn}`)
    await sleep(3000)
  }
  console.log('login:', loggedIn)
  if (!loggedIn || String(loggedIn).indexOf('fail') === 0) {
    throw new Error('登录失败，无法继续验收：' + loggedIn)
  }
  await sleep(2500)

  // 单品详情的 ASIN 从真实目录取；没有商品就退回列表页（不再写死 ASIN 造成假 MISS）
  const sampleAsin = await evaluate(`fetch('/api/marketplace/products?limit=1')
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => (d && d.items && d.items[0] ? d.items[0].asin : ''))
    .catch(() => '')`)
  {
    const sixB = PAGES.filter((item) => item.name === '6b-product-detail')[0]
    if (sixB) {
      if (sampleAsin) sixB.path = '/stores/product?asin=' + encodeURIComponent(sampleAsin)
      else {
        sixB.path = '/stores/product'
        sixB.ready = '.st-table tbody tr'
      }
    }
  }


  // 等外壳与路由就绪（页面内轮询，不做 CDP 往返）
  console.log('shell:', await evaluate(`(async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < 20000) {
      if (window.CPRouter && document.getElementById('view-root')) return 'ready';
      await new Promise((r) => setTimeout(r, 150));
    }
    return 'timeout';
  })()`))

  console.log('gate:', await evaluate(`(() => {
    const g = document.getElementById('auth-gate');
    if (!g) return 'none';
    return (g.hasAttribute('hidden') || getComputedStyle(g).display === 'none') ? 'hidden' : 'VISIBLE';
  })()`))

  // 服务端 SPA 回退自检：子页刷新必须是 HTML 外壳，不能是 404 JSON
  console.log('spa-fallback:', await evaluate(`Promise.all(['/stores','/stores/product','/stores/ledger','/stores/authorize']
    .map((p) => fetch(p).then((r) => p + '=' + r.status + ':' + (r.headers.get('content-type') || '').split(';')[0])))
    .then((a) => a.join(' '))`))

  const results = []
  for (const page of PAGES) {
    const before = errors.length
    // 应用内跳转：和点导航链接等价，不走整页刷新
    const navigated = await evaluate(`(async () => {
      try { window.CPRouter.go(${JSON.stringify(page.path)}, { force: true }); }
      catch (e) { return 'THROW ' + e.message; }
      const t0 = Date.now();
      // 本机到新加坡库单次往返 1~2s，一个接口要开好几次连接，
      // 实测 /api/stores + /api/marketplace/dashboard 叠起来能到 30s 以上，
      // 所以这里给到 120s；线上（同机房）不会有这个问题。
      while (Date.now() - t0 < 240000) {
        if (document.querySelector(${JSON.stringify(page.ready)})) return 'ok:' + (Date.now() - t0);
        await new Promise((r) => setTimeout(r, 150));
      }
      return 'timeout';
    })()`)
    const ready = String(navigated).indexOf('ok:') === 0
    if (!ready) console.log('  nav:', navigated)

    // 图表换成 Recharts 并按需加载：页面就绪时图表 chunk 可能还没到。
    // 有宿主的页面等到「出 svg 或出空态」再取样，否则会读成 0。
    if (ready) {
      await evaluate(`(async () => {
        const hosts = Array.from(document.querySelectorAll('#st-trend, #st-hours'))
        if (!hosts.length) return 'no-host'
        // 两个宿主都要落地：只看第一个会量到 charts=1（另一张还在加载）
        const done = (h) => !!h.querySelector('svg') || !!h.querySelector('.cp-chart-empty')
        const t0 = Date.now()
        while (Date.now() - t0 < 20000) {
          if (hosts.every(done)) return 'ok'
          await new Promise((r) => setTimeout(r, 100))
        }
        return 'timeout'
      })()`)
    }

    const facts = await evaluate(`(() => {
      const q = (s) => document.querySelectorAll(s).length;
      const cs = (s, p) => { const el = document.querySelector(s); return el ? getComputedStyle(el)[p] : null; };
      const active = document.querySelector('.st-tab.is-active');
      const grid = document.querySelector('.st-metrics');
      const err = document.querySelector('#view-root .callout-danger');
      return {
        path: location.pathname + location.search,
        title: (document.querySelector('.page-title') || {}).textContent || '',
        error: err ? err.textContent.trim().slice(0, 160) : '',
        tabs: q('.st-tab'),
        activeTab: active ? active.textContent : '',
        cards: q('.st-card'),
        metrics: q('.st-metric'),
        metricCols: grid ? getComputedStyle(grid).gridTemplateColumns.split(' ').length : 0,
        adsCols: (() => { const g = document.querySelector('.st-metrics--ads'); return g ? getComputedStyle(g).gridTemplateColumns.split(' ').length : 0; })(),
        rows: q('.st-table tbody tr'),
        charts: q('.cp-chart svg'),
        todos: q('.st-todo'),
        segTabs: q('.st-seg button'),
        cardRadius: cs('.st-card', 'borderRadius'),
        cardShadow: cs('.st-card', 'boxShadow'),
        thHeight: cs('.st-table th', 'height'),
        metricMinH: cs('.st-metric', 'minHeight'),
        firstName: (() => { const el = document.querySelector('.st-metric-label'); return el ? el.textContent : ''; })(),
        pageWidth: (() => { const el = document.querySelector('.page-inner'); return el ? Math.round(el.getBoundingClientRect().width) : 0; })(),
      };
    })()`)

    const name = `${page.name}.png`
    const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(join(OUT_DIR, name), Buffer.from(cap.result.data, 'base64'))
    results.push({ name, ready, nav: navigated, ...facts, errors: errors.slice(before) })
    console.log((ready ? 'OK  ' : 'MISS') + ' ' + name + ' ' + JSON.stringify(facts))
  }

  const real = errors.filter((e) => !/404|favicon|Failed to load resource/.test(e))
  if (real.length) console.log('ERRORS:\n' + real.slice(0, 10).join('\n'))
  writeFileSync(join(OUT_DIR, 'report.json'), JSON.stringify(results, null, 2))
  console.log('out:', OUT_DIR, real.length ? 'WITH ERRORS' : 'CLEAN')

  ws.close(); edge.kill(); await sleep(300)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
}

main().catch((e) => { console.error('FAIL:', e.message); edge.kill(); process.exit(1) })
