// 数据资产两步导入验收：上传 CSV → 预览列识别 → 字段映射 → 提交 → 错误 CSV
import { spawn } from 'node:child_process'
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8200'
const OUT = process.argv[3] || join(tmpdir(), 'cp-data')
const PORT = 9360
const profile = join(tmpdir(), `cp-edge-data-${Date.now()}`)
mkdirSync(OUT, { recursive: true })

const here = dirname(fileURLToPath(import.meta.url))
const samplePath = join(here, '..', 'examples', 'competitors_sample.csv')

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
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  const errors = []
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
  const goto = async (path) => { await send('Page.navigate', { url: BASE + path }); await sleep(1800) }
  const waitFor = async (expr, timeout = 25000) => {
    const end = Date.now() + timeout
    while (Date.now() < end) { if (await ev(expr)) return true; await sleep(250) }
    return false
  }
  const shot = async (name) => {
    const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(cap.result.data, 'base64'))
  }

  await send('Page.enable'); await send('Runtime.enable'); await send('DOM.enable')

  await goto('/dashboard')
  await ev(`fetch('/api/auth/demo', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:'{}'}).then(r=>r.status)`)
  await goto('/data')
  await waitFor('!!document.getElementById("data-file")', 10000)
  check('数据资产页渲染', await ev('!!document.getElementById("data-file")'))

  // 用 CDP 直接塞文件，模拟用户选择
  const doc = await send('DOM.getDocument', { depth: -1 })
  const node = await send('DOM.querySelector', { nodeId: doc.result.root.nodeId, selector: '#data-file' })
  await send('DOM.setFileInputFiles', {
    nodeId: node.result.nodeId,
    files: [samplePath],
  })
  await sleep(600)
  check('已选择文件', (await ev('document.getElementById("data-filename").textContent')).includes('.csv'))
  check('上传按钮可用', await ev('document.getElementById("data-upload").disabled === false'))

  await ev('document.getElementById("data-upload").click()')
  const previewed = await waitFor('!!document.querySelector("[data-map-col]")', 20000)
  check('预览返回列并渲染映射表', previewed)
  check('识别到的列可映射', (await ev('document.querySelectorAll("[data-map-col]").length')) >= 3)
  await shot('data-preview')

  const canCommit = await ev('(document.getElementById("data-commit")||{}).disabled === false')
  check('校验通过可提交', canCommit)
  if (canCommit) {
    await ev('document.getElementById("data-commit").click()')
    const committed = await waitFor('document.body.innerText.includes("已提交")', 25000)
    check('提交成功', committed)
    await shot('data-committed')
  }

  // 错误文件：逐行错误 + 错误 CSV
  await goto('/data')
  await waitFor('!!document.getElementById("data-file")', 10000)
  const badPath = join(tmpdir(), `cp-bad-${Date.now()}.csv`)
  writeFileSync(badPath, 'name,price\n,1.0\nBadPrice,abc\n')
  const doc2 = await send('DOM.getDocument', { depth: -1 })
  const node2 = await send('DOM.querySelector', { nodeId: doc2.result.root.nodeId, selector: '#data-file' })
  await send('DOM.setFileInputFiles', { nodeId: node2.result.nodeId, files: [badPath] })
  await sleep(500)
  await ev('document.getElementById("data-upload").click()')
  const badDone = await waitFor('document.body.innerText.includes("逐行错误")', 20000)
  check('错误文件显示逐行错误', badDone)
  check('错误可下载 CSV', await ev('!!document.getElementById("data-export-errors")'))
  check('有错误时禁止提交', await ev('document.getElementById("data-commit") === null || document.getElementById("data-commit").disabled === true'))
  await shot('data-errors')

  console.log(errors.length ? `\nCONSOLE ERRORS:\n${errors.slice(0, 5).join('\n')}` : '\nno console errors')
  ws.close(); edge.kill(); await sleep(300)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
  console.log(failures ? `\n${failures} FAILED` : '\nALL DATA FLOW CHECKS PASSED')
  console.log('shots:', OUT)
  process.exit(failures ? 1 : 0)
}
main().catch((e) => { console.error('FAIL:', e.message); edge.kill(); process.exit(1) })
