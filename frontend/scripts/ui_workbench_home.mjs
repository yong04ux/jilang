// 工作台「首页」验收：三段入口（业务 Agent / 专家 / 技能）+ 底部输入框
//   1. 标题、分段控件、输入框同屏
//   2. 三段切换各自渲染正确内容，且不串台
//   3. 点「试试这样说」直接带着目标进参数确认
//   4. 专家卡片可选、选中态可辨、助手选择器同步
//   5. 输入框草稿在分段切换后不丢；提交后进参数确认
//   6. 零阴影 / 圆角 12px / 无 JS 异常 / 无开发标记
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir, homedir } from 'node:os'

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const BASE = process.argv[2] || 'http://127.0.0.1:8200'
const OUT = process.argv[3] || join(tmpdir(), 'cp-wbhome')
const PORT = 9361
const profile = join(homedir(), '.cp-probe-' + Date.now())
mkdirSync(OUT, { recursive: true })

const edge = spawn(EDGE, [
  '--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
  '--no-proxy-server', '--proxy-bypass-list=<-loopback>',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1440,960', 'about:blank',
], { stdio: 'ignore' })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let failures = 0
function check(name, cond, detail = '') {
  console.log(`[${cond ? 'PASS' : 'FAIL'}] ${name}${detail ? ' — ' + detail : ''}`)
  if (!cond) failures += 1
}

