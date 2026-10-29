#!/usr/bin/env node
/**
 * 轮询状态机行为测试（无框架，直接跑 TS）。
 *
 * 为什么单独测这个：它决定「任务跑起来了但界面一直不动」这类事故。
 * 旧实现在单次网络失败后不再排下一次 setTimeout，探针覆盖不到（探针环境不抖动网络），
 * 所以这里用注入的 fetchTask 精确复现。
 *
 * 用法：node scripts/poller-check.mjs
 */
import { pathToFileURL } from 'node:url'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = dirname(here)
const { createPoller, POLL_MS, RUNNING, MAX_CONSECUTIVE_FAILURES } = await import(
  pathToFileURL(resolve(root, 'src/lib/async-run/poller.ts')).href
)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let failed = 0

function check(ok, label, detail = '') {
  if (ok) console.log(`  PASS  ${label}${detail ? '  ' + detail : ''}`)
  else {
    console.log(`  FAIL  ${label}${detail ? '  ' + detail : ''}`)
    failed += 1
  }
}

console.log('\n轮询状态机行为测试\n' + '─'.repeat(56))

check(POLL_MS === 1000, '轮询间隔 = 1000ms', String(POLL_MS))
check(
  Object.keys(RUNNING).sort().join(',') === 'cancelling,queued,running',
  '「运行中」只有 queued/running/cancelling',
  Object.keys(RUNNING).join(','),
)
check(MAX_CONSECUTIVE_FAILURES === 5, '连续失败上限 = 5', String(MAX_CONSECUTIVE_FAILURES))

/* 1. 终态：onUpdate 每次都调，onDone 只调一次，且之后不再请求 */
{
  const statuses = ['running', 'running', 'succeeded']
  let calls = 0
  let updates = 0
  let dones = 0
  const p = createPoller({
    taskId: 't1',
    intervalMs: 10,
    fetchTask: async () => {
      const status = statuses[Math.min(calls, statuses.length - 1)]
      calls += 1
      return { task: { status } }
    },
    onUpdate: () => {
      updates += 1
    },
    onDone: () => {
      dones += 1
    },
  })
  check(calls === 1, '首次 tick 立刻执行（不等第一个间隔）', `已请求 ${calls} 次`)
  await sleep(120)
  check(calls === 3, '按间隔继续轮询直到终态', `请求 ${calls} 次`)
  check(updates === 3, 'onUpdate 每次结果都回调', `update ${updates} 次`)
  check(dones === 1, 'onDone 只触发一次', `done ${dones} 次`)
  p.stop()
}

/* 2. 回归测试：单次失败后必须继续轮询 */
{
  const plan = ['reject', 'running', 'succeeded']
  let calls = 0
  let updates = 0
  let dones = 0
  let errors = 0
  let gaveUp = 0
  createPoller({
    taskId: 't2',
    intervalMs: 10,
    fetchTask: async () => {
      const step = plan[Math.min(calls, plan.length - 1)]
      calls += 1
      if (step === 'reject') throw new Error('network down')
      return { task: { status: step } }
    },
    onUpdate: () => {
      updates += 1
    },
    onDone: () => {
      dones += 1
    },
    onError: () => {
      errors += 1
    },
    onGiveUp: () => {
      gaveUp += 1
    },
  })
  await sleep(120)
  check(calls >= 3, '单次网络失败后仍然继续轮询', `请求 ${calls} 次`)
  check(errors === 1, '失败会回调 onError', `error ${errors} 次`)
  check(dones === 1, '恢复后仍能拿到终态', `done ${dones} 次`)
  check(gaveUp === 0, '未达上限不放弃', `giveUp ${gaveUp} 次`)
}

/* 3. 连续失败达上限 → 放弃并停止 */
{
  let calls = 0
  let errors = 0
  let gaveUp = 0
  const p = createPoller({
    taskId: 't3',
    intervalMs: 10,
    fetchTask: async () => {
      calls += 1
      throw new Error('still down')
    },
    onError: () => {
      errors += 1
    },
    onGiveUp: () => {
      gaveUp += 1
    },
  })
  await sleep(300)
  check(calls === MAX_CONSECUTIVE_FAILURES, `连续失败 ${MAX_CONSECUTIVE_FAILURES} 次后放弃`, `请求 ${calls} 次`)
  check(errors === MAX_CONSECUTIVE_FAILURES, '每次失败都回调 onError', `error ${errors} 次`)
  check(gaveUp === 1, 'onGiveUp 只触发一次', `giveUp ${gaveUp} 次`)
  check(p.stopped === true, '放弃后轮询器处于已停止状态')
  const before = calls
  await sleep(80)
  check(calls === before, '放弃后不再发请求', `又发了 ${calls - before} 次`)
}

/* 4. stop() 立即生效 */
{
  let calls = 0
  const p = createPoller({
    taskId: 't4',
    intervalMs: 10,
    fetchTask: async () => {
      calls += 1
      return { task: { status: 'running' } }
    },
  })
  await sleep(35)
  p.stop()
  const snapshot = calls
  await sleep(60)
  check(calls === snapshot, 'stop() 后不再发请求', `又发了 ${calls - snapshot} 次`)
}

/* 5. waiting_for_* / partial 等非 RUNNING 状态一律停止轮询（与旧实现一致） */
{
  for (const status of ['awaiting_approval', 'waiting_for_input', 'waiting_for_review', 'partial']) {
    let calls = 0
    let dones = 0
    createPoller({
      taskId: 't5',
      intervalMs: 10,
      fetchTask: async () => {
        calls += 1
        return { task: { status } }
      },
      onDone: () => {
        dones += 1
      },
    })
    await sleep(60)
    check(calls === 1 && dones === 1, `${status} 视为终态（只请求一次并回调 onDone）`, `请求 ${calls} 次`)
  }
}

console.log('─'.repeat(56))
if (failed) {
  console.error(`\n轮询行为不符合预期：${failed} 项失败\n`)
  process.exit(1)
}
console.log('\n轮询行为全部符合预期\n')
