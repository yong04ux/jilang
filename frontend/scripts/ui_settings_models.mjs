// 设置页「选择模型」验收：
//   1. 新增配置里，「模型」有候选下拉（datalist），默认值来自所选厂商
//   2. 换厂商时候选与默认地址同步换
//   3. 「读取可用模型」没填 Key 时给中文提示，不吐异常原文
//   4. 无开发标记、无 JS 异常、控件尺寸符合规范
import { spawn } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir, homedir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8200'
const OUT = process.argv[3] || join(tmpdir(), 'cp-settings')
const PORT = 9371
const profile = join(homedir(), '.cp-probe-settings-' + Date.now())
mkdirSync(OUT, { recursive: true })

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
  '--no-proxy-server', '--proxy-bypass-list=<-loopback>',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1440,1100', 'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let failures = 0
function check(name, cond, detail = '') {
  console.log(`[${cond ? 'PASS' : 'FAIL'}] ${name}${detail ? ' — ' + detail : ''}`)
  if (!cond) failures += 1
}

const BANNED = ['Mock', 'mock', 'TODO', 'Placeholder', 'Stub', 'task_id', 'base_url', 'en-US', 'Traceback']

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
  const netErrors = []
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data)
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id)
      pending.delete(msg.id)
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)
      return
    }
    if (msg.method === 'Runtime.exceptionThrown') {
      const d = msg.params.exceptionDetails
      errors.push(d.exception?.description || d.text || 'unknown')
    }
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') {
      // 资源加载失败单独记：点「读取可用模型」时故意不带 Key，那一次 400 是预期的
      netErrors.push(msg.params.entry.text)
    }
  }
  await new Promise((r) => { ws.onopen = r })
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const mid = ++id
    pending.set(mid, { resolve, reject })
    ws.send(JSON.stringify({ id: mid, method, params }))
  })
  const evalJs = async (expression) => {
    const res = await send('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true,
    })
    if (res.exceptionDetails) throw new Error(res.exceptionDetails.exception?.description || 'eval failed')
    return res.result.value
  }
  const shot = async (name) => {
    const res = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
    const { writeFileSync } = await import('node:fs')
    writeFileSync(join(OUT, name), Buffer.from(res.data, 'base64'))
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Log.enable')

  // ---- 登录（先注册一个临时账号，避免 demo 接口按 IP 限流）----
  // 注意：登录门不是路由，是盖在页面上的浮层，所以导航到站点根即可
  await send('Page.navigate', { url: `${BASE}/` })
  await sleep(2200)
  const switched = await evalJs(`(() => {
    const btn = document.querySelector('#auth-switch')
    if (btn && /注册/.test(btn.textContent || '')) { btn.click(); return true }
    return false
  })()`)
  if (switched) await sleep(700)
  const filled = await evalJs(`(() => {
    const u = document.querySelector('#auth-username')
    const p = document.querySelector('#auth-password')
    if (!u || !p) return 'no-fields'
    const name = 'probe' + Date.now().toString(36)
    u.value = name
    u.dispatchEvent(new Event('input', { bubbles: true }))
    // 注册模式还有「确认密码」，所有密码框统一填
    document.querySelectorAll('form input[type="password"]').forEach(function (el) {
      el.value = 'password123'
      el.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const f = u.closest('form')
    if (!f) return 'no-form'
    if (f.requestSubmit) f.requestSubmit(); else f.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    return 'ok:' + name
  })()`)
  await sleep(3500)
  const loggedIn = await evalJs(`Boolean(window.CPAuth && window.CPAuth.user)`)
  if (!loggedIn) {
    const snapshot = await evalJs(`document.body.innerText.slice(0, 1200)`)
    console.log('登录失败现场：', filled, '|', snapshot.replace(/\\n/g, ' / '))
  }
  check('登录门已放行', loggedIn, filled)

  // ---- 设置页 ----
  await send('Page.navigate', { url: `${BASE}/settings` })
  await sleep(2500)
  const opened = await evalJs(`(() => {
    const btn = document.querySelector('#prov-new')
    if (!btn) return false
    btn.click()
    return true
  })()`)
  await sleep(800)
  check('可以打开「新增配置」表单', opened)

  const before = await evalJs(`(() => {
    const input = document.querySelector('#prov-form [name="model"]')
    const list = document.querySelector('#prov-model-options')
    const opts = list ? [...list.querySelectorAll('option')].map(o => o.value) : []
    return {
      hasInput: Boolean(input),
      listAttr: input ? input.getAttribute('list') : null,
      value: input ? input.value : null,
      options: opts,
      fetchBtn: Boolean(document.querySelector('#prov-fetch-models')),
      height: input ? Math.round(input.getBoundingClientRect().height) : 0,
      baseHeight: (() => {
        const el = document.querySelector('#prov-form [name="base_url"]')
        return el ? Math.round(el.getBoundingClientRect().height) : 0
      })(),
    }
  })()`)
  check('模型字段存在', before.hasInput)
  check('模型字段挂了候选列表', before.listAttr === 'prov-model-options')
  check('DeepSeek 默认模型是 deepseek-flash', before.value === 'deepseek-flash', String(before.value))
  check('DeepSeek 有候选模型', before.options.length >= 2, before.options.join(' / '))
  check('有「读取可用模型」按钮', before.fetchBtn)
  check(
    '模型输入框与同表单其余输入框等高',
    before.height > 0 && before.height === before.baseHeight,
    `${before.height} vs ${before.baseHeight}`
  )

  // ---- 换厂商：候选与默认地址同步 ----
  const after = await evalJs(`(() => {
    const sel = document.querySelector('#prov-provider')
    sel.value = 'dashscope'
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    const list = document.querySelector('#prov-model-options')
    const input = document.querySelector('#prov-form [name="model"]')
    const base = document.querySelector('#prov-form [name="base_url"]')
    return {
      options: list ? [...list.querySelectorAll('option')].map(o => o.value) : [],
      value: input ? input.value : null,
      base: base ? base.value : null,
    }
  })()`)
  check('换厂商后候选跟着换', after.options.includes('qwen-plus'), after.options.join(' / '))
  check('换厂商后默认模型跟着换', after.value === 'qwen-plus', String(after.value))
  check('换厂商后接口地址跟着换', /dashscope\.aliyuncs\.com/.test(after.base || ''), String(after.base))

  // ---- 原生协议的厂商也要在列表里，且各带自己的默认值 ----
  const vendors = await evalJs(`(() => {
    const sel = document.querySelector('#prov-provider')
    return [...sel.options].map(o => ({ key: o.value, label: o.textContent.trim() }))
  })()`)
  const vendorKeys = vendors.map(v => v.key)
  check(
    '厂商列表含 Anthropic 与 Google',
    vendorKeys.includes('anthropic') && vendorKeys.includes('google'),
    vendorKeys.join(' / ')
  )
  check('厂商列表共 11 家', vendors.length === 11, String(vendors.length))

  const anthropic = await evalJs(`(() => {
    const sel = document.querySelector('#prov-provider')
    sel.value = 'anthropic'
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    return {
      base: document.querySelector('#prov-form [name="base_url"]').value,
      model: document.querySelector('#prov-form [name="model"]').value,
      options: [...document.querySelectorAll('#prov-model-options option')].map(o => o.value),
    }
  })()`)
  check('Anthropic 默认地址正确', /api\.anthropic\.com/.test(anthropic.base), anthropic.base)
  check('Anthropic 预填默认模型', Boolean(anthropic.model), anthropic.model)

  const google = await evalJs(`(() => {
    const sel = document.querySelector('#prov-provider')
    sel.value = 'google'
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    return {
      base: document.querySelector('#prov-form [name="base_url"]').value,
      model: document.querySelector('#prov-form [name="model"]').value,
      options: [...document.querySelectorAll('#prov-model-options option')].map(o => o.value),
    }
  })()`)
  check('Google 默认地址正确', /generativelanguage\.googleapis\.com/.test(google.base), google.base)
  // Gemini 的模型名更新频繁，故意不预置，让用户点「读取可用模型」
  check('Google 不预置模型名', google.model === '' && google.options.length === 0, google.model)

  // ---- 保存后顶栏要跟着变（否则切了配置顶栏还停在上一套）----
  const chipBefore = await evalJs(`(document.querySelector('#provider-flag') || {}).textContent || ''`)
  await evalJs(`(() => {
    const sel = document.querySelector('#prov-provider')
    sel.value = 'dashscope'
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    const model = document.querySelector('#prov-form [name="model"]')
    model.value = 'qwen3.7-plus'
    model.dispatchEvent(new Event('input', { bubbles: true }))
    const key = document.querySelector('#prov-form [name="api_key"]')
    key.value = 'sk-fake-1234567890'
    key.dispatchEvent(new Event('input', { bubbles: true }))
    document.querySelector('#prov-form').requestSubmit()
    return true
  })()`)
  await sleep(2200)
  const chipAfter = await evalJs(`(document.querySelector('#provider-flag') || {}).textContent || ''`)
  check('保存配置后顶栏跟着换模型', chipAfter.includes('qwen3.7-plus'), `${chipBefore} -> ${chipAfter}`)
  // 没点过「测试」就该说未验证，不能默认宣称可用
  check('未测试时顶栏标注未验证', chipAfter.includes('未验证'), chipAfter)

  // ---- 没填 Key 点读取：要给中文提示 ----
  // 保存成功后表单会收起，先重新打开一个空表单
  await evalJs(`(() => {
    const btn = document.querySelector('#prov-new')
    if (btn) btn.click()
    return true
  })()`)
  await sleep(800)
  await evalJs(`document.querySelector('#prov-fetch-models').click()`)
  await sleep(1500)
  const hint = await evalJs(`(() => {
    const el = document.querySelector('#prov-model-hint')
    return el ? el.textContent : ''
  })()`)
  check('没填 Key 时给中文提示', /Key/.test(hint), hint)
  check('提示里没有异常原文', !/Traceback|401|invalid_api_key/.test(hint), hint)

  // ---- 文案与异常 ----
  const pageText = await evalJs(`document.body.innerText`)
  const hits = BANNED.filter((w) => pageText.includes(w))
  check('页面无开发标记', hits.length === 0, hits.join(', '))
  // 点「读取可用模型」故意不带 Key，那一次 400 是预期内的；
  // 只有 5xx 与未捕获异常才算真问题。
  const serverErrors = netErrors.filter((e) => /status of 5\d\d/.test(e))
  check(
    '无未捕获异常 / 无服务端错误',
    errors.length === 0 && serverErrors.length === 0,
    [...errors, ...serverErrors].slice(0, 3).join(' | ')
  )

  await evalJs(`window.scrollTo(0, document.querySelector('#section-model').offsetTop - 10)`)
  await sleep(400)
  await shot('settings-models.png')
  console.log('截图目录：' + OUT)

  ws.close()
  edge.kill()
  console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILED`)
  process.exit(failures === 0 ? 0 : 1)
}

main().catch((err) => {
  console.error('探针异常：', err)
  edge.kill()
  process.exit(1)
})
