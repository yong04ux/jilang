// 定位白屏：打开页面，抓取异常栈与容器内容长度
import { spawn } from 'node:child_process'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const URL_ARG = process.argv[2] || 'http://127.0.0.1:8200/tasks/tsk_8f2e14'
const PORT = 9336
const profile = join(tmpdir(), `cp-edge-diag-${Date.now()}`)

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1440,900', 'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

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
  const logs = []
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id) }
    if (msg.method === 'Runtime.exceptionThrown') {
      const d = msg.params.exceptionDetails
      logs.push('EXCEPTION: ' + (d.exception?.description || d.text))
    }
    if (msg.method === 'Runtime.consoleAPICalled') {
      logs.push(msg.params.type.toUpperCase() + ': ' + msg.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
    }
    if (msg.method === 'Log.entryAdded') {
      logs.push('LOG[' + msg.params.entry.level + ']: ' + msg.params.entry.text + ' ' + (msg.params.entry.url || ''))
    }
  }
  await new Promise((r) => (ws.onopen = r))
  const send = (method, params = {}) => new Promise((resolve) => {
    id += 1; pending.set(id, resolve); ws.send(JSON.stringify({ id, method, params }))
  })
  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true })
    if (r.result?.exceptionDetails) return 'EVAL_ERROR: ' + (r.result.exceptionDetails.exception?.description || '')
    return r.result?.result?.value
  }

  await send('Page.enable'); await send('Runtime.enable'); await send('Log.enable')
  await send('Page.navigate', { url: URL_ARG })
  await sleep(2500)

  console.log('URL:', URL_ARG)
  console.log('view-root html length:', await evaluate('document.getElementById("view-root")?.innerHTML.length'))
  console.log('rail html length:', await evaluate('document.getElementById("rail")?.innerHTML.length'))
  console.log('body text sample:', await evaluate('document.body.innerText.slice(0,200)'))
  console.log('--- console / exceptions ---')
  console.log(logs.join('\n') || '(none)')
  ws.close(); edge.kill(); await sleep(300)
  try { (await import('node:fs')).rmSync(profile, { recursive: true, force: true }) } catch {}
}
main().catch((e) => { console.error('DIAG FAIL:', e.message); edge.kill(); process.exit(1) })
