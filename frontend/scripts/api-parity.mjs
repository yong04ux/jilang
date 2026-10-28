#!/usr/bin/env node
/**
 * 传输层语义对照：旧 `frontend/js/api.js` vs 新 `frontend/src/lib/api.ts`。
 *
 * 做法：用同一组伪造响应分别打两个实现，逐条比对
 *   message / status / detail / payload / 是否触发全局 401 处理。
 *
 * 这一步的意义：页面大量依赖 `err.status === 428/422/409` 与 detail 结构，
 * 只要这条管道有一处偏差，错误提示就会静默变样，而探针未必覆盖得到。
 *
 * 用法：node scripts/api-parity.mjs
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = dirname(here)

// 旧实现：读源码放进一个假 window 里执行
const legacyWin = {}
new Function('window', readFileSync(resolve(root, 'js/api.js'), 'utf8'))(legacyWin)
const legacy = legacyWin.CPApi
if (!legacy) {
  console.error('无法加载旧实现 js/api.js')
  process.exit(1)
}

const modern = await import(pathToFileURL(resolve(root, 'src/lib/api.ts')).href)

/** 伪造响应 */
function fakeResponse(status, body) {
  const text = body === undefined ? '' : typeof body === 'string' ? body : JSON.stringify(body)
  return {
    status,
    ok: status >= 200 && status < 300,
    text: async () => text,
  }
}

function makeFetch(handler) {
  return async (url, init) => {
    globalThis.__lastInit = init
    return handler(url, init)
  }
}

/** 把一次调用的结果收敛成可比较的形状 */
async function probe(fn, path, fetchImpl) {
  const record = { unauthorized: 0 }
  const originalFetch = globalThis.fetch
  globalThis.fetch = fetchImpl
  try {
    const value = await fn(path)
    return { kind: 'ok', value, unauthorized: record.unauthorized }
  } catch (err) {
    return {
      kind: 'err',
      message: err && err.message,
      status: err && err.status,
      detail: err && err.detail,
      unauthorized: record.unauthorized,
    }
  } finally {
    globalThis.fetch = originalFetch
  }
}

/** 同一个用例分别跑两个实现（各自注册 401 计数） */
async function compare(name, path, response) {
  const fetchImpl = makeFetch(() => response())

  legacy.onUnauthorized(() => {
    legacyCounter.n += 1
  })
  modern.api.onUnauthorized(() => {
    modernCounter.n += 1
  })
  legacyCounter.n = 0
  modernCounter.n = 0

  const a = await probe((p) => legacy.get(p), path, fetchImpl)
  const aCount = legacyCounter.n
  const b = await probe((p) => modern.api.get(p), path, fetchImpl)
  const bCount = modernCounter.n

  const same =
    a.kind === b.kind &&
    JSON.stringify(a.value ?? null) === JSON.stringify(b.value ?? null) &&
    a.message === b.message &&
    a.status === b.status &&
    JSON.stringify(a.detail ?? null) === JSON.stringify(b.detail ?? null) &&
    aCount === bCount

  if (same) {
    console.log(`  PASS  ${name}`)
    return true
  }
  console.log(`  FAIL  ${name}`)
  console.log('        旧：' + JSON.stringify({ ...a, unauthorized: aCount }))
  console.log('        新：' + JSON.stringify({ ...b, unauthorized: bCount }))
  return false
}

const legacyCounter = { n: 0 }
const modernCounter = { n: 0 }

console.log('\n传输层语义对照（旧 js/api.js ↔ 新 src/lib/api.ts）\n' + '─'.repeat(56))

const results = []
const add = (v) => results.push(v)

add(await compare('200 正常返回对象', '/api/x', () => fakeResponse(200, { items: [1, 2] })))
add(await compare('200 空响应体', '/api/x', () => fakeResponse(200)))
add(await compare('400 detail 是字符串', '/api/x', () => fakeResponse(400, { detail: '参数不对' })))
add(
  await compare('422 字段级错误（field 前缀）', '/api/x', () =>
    fakeResponse(422, {
      detail: {
        message: '提交的内容有几处需要修正',
        errors: [
          { field: '商品名', message: '不能为空' },
          { row: 3, message: '价格不规范' },
          { row: 9, message: '第三行' },
          { row: 10, message: '第四行应被截断' },
        ],
      },
    }),
  ),
)
add(
  await compare('428 缺 Key 追加可读提示', '/api/x', () =>
    fakeResponse(428, { detail: { message: '需要配置模型密钥', code: 'api_key_required' } }),
  ),
)
add(
  await compare('428 无 code 时不加提示', '/api/x', () =>
    fakeResponse(428, { detail: { message: '需要配置模型密钥' } }),
  ),
)
add(
  await compare('401 业务接口 → 全局登出 + 登录已过期', '/api/tasks/tsk_1', () =>
    fakeResponse(401, { detail: '未登录' }),
  ),
)
add(
  await compare('401 登录入口 → 不触发全局登出', '/api/auth/login', () =>
    fakeResponse(401, { detail: '用户名或密码不正确' }),
  ),
)
add(
  await compare('401 注册入口 → 不触发全局登出', '/api/auth/register', () =>
    fakeResponse(401, { detail: '账号已存在' }),
  ),
)
add(await compare('500 detail 是数组', '/api/x', () => fakeResponse(500, [{ msg: '甲' }, { msg: '乙' }])))
add(await compare('500 空响应体', '/api/x', () => fakeResponse(500)))
add(
  await compare('409 detail 是对象但无 message', '/api/x', () =>
    fakeResponse(409, { detail: { conflict: true } }),
  ),
)
add(
  await compare('网络层异常 → status 0', '/api/x', () => {
    throw new TypeError('fetch failed')
  }),
)

console.log('─'.repeat(56))
const failed = results.filter((v) => !v).length
if (failed) {
  console.error(`\n语义不一致：${failed}/${results.length} 项\n`)
  process.exit(1)
}
console.log(`\n两个实现语义一致：${results.length}/${results.length} 项\n`)