const BANNED = ['Mock', 'mock', 'TODO', 'Placeholder', 'Stub', 'task_id', 'base_url', 'en-US', 'Manual', 'manual']

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
  const goto = async (path) => { await send('Page.navigate', { url: BASE + path }); await sleep(2200) }
  const waitFor = async (expr, timeout = 20000) => {
    const end = Date.now() + timeout
    while (Date.now() < end) { if (await ev(expr)) return true; await sleep(250) }
    return false
  }
  const shot = async (name) => {
    const cap = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(cap.result.data, 'base64'))
  }
  const count = (sel) => ev(`document.querySelectorAll(${JSON.stringify(sel)}).length`)
  const text = (sel) => ev(`(document.querySelector(${JSON.stringify(sel)})||{}).textContent||''`)
  /* 输入框必须落在首屏里：分段内容再长也不能把它顶出视口 */
  const composerInView = () => ev(`(() => {
    const c = document.querySelector('.composer'); if (!c) return false
    const r = c.getBoundingClientRect()
    return r.bottom <= innerHeight + 1 && r.top >= 0
  })()`)

  await send('Page.enable'); await send('Runtime.enable')
  await goto('/dashboard')
  /* 「一键体验」按 IP 限流 5 次/小时，探针反复跑很容易撞上；撞上就注册一个临时账号兜底 */
  const demoStatus = await ev(`fetch('/api/auth/demo', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:'{}'}).then(r=>r.status)`)
  if (demoStatus !== 200) {
    const uname = 'probe' + Date.now()
    const rs = await ev(`fetch('/api/auth/register', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:${JSON.stringify(uname)}, password:'Probe!23456', display_name:'验收探针'})}).then(r=>r.status)`)
    check('体验账号或临时账号可用', rs === 200, `demo=${demoStatus} register=${rs}`)
  }
  await goto('/workbench')
  await waitFor('!!document.querySelector(".wb-hero-title")', 12000)

  /* ---------- 首屏骨架 ---------- */
  check('标题在', ((await text('.wb-hero-title')) || '').includes('AI 运营助手'))
  check('分段控件三项', (await count('.wb-seg-item')) === 3)
  check('分段文案正确',
    JSON.stringify(await ev('Array.from(document.querySelectorAll(".wb-seg-item")).map(e=>e.textContent.trim())')) ===
    JSON.stringify(['业务 Agent', '专家', '技能']))
  check('底部输入框在', await ev('!!document.getElementById("composer-input")'))
  check('助手选择器在', await ev('!!document.getElementById("wb-assistant")'))
  check('业务 Agent 段输入框在首屏', await composerInView())
  await shot('wb-home-agent')

  /* ---------- 默认业务 Agent 段 ---------- */
  check('业务 Agent 段有提示语', (await count('.wb-prompt')) >= 3)
  check('业务 Agent 段无技能卡', (await count('.skill-card')) === 0)

  /* ---------- 切到专家 ---------- */
  await ev('document.querySelector(\'[data-seg="expert"]\').click()')
  await sleep(700)
  check('专家段渲染专家卡', (await count('.skill-card')) === 3)
  check('专家段激活态跟着走',
    (await ev('document.querySelector(\'.wb-seg-item.is-active\').getAttribute("data-seg")')) === 'expert')
  check('默认选中主控 Agent', (await count('.skill-card.is-selected')) === 1)
  check('选中的是激浪主控 Agent', ((await text('.skill-card.is-selected .skill-name')) || '').includes('主控'))

  // 选另一个专家
  await ev('document.querySelectorAll(".skill-card")[1].click()')
  await sleep(700)
  const picked = (await text('.skill-card.is-selected .skill-name')) || ''
  check('点了就换选中项', picked.length > 0 && !picked.includes('主控'), picked)
  check('助手选择器同步名字', ((await text('#wb-assistant')) || '').includes(picked.replace(/\s/g, ' ').trim()))
  check('专家段输入框在首屏', await composerInView())
  await shot('wb-home-expert')

  /* ---------- 切到技能 ---------- */
  await ev('document.querySelector(\'[data-seg="skill"]\').click()')
  await sleep(900)
  check('技能段渲染技能卡', (await count('.skill-card')) >= 5)
  check('技能段有分类 chip', (await count('.wb-chips .chip')) >= 2)
  check('技能卡有「需要密钥」标记', (await count('.tag-warn')) >= 1)
  check('技能段入口指向技能广场', await ev('!!document.querySelector(\'.wb-skills-more a[href="/skills"]\')'))

  // 分类筛选真的收敛
  const allCards = await count('.skill-card')
  const chips = await ev('Array.from(document.querySelectorAll(".wb-chips .chip")).map(e=>e.textContent.trim())')
  const chipLabel = chips[1]
  await ev(`(() => { const b = Array.from(document.querySelectorAll(".wb-chips .chip")).find(e=>e.textContent.trim()===${JSON.stringify(chipLabel)}); if (b) b.click(); return true })()`)
  await sleep(700)
  const filtered = await count('.skill-card')
  check('分类筛选生效', filtered > 0 && filtered < allCards, `${chipLabel}: ${filtered}/${allCards}`)
  await ev('document.querySelector(\'.wb-chips .chip\').click()') // 回到推荐
  await sleep(600)
  check('技能段输入框在首屏', await composerInView())
  await shot('wb-home-skill')

  /* ---------- 输入框草稿跨分段保留 ---------- */
  await ev('(() => { const t = document.getElementById("composer-input"); t.value = "帮我看看这个类目的竞品格局"; t.dispatchEvent(new Event("input", {bubbles:true})); return true })()')
  check('有内容时发送键可用', (await ev('document.getElementById("composer-send").disabled')) === false)
  await ev('document.querySelector(\'[data-seg="agent"]\').click()')
  await sleep(700)
  check('切分段后草稿还在',
    (await ev('document.getElementById("composer-input").value')) === '帮我看看这个类目的竞品格局')

  /* ---------- 助手选择器菜单 ---------- */
  await ev('document.getElementById("wb-assistant").click()')
  await sleep(400)
  check('助手菜单能打开', (await count('.wb-menu-item')) === 3)
  check('菜单里标了当前项', (await count('.wb-menu-item.is-active')) === 1)
  await shot('wb-home-assistant')
  await ev('document.querySelector(\'[data-seg="agent"]\').click()') // 点外面 → 关
  await sleep(600)
  check('点空白处菜单关闭', (await count('.wb-menu-item')) === 0)

  /* ---------- 点技能 / 提示语：只带入输入框，不跳页 ---------- */
  await ev('document.querySelector(".wb-prompt").click()')
  await sleep(600)
  check('点提示语不跳页', await ev('!!document.querySelector(".wb-home")'))
  check('提示语带进了输入框',
    ((await ev('document.getElementById("composer-input").value')) || '').length > 5)
  check('输入框上方出现技能说明', (await count('.wb-echo')) === 1)
  await shot('wb-home-picked')

  // 取消带入
  await ev('document.querySelector(\'[data-act="drop-skill"]\').click()')
  await sleep(400)
  check('能取消已带入的技能', (await count('.wb-echo')) === 0)

  // 技能卡同样只带入
  await ev('document.querySelector(\'[data-seg="skill"]\').click()')
  await sleep(800)
  const firstSkill = await text('.skill-card .skill-name')
  await ev('document.querySelector(".skill-card").click()')
  await sleep(600)
  check('点技能卡不跳页', await ev('!!document.querySelector(".wb-home")'))
  check('技能卡标成「已带入」',
    ((await text('.skill-card.is-selected .skill-go')) || '').includes('已带入'), firstSkill)
  check('技能说明对上刚才那张卡',
    ((await text('.wb-echo-title')) || '').includes(firstSkill.trim()))
  await shot('wb-home-picked-skill')

  await ev('document.getElementById("composer-send").click()')
  check('发送后才进参数确认', await waitFor('!!document.getElementById("wb-product")', 15000))
  await shot('wb-home-params')

  /* ---------- 返回首页，用输入框提交 ---------- */
  await ev('(() => { const b = document.querySelector(\'[data-act="back"]\'); if (b) b.click(); return true })()')
  await waitFor('!!document.getElementById("composer-input")', 10000)
  await ev('(() => { const t = document.getElementById("composer-input"); t.value = "帮我分析蓝牙耳机的竞品"; t.dispatchEvent(new Event("input", {bubbles:true})); return true })()')
  await ev('document.getElementById("composer-send").click()')
  check('输入框提交能进参数确认', await waitFor('!!document.getElementById("wb-product")', 15000))
  /* 参数确认是独立的一屏「新建任务」：面包屑 + 四段表单 + 右侧执行信息栏。
     首页骨架（大标题、底部输入框）不再出现，路由仍然是 /workbench。 */
  const paramsPage = await ev(`(() => ({
    title: (document.querySelector('.wb-task-title') || {}).textContent || '',
    sections: document.querySelectorAll('.wb-sec').length,
    aside: document.querySelectorAll('.wb-aside-card').length,
    runBtn: !!document.getElementById('wb-run-task'),
    hero: !!document.querySelector('.wb-hero-title'),
    url: location.pathname,
  }))()`)
  check('参数确认是独立的新建任务页',
    paramsPage.title === '新建任务' && paramsPage.hero === false,
    `title=${paramsPage.title} hero=${paramsPage.hero}`)
  check('四个编号区块都在', paramsPage.sections === 4, paramsPage.sections)
  check('右侧有执行计划与技能信息', paramsPage.aside >= 3, paramsPage.aside)
  check('主按钮固定在右栏', paramsPage.runBtn === true)
  check('参数确认不换路由', paramsPage.url === '/workbench', paramsPage.url)

  /* ---------- 视觉纪律 ---------- */
  await ev('(() => { const b = document.querySelector(\'[data-act="back"]\'); if (b) b.click(); return true })()')
  await waitFor('!!document.querySelector(".wb-home")', 10000)
  await ev('document.querySelector(\'[data-seg="skill"]\').click()')
  await sleep(800)
  const card = await ev(`(() => {
    const c = document.querySelector('.skill-card'); if (!c) return null
    const s = getComputedStyle(c)
    return { radius: s.borderTopLeftRadius, shadow: s.boxShadow, border: s.borderTopWidth, bg: s.backgroundColor }
  })()`)
  check('技能卡圆角 12px', card && card.radius === '12px', card && card.radius)
  check('技能卡零阴影', card && (card.shadow === 'none' || card.shadow === ''), card && card.shadow)
  check('技能卡有边框', card && card.border === '1px')

  const seg = await ev(`(() => {
    const s = getComputedStyle(document.querySelector('.wb-seg-item.is-active'))
    return { radius: s.borderTopLeftRadius, shadow: s.boxShadow }
  })()`)
  check('分段控件不用胶囊形', seg && seg.radius !== '999px' && parseFloat(seg.radius) <= 8, seg && seg.radius)

  /* ---------- 文案红线 ---------- */
  const bodyText = await ev('document.body.innerText')
  const hits = BANNED.filter((w) => bodyText.includes(w))
  check('首页无开发标记/内部标识', hits.length === 0, hits.join(','))

  await shot('wb-home-final')

  console.log(errors.length ? `\nCONSOLE ERRORS:\n${errors.slice(0, 5).join('\n')}` : '\nno console errors')
  check('无 JS 异常', errors.length === 0)

  ws.close(); edge.kill(); await sleep(300)
  try { rmSync(profile, { recursive: true, force: true }) } catch {}
  console.log(failures ? `\n${failures} FAILED` : '\nALL WORKBENCH HOME CHECKS PASSED')
  console.log('shots:', OUT)
  process.exit(failures ? 1 : 0)
}
main().catch((e) => { console.error('FAIL:', e.message); edge.kill(); process.exit(1) })
