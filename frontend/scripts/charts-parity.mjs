#!/usr/bin/env node
/**
 * 图表语义对照：新 `src/lib/charts.ts` ↔ 旧 `js/charts.js`。
 *
 * 为什么不用 Node 做：这两个函数直接产出 SVG 字符串并操作 DOM
 * （clientWidth 实测宽度、ResizeObserver、浮层定位），没有 DOM 就跑不起来。
 * 办法是在页面里建两个同样宽度的宿主：一个用主页面上的 TS 实现画，
 * 另一个放进 iframe（里面单独加载旧 js/charts.js）画，然后逐字节比对 innerHTML。
 *
 * 用法：node scripts/charts-parity.mjs [base]
 */
import { spawn } from 'node:child_process'
import { rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8200'
const PORT = 9900 + (Date.now() % 60)
const profile = join(tmpdir(), `cp-chartpar-${Date.now()}`)

const edge = spawn(
  EDGE,
  ['--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
    '--window-size=1440,1000', 'about:blank'],
  { stdio: 'ignore' },
)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let failed = 0
const check = (ok, label, detail = '') => {
  if (ok) console.log(`  PASS  ${label}${detail ? '  ' + detail : ''}`)
  else {
    failed += 1
    console.log(`  FAIL  ${label}${detail ? '  ' + detail : ''}`)
  }
}

/* 在页面里执行的比对代码（主页面 = TS，iframe = 旧实现） */
const COMPARE = `
(async () => {
  const W = 600;

  const makeHost = (doc, w) => {
    const d = doc.createElement('div');
    d.style.width = w + 'px';
    d.style.height = '240px';
    doc.body.appendChild(d);
    return d;
  };

  const iframe = document.createElement('iframe');
  iframe.style.cssText = 'width:900px;height:600px;position:fixed;left:-9999px;top:0';
  iframe.srcdoc = '<!doctype html><html><head><link rel="stylesheet" href="/css/tokens.css"></head><body></body></html>';
  document.body.appendChild(iframe);
  await new Promise((r) => { iframe.onload = r; setTimeout(r, 3000); });

  // iframe 里单独加载旧实现
  await new Promise((resolve, reject) => {
    const s = iframe.contentDocument.createElement('script');
    s.src = '/js/charts.js';
    s.onload = resolve;
    s.onerror = () => reject(new Error('legacy charts.js load failed'));
    iframe.contentDocument.head.appendChild(s);
  });

  const TS = window.CPChart;
  const OLD = iframe.contentWindow.CPChart;

  const cases = {
    line7: {
      kind: 'line',
      spec: {
        series: [
          { date: '2026-10-22', value: 3 }, { date: '2026-10-23', value: 0 },
          { date: '2026-10-24', value: 7 }, { date: '2026-10-25', value: 12 },
          { date: '2026-10-26', value: 5 }, { date: '2026-10-27', value: 9 },
          { date: '2026-10-28', value: 1 },
        ],
        format: 'number', height: 148, label: '近 7 天任务数量趋势',
      },
    },
    line1: { kind: 'line', spec: { series: [{ date: '2026-10-28', value: 42 }], format: 'number' } },
    lineMoney: {
      kind: 'line',
      spec: {
        series: [{ date: '2026-10-27', value: 1234.5 }, { date: '2026-10-28', value: 98765.4 }],
        format: 'money', currency: 'CNY', height: 200, label: '销售额',
      },
    },
    lineEmpty: { kind: 'line', spec: { series: [] } },
    bars24: {
      kind: 'bars',
      spec: {
        series: Array.from({ length: 24 }, (_, i) => ({ hour: i, value: (i * 7) % 13 })),
        format: 'number', height: 168, label: '24 小时分布',
      },
    },
    barsCost: {
      kind: 'bars',
      spec: {
        series: [
          { label: '采购成本', value: 12.5 }, { label: '头程运费', value: 3.2 },
          { label: '平台佣金', value: 4.1 }, { label: '履约配送费', value: 2.8 },
        ],
        categories: true, format: 'number', height: 168, label: '成本构成',
      },
    },
    barsEmpty: { kind: 'bars', spec: { series: [] } },
  };

  const out = {};
  for (const [name, item] of Object.entries(cases)) {
    const hostA = makeHost(document, W);
    const hostB = makeHost(iframe.contentDocument, W);
    TS[item.kind](hostA, JSON.parse(JSON.stringify(item.spec)));
    OLD[item.kind](hostB, JSON.parse(JSON.stringify(item.spec)));
    out[name] = { a: hostA.innerHTML, b: hostB.innerHTML };
  }

  const fmtCases = [
    ['money', 0, 'USD'], ['money', 999.5, 'USD'], ['money', 1234, 'USD'],
    ['money', 1234567, 'CNY'], ['money', -2500, 'EUR'], ['money', 12.345, 'GBP'],
    ['moneyFull', 0, 'USD'], ['moneyFull', 1234.5, 'CNY'], ['moneyFull', 9876543.21, 'JPY'],
    ['num', 0], ['num', 12.34], ['num', 9999], ['num', 12345], ['num', 1234567], ['num', -5],
    ['pct', 0.1234], ['pct', 42], ['pct', 'abc'],
    ['format', 1234, 'money', 'USD'], ['format', 1234, 'percent'], ['format', 1234, 'ratio'],
  ];
  const fmts = fmtCases.map(([fn, ...args]) => {
    let a; let b;
    try { a = TS[fn](...args) } catch (e) { a = 'THROW ' + e.message }
    try { b = OLD[fn](...args) } catch (e) { b = 'THROW ' + e.message }
    return { fn, args, a, b };
  });

  return JSON.stringify({ html: out, fmts });
})()
`

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
    if (m.id && pending.has(m.id)) {
      pending.get(m.id)(m)
      pending.delete(m.id)
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
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
    if (r.result?.exceptionDetails) {
      return 'THROW ' + (r.result.exceptionDetails.exception?.description || '').slice(0, 400)
    }
    return r.result?.result?.value
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Page.navigate', { url: `${BASE}/dashboard` })
  await sleep(3000)

  console.log('\n图表语义对照（TS ↔ 旧 js/charts.js）\n' + '─'.repeat(56))

  const raw = await ev(COMPARE)
  if (typeof raw !== 'string' || raw.startsWith('THROW')) {
    console.error('比对脚本执行失败：', raw)
    ws.close(); edge.kill()
    process.exit(1)
  }
  const data = JSON.parse(raw)

  for (const [name, pair] of Object.entries(data.html)) {
    const same = pair.a === pair.b
    check(same, `${name} SVG 逐字节一致`, same ? '' : `旧 ${pair.b.length} 字符 / 新 ${pair.a.length} 字符`)
    if (!same) {
      let i = 0
      while (i < Math.min(pair.a.length, pair.b.length) && pair.a[i] === pair.b[i]) i += 1
      console.log(`        首个差异在 ${i}：旧「${pair.b.slice(i, i + 70)}」 新「${pair.a.slice(i, i + 70)}」`)
    }
  }

  for (const f of data.fmts) {
    check(f.a === f.b, `${f.fn}(${JSON.stringify(f.args)}) 一致`, f.a === f.b ? String(f.a) : `旧 ${String(f.b)} / 新 ${String(f.a)}`)
  }

  console.log('─'.repeat(56))
  ws.close()
  edge.kill()
  await sleep(200)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}

  if (failed) {
    console.error(`\n图表不一致：${failed} 项\n`)
    process.exit(1)
  }
  console.log('\n图表输出逐字节一致\n')
}

main().catch((e) => {
  console.error('FAIL', e.message)
  edge.kill()
  process.exit(1)
})
