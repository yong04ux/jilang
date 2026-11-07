// 技能广场（/skills）验收探针
// 用法：node scripts/ui_skills_shot.mjs [baseUrl] [outDir]
//
// 验两件事：
//   1) 广场页：卡片都从接口来、筛选与搜索真的生效、卡片信息完整且文案是业务语言；
//   2) 详情页：点卡片进去能真跑出结果（PRD v3.0 P0 的 F-06）。
import { spawn } from 'node:child_process'
import { writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8123'
const OUT_DIR = process.argv[3] || join(tmpdir(), 'cp-skills-shots')
const W = 1440
const H = 1100
const PORT = 9700 + (Date.now() % 200)
const profile = join(tmpdir(), `cp-edge-skills-${Date.now()}`)

mkdirSync(OUT_DIR, { recursive: true })

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
  // 本机开了系统级 HTTP 代理，localhost 也会被代理吞掉（表现为 502 / fetch 失败），
  // 探针必须显式绕过，否则拿不到本机服务。
  '--no-proxy-server', '--proxy-bypass-list=<-loopback>',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  `--window-size=${W},${H}`, 'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const failures = []

function check(name, ok, detail) {
  if (!ok) failures.push(name)
  console.log((ok ? 'OK   ' : 'FAIL ') + name + (detail === undefined ? '' : '  ' + JSON.stringify(detail)))
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

  const shot = async (name) => {
    const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(join(OUT_DIR, name), Buffer.from(cap.result.data, 'base64'))
  }

  await send('Page.enable')
  await send('Runtime.enable')

  await send('Page.navigate', { url: `${BASE}/skills` })
  await sleep(2500)
  await evaluate(`(async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < 20000) {
      if (window.CPRouter && document.querySelector('#sk-grid-all')) return 'ready';
      await new Promise((r) => setTimeout(r, 150));
    }
    return 'timeout';
  })()`)

  // 现注册一个账号，避开 /api/auth/demo 的按 IP 限流
  const user = 'skillprobe_' + Date.now().toString(36)
  const login = await evaluate(`(async () => {
    const body = { username: ${JSON.stringify(user)}, password: 'password123' };
    const r = await fetch('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) return 'register:' + r.status + ' ' + (await r.text()).slice(0, 120);
    const u = await window.CPAuth.load();
    if (!u) return 'gate-still-up';
    window.dispatchEvent(new CustomEvent('cp:authenticated'));
    return u.username;
  })()`)
  check('登录并关闭登录门', typeof login === 'string' && !/^(register|gate)/.test(login), login)
  await sleep(1500)

  /* ---------------- 一、广场页 ---------------- */

  await evaluate(`window.CPRouter.go('/skills', { force: true })`)
  const gridReady = await evaluate(`(async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < 30000) {
      if (document.querySelectorAll('#sk-all .sk-card').length) return true;
      await new Promise((r) => setTimeout(r, 150));
    }
    return false;
  })()`)
  check('卡片网格渲染出来', gridReady === true)

  const grid = await evaluate(`(() => {
    const q = (s) => document.querySelectorAll(s).length;
    const first = document.querySelector('#sk-all .sk-card');
    const cs = (sel, p) => { const el = first && first.querySelector(sel); return el ? getComputedStyle(el)[p] : null; };
    return {
      title: (document.querySelector('.page-title') || {}).textContent || '',
      featured: q('.sk-section:first-of-type .sk-card'),
      featuredHead: (document.querySelector('.sk-h2') || {}).textContent || '',
      all: q('#sk-all .sk-card'),
      cards: Array.from(document.querySelectorAll('#sk-all .sk-card')).map((el) => ({
        name: (el.querySelector('.sk-card-title') || {}).textContent || '',
        cat: (el.querySelector('.sk-card-cat') || {}).textContent || '',
        avatar: (el.querySelector('.sk-avatar') || {}).textContent || '',
        tags: el.querySelectorAll('.sk-tag').length,
        src: (el.querySelector('.sk-card-src') || {}).textContent || '',
        badge: (el.querySelector('.sk-card-badge') || {}).textContent || '',
        action: (el.querySelector('.btn') || {}).textContent || '',
      })),
      facets: Array.from(document.querySelectorAll('.sk-facet')).map((el) => ({
        label: (el.querySelector('.sk-facet-label') || {}).textContent || '',
        chips: el.querySelectorAll('.sk-chip').length,
        counts: Array.from(el.querySelectorAll('.sk-chip-num')).map((n) => n.textContent),
      })),
      count: (document.querySelector('#sk-count') || {}).textContent || '',
      cardRadius: first ? getComputedStyle(first).borderRadius : null,
      cardShadow: first ? getComputedStyle(first).boxShadow : null,
      avatarSize: (() => { const a = first && first.querySelector('.sk-avatar'); return a ? getComputedStyle(a).width : null; })(),
      rawKeyVisible: /competitor_analysis|listing_generation|profit_calc/.test(document.body.innerText),
    };
  })()`)

  check('页面标题是「技能广场」', grid.title === '技能广场', grid.title)
  check('精选位 3 张卡片', grid.featured === 3, grid.featured)
  check('全量列表 7 项', grid.all === 7, grid.all)
  check('卡片信息完整（头像/分类/标签/来源/运行）',
    grid.cards.every((c) => c.avatar && c.cat && c.tags >= 2 && c.src && c.action === '运行'),
    grid.cards[0])
  check('来源标为「激浪内置」', grid.cards.every((c) => c.src.indexOf('激浪内置') !== -1))
  check('只有需要模型的能力挂「需要密钥」',
    grid.cards.filter((c) => c.badge).length === 1 && grid.cards.filter((c) => c.badge)[0].name.indexOf('Listing 生成') !== -1,
    grid.cards.filter((c) => c.badge).map((c) => c.name))
  check('两组筛选（来源 / 场景分类）', grid.facets.length === 2, grid.facets.map((f) => f.label))
  const facetOk = grid.facets.length === 2 &&
    Number(grid.facets[0].counts[0]) === 7 &&
    grid.facets[1].counts.slice(1).reduce((a, n) => a + Number(n), 0) === 7
  check('筛选计数与真实清单一致', facetOk, grid.facets)
  check('卡片零阴影 + 圆角 12px',
    grid.cardShadow === 'none' && grid.cardRadius === '12px',
    { shadow: grid.cardShadow, radius: grid.cardRadius })
  check('头像 40px', grid.avatarSize === '40px', grid.avatarSize)
  check('页面不暴露内部 key', grid.rawKeyVisible === false)
  await shot('1-skills-plaza.png')

  // 搜索
  const searched = await evaluate(`(async () => {
    const box = document.querySelector('#sk-search');
    if (!box) return 'no-search';
    box.value = '评论';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 250));
    return JSON.stringify({
      n: document.querySelectorAll('#sk-all .sk-card').length,
      names: Array.from(document.querySelectorAll('#sk-all .sk-card-title')).map((e) => e.textContent),
      count: (document.querySelector('#sk-count') || {}).textContent,
    });
  })()`)
  let searchInfo = {}
  try { searchInfo = JSON.parse(searched) } catch {}
  check('搜索「评论」命中相关能力', searchInfo.n >= 1 && searchInfo.n <= 2, searchInfo)
  check('搜索后计数同步', /共\s*\d+\s*项/.test(searchInfo.count || ''), searchInfo.count)

  // 分类筛选
  const filtered = await evaluate(`(async () => {
    const box = document.querySelector('#sk-search');
    if (box) { box.value = ''; box.dispatchEvent(new Event('input', { bubbles: true })); }
    await new Promise((r) => setTimeout(r, 150));
    const chip = Array.from(document.querySelectorAll('[data-facet="cat"]'))
      .find((b) => b.getAttribute('data-value') === '财务核算');
    if (!chip) return 'no-chip';
    chip.click();
    await new Promise((r) => setTimeout(r, 250));
    return JSON.stringify({
      n: document.querySelectorAll('#sk-all .sk-card').length,
      names: Array.from(document.querySelectorAll('#sk-all .sk-card-title')).map((e) => e.textContent),
      active: Array.from(document.querySelectorAll('.sk-chip.is-active')).map((b) => b.textContent.trim()),
      count: (document.querySelector('#sk-count') || {}).textContent,
    });
  })()`)
  let filterInfo = {}
  try { filterInfo = JSON.parse(filtered) } catch {}
  check('点分类只留这一类', filterInfo.n === 1 && (filterInfo.names || [])[0] === '成本与利润测算', filterInfo)
  check('选中态落在刚点的那颗 chip 上',
    (filterInfo.active || []).length === 2 &&
      (filterInfo.active || []).some((t) => t.indexOf('财务核算') === 0) &&
      (filterInfo.active || []).some((t) => t.indexOf('全部') === 0),
    filterInfo.active)

  // 清空筛选
  const cleared = await evaluate(`(async () => {
    const chip = Array.from(document.querySelectorAll('[data-facet="cat"]'))
      .find((b) => b.getAttribute('data-value') === 'all');
    if (!chip) return 'no-all';
    chip.click();
    await new Promise((r) => setTimeout(r, 250));
    return document.querySelectorAll('#sk-all .sk-card').length;
  })()`)
  check('清空筛选恢复全量', cleared === 7, cleared)

  // 空结果
  const empty = await evaluate(`(async () => {
    const box = document.querySelector('#sk-search');
    box.value = 'zzzz';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 250));
    const el = document.querySelector('.sk-empty');
    const text = el ? el.textContent : '';
    box.value = '';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 200));
    return text;
  })()`)
  check('搜不到时给空状态而不是白屏', /没有匹配的技能/.test(empty), empty)

  /* ---------------- 二、点卡片进详情 ---------------- */

  const opened = await evaluate(`(async () => {
    const card = Array.from(document.querySelectorAll('#sk-all .sk-card'))
      .find((el) => el.getAttribute('data-open') === 'profit_calc');
    if (!card) return 'no-card';
    card.click();
    const t0 = Date.now();
    while (Date.now() - t0 < 20000) {
      if (document.querySelector('#sk-form')) return 'ok:' + location.pathname + location.search;
      await new Promise((r) => setTimeout(r, 120));
    }
    return 'timeout';
  })()`)
  check('点卡片进入详情', String(opened).indexOf('ok:/skills?skill=profit_calc') === 0, opened)

  const detail = await evaluate(`(() => ({
    back: (document.querySelector('.sk-back') || {}).textContent || '',
    title: (document.querySelector('.sk-detail .sk-h2') || {}).textContent || '',
    badges: Array.from(document.querySelectorAll('.sk-detail .badge')).map((b) => b.textContent.trim()),
    fields: document.querySelectorAll('#sk-form [data-path]').length,
    labels: Array.from(document.querySelectorAll('#sk-form .field-label')).map((e) => e.textContent.replace('*','').trim()),
  }))()`)
  check('详情有返回入口', /技能广场/.test(detail.back), detail.back)
  check('详情标题是能力名', detail.title === '成本与利润测算', detail.title)
  check('详情标出「本地计算」', detail.badges.indexOf('本地计算') !== -1, detail.badges)
  check('表单由接口入参生成', detail.fields >= 10, detail.fields)
  const isChinese = (t) => /[\u4e00-\u9fa5]/.test(t)
  const badLabels = detail.labels.filter((t) => !isChinese(t))
  check('表单标签全中文', badLabels.length === 0, badLabels)
  await shot('2-skills-detail.png')

  /* ---------------- 三、真跑：本地计算 ---------------- */

  const profitRun = await evaluate(`(async () => {
    const set = (sel, v) => {
      const el = document.querySelector(sel);
      if (!el) return false;
      el.value = String(v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    };
    set('input[data-path="selling_price"]', 29.9);
    set('input[data-path="purchase_cost"]', 9.5);
    set('input[data-path="shipping_cost"]', 3.2);
    document.querySelector('#sk-run').click();
    const t0 = Date.now();
    while (Date.now() - t0 < 60000) {
      if (document.querySelector('#sk-result .sk-kpi-value')) return 'ok';
      const err = document.querySelector('#sk-result .callout');
      if (err && err.textContent.trim()) return 'err:' + err.textContent.trim().slice(0, 120);
      await new Promise((r) => setTimeout(r, 150));
    }
    return 'timeout';
  })()`)
  check('利润测算跑出结果', profitRun === 'ok', profitRun)

  // 成本图是 Recharts 懒加载 chunk：KPI 一出现就数图会读成 0，
  // 等到真的出 svg（或明确空态）再断言
  await evaluate(`(async () => {
    const t0 = Date.now()
    while (Date.now() - t0 < 20000) {
      if (document.querySelector('#sk-result .cp-chart svg, #sk-result .cp-chart-empty')) return 'ok'
      await new Promise((r) => setTimeout(r, 100))
    }
    return 'timeout'
  })()`)

  const profitFacts = await evaluate(`(() => ({
    values: Array.from(document.querySelectorAll('#sk-result .sk-kpi-value')).map((e) => e.textContent.trim()),
    rows: document.querySelectorAll('#sk-result .table tbody tr').length,
    chart: document.querySelectorAll('#sk-result .cp-chart svg').length,
  }))()`)
  check('利润结果有 KPI 数值', profitFacts.values.length >= 4, profitFacts.values.slice(0, 4))
  check('成本构成表有明细行', profitFacts.rows >= 3, profitFacts.rows)
  check('成本构成图渲染成 SVG', profitFacts.chart >= 1, profitFacts.chart)
  await shot('2-skills-profit.png')

  /* ---------------- 四、真跑：需要模型的能力 ---------------- */

  const listing = await evaluate(`(async () => {
    window.CPRouter.go('/skills?skill=listing_generation', { force: true });
    const t0 = Date.now();
    while (Date.now() - t0 < 20000) {
      if (document.querySelector('#sk-form')) return 'ok';
      await new Promise((r) => setTimeout(r, 120));
    }
    return 'timeout';
  })()`)
  check('深链直接打开详情', listing === 'ok', listing)

  const listingLabels = await evaluate(`Array.from(document.querySelectorAll('#sk-form .field-label')).map((e) => e.textContent.replace('*','').trim())`)
  const badListing = listingLabels.filter((t) => !isChinese(t))
  check('嵌套字段也用中文标签', badListing.length === 0, badListing)

  const rawCodes = await evaluate(`(() => {
    const bad = [];
    const pattern = /^(manual|demo|import|en-US|zh-CN|amazon|ebay|walmart|shopee|mercadolibre|fba|fbm|self|short|medium|long)$/;
    document.querySelectorAll('#sk-form [data-path]').forEach((el) => {
      if (el.tagName === 'SELECT') {
        Array.from(el.options).forEach((o) => { if (pattern.test(o.textContent.trim())) bad.push(o.textContent.trim()); });
      } else if (el.value && pattern.test(String(el.value).trim())) {
        bad.push(el.getAttribute('data-path') + '=' + el.value);
      }
    });
    return Array.from(new Set(bad));
  })()`)
  check('表单不露内部枚举码', rawCodes.length === 0, rawCodes)

  const runVisible = await evaluate(`(() => {
    const el = document.querySelector('#sk-run');
    if (!el) return 'no-run';
    const r = el.getBoundingClientRect();
    return r.top >= 0 && r.bottom <= window.innerHeight + 1 ? 'visible' : 'off-screen:' + Math.round(r.top);
  })()`)
  check('运行按钮始终在视口内', runVisible === 'visible', runVisible)

  const keyRun = await evaluate(`(async () => {
    // 先把必填项填齐：参数校验在「缺密钥」之前，不填的话拿到的是 422，
    // 那样就验不到 428 的引导路径了。
    const el = document.querySelector('input[data-path="product.name"]');
    if (el) {
      el.value = 'EcoSip 保温杯 750ml';
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }
    document.querySelector('#sk-run').click();
    const t0 = Date.now();
    while (Date.now() - t0 < 60000) {
      const badge = document.getElementById('sk-engine');
      if (badge) {
        return JSON.stringify({
          text: badge.textContent.trim().slice(0, 60),
          kind: badge.getAttribute('data-engine') || '',
        });
      }
      const err = document.querySelector('#sk-result .callout-danger');
      if (err && err.textContent.trim()) return 'err:' + err.textContent.trim().slice(0, 100);
      await new Promise((r) => setTimeout(r, 150));
    }
    return 'timeout';
  })()`)
  let keyInfo = {}
  try { keyInfo = JSON.parse(keyRun) } catch {}
  /* 这条断言原先验的是「没 Key → 428 → 弹去配置的引导」。BYOK 改版后
     无 Key 也能跑（走规则引擎），428 分支不存在了，于是它会误抓 Listing 的
     质检警告当成功。改成验真正该守的契约：**结果必须如实标注执行引擎**，
     不能让人把规则生成当成模型生成。 */
  const engineOk = Boolean(keyInfo.kind) && /规则|模型/.test(keyInfo.text || '')
  check('结果标注执行引擎（无 Key 时为规则引擎）', engineOk, keyInfo)

  const resultVisible = await evaluate(`(async () => {
    const el = document.querySelector('#sk-result .callout');
    if (!el) return 'no-result';
    const t0 = Date.now();
    while (Date.now() - t0 < 2000) {
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight && r.bottom > 0) return 'visible';
      await new Promise((res) => setTimeout(res, 120));
    }
    return 'off-screen:' + Math.round(el.getBoundingClientRect().top);
  })()`)
  check('结果区没被吸底条压出视口', resultVisible === 'visible', resultVisible)
  await shot('3-skills-needkey.png')

  /* ---------------- 五、异步：竞品分析 ---------------- */

  const compResult = await evaluate(`(async () => {
    window.CPRouter.go('/skills?skill=competitor_analysis', { force: true });
    let t0 = Date.now();
    while (Date.now() - t0 < 20000) {
      if (document.querySelector('#sk-form')) break;
      await new Promise((r) => setTimeout(r, 120));
    }
    const set = (sel, v) => {
      const el = document.querySelector(sel);
      if (!el) return false;
      el.value = v;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    };
    set('input[data-path="product_name"]', 'EcoSip 保温杯 750ml');
    set('input[data-path="own_price"]', '22.9');
    // 格式按表单自己的提示：「名称 | 价格 | 评分 | 评论数 | 一条评论」，只有名称必填
    set('textarea[data-type="competitors"]', [
      'AquaPeak 保温杯 32oz | 25.99 | 4.4 | 1842 | The lid leaked in my bag on day three.',
      'TrailMate 随行杯 20oz | 18.5 | 4.1 | 963 | Hard to clean the narrow opening.',
      'HydraCore 运动水壶 24oz | 31 | 4.6 | 2310 | Started leaking after a month.',
    ].join('\\n'));
    // 用**网络证据**判断走了后台任务：DOM 上采样 loading 不可靠 ——
    // 规则引擎一个任务 GET 就能跑完，loading 只存在一两百毫秒。
    window.__net = [];
    const _f = window.fetch;
    window.fetch = async (...a) => {
      const u = typeof a[0] === 'string' ? a[0] : a[0].url;
      const r = await _f.apply(window, a);
      window.__net.push(r.status + ' ' + u);
      return r;
    };
    const btn = document.querySelector('#sk-run');
    if (!btn) return 'no-run';
    btn.click();
    t0 = Date.now();
    let sawPolling = false;
    while (Date.now() - t0 < 180000) {
      if (document.querySelector('#sk-result .sk-loading, #sk-result .timeline-item')) sawPolling = true;
      const rep = document.querySelector('#sk-result .report-block');
      const err = document.querySelector('#sk-result .callout-danger');
      if (err) return 'err:' + err.textContent.trim().slice(0, 160);
      if (rep && !document.querySelector('#sk-result .sk-loading')) {
        const net = (window.__net || []).filter(
          (x) => x.indexOf('async_run') !== -1 || x.indexOf('api/tasks') !== -1,
        );
        return 'ok polling=' + sawPolling + ' net=' + JSON.stringify(net);
      }
      // 采样 50ms 而不是 200ms：规则引擎跑得快时，loading 态（异步任务 + 轮询）
      // 可能只存在一两百毫秒，200ms 采样会整段错过，误报「没走后台轮询」。
      await new Promise((r) => setTimeout(r, 50));
    }
    return 'timeout';
  })()`)
  check('竞品分析跑出报告', String(compResult).indexOf('ok') === 0, compResult)
  check(
    '慢能力走后台任务并轮询任务状态',
    String(compResult).indexOf('async_run') !== -1 && String(compResult).indexOf('api/tasks') !== -1,
    String(compResult).slice(0, 200),
  )

  const compFacts = await evaluate(`(() => ({
    demo: document.querySelector('#sk-result .callout-warn') ? document.querySelector('#sk-result .callout-warn').textContent.trim().slice(0, 60) : '',
    sections: Array.from(document.querySelectorAll('#sk-result .t-section')).map((e) => e.textContent.trim()),
    rows: document.querySelectorAll('#sk-result .table tbody tr').length,
  }))()`)
  check('报告有内容分节', compFacts.sections.length >= 5, compFacts.sections.slice(0, 8))
  check('报告有对比表格数据', compFacts.rows >= 3, compFacts.rows)
  // 用户自己填的数据不能被标成「示例数据」，否则真实结果会被当成演示数据忽略
  check('自填数据不误标示例数据', !/示例数据/.test(compFacts.demo), compFacts.demo)
  await shot('4-skills-competitor.png')

  /* ---------------- 六、查询串路由（广场 ↔ 详情） ---------------- */

  // 早先 router 比路径时把 ?query 丢了，导致「只改查询串」的跳转既不更新地址栏
  // 也不进历史。这里把这条路径钉住。
  const routeInfo = await evaluate(`(async () => {
    const waitFor = async (fn, ms) => {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) { if (fn()) return true; await new Promise((r) => setTimeout(r, 100)); }
      return false;
    };
    window.CPRouter.go('/skills', { force: true });
    await waitFor(() => document.querySelector('#sk-all .sk-card'), 20000);
    const card = document.querySelector('#sk-all [data-open="data_validation"]');
    if (!card) return JSON.stringify({ err: 'no-card' });
    card.click();
    await waitFor(() => document.querySelector('#sk-form'), 20000);
    const detailUrl = location.pathname + location.search;
    history.back();
    await waitFor(() => document.querySelector('#sk-all .sk-card'), 20000);
    return JSON.stringify({
      detailUrl,
      backUrl: location.pathname + location.search,
      backCards: document.querySelectorAll('#sk-all .sk-card').length,
    });
  })()`)
  let route = {}
  try { route = JSON.parse(routeInfo) } catch {}
  check('详情地址带能力参数', route.detailUrl === '/skills?skill=data_validation', route.detailUrl)
  check('浏览器后退回到广场', route.backUrl === '/skills' && route.backCards === 7, route)

  /* ---------------- 六、别把别的页弄坏 ---------------- */

  const other = await evaluate(`(async () => {
    const out = {};
    for (const [name, path, ready] of [['workbench', '/workbench', '.wb-hero-title'], ['agents', '/agents', '[data-agent-card]']]) {
      window.CPRouter.go(path, { force: true });
      const t0 = Date.now();
      let ok = false;
      while (Date.now() - t0 < 60000) {
        if (document.querySelector('#view-root ' + ready)) { ok = true; break; }
        const err = document.querySelector('#view-root .callout-danger');
        if (err) { out[name] = 'err:' + err.textContent.trim().slice(0, 80); break; }
        await new Promise((r) => setTimeout(r, 150));
      }
      if (ok) out[name] = 'ok';
      else if (!out[name]) out[name] = 'timeout';
      out[name + '_devwords'] = /Mock|TODO|Placeholder|Stub|base_url|task_id/.test((document.querySelector('#view-root') || {}).innerText || '');
    }
    return out;
  })()`)
  check('工作台仍可用', other.workbench === 'ok', other.workbench)
  check('Agent 页仍可用', other.agents === 'ok', other.agents)
  check('页面不含开发标记', other.workbench_devwords === false && other.agents_devwords === false, other)

  const real = errors.filter((e) => !/favicon|Failed to load resource/.test(e))
  if (real.length) console.log('ERRORS:\n' + real.slice(0, 10).join('\n'))
  check('无 JS 异常', real.length === 0, real.slice(0, 3))

  writeFileSync(join(OUT_DIR, 'report.json'), JSON.stringify({ failures, grid, searchInfo, filterInfo, detail, profitFacts, compFacts, keyInfo, other }, null, 2))
  console.log('\n' + (failures.length ? 'FAILED: ' + failures.join(' | ') : 'ALL CHECKS PASSED'))
  ws.close()
  edge.kill()
  process.exit(failures.length ? 1 : 0)
}

main().catch(async (err) => {
  console.error('探针异常:', err.message)
  try { edge.kill() } catch {}
  process.exit(1)
})
