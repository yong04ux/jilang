/**
 * 任务轮询器 —— 移植自旧 `js/async-run.js:123-159`，并修掉一个缺陷。
 *
 * 保留的语义（页面全靠它们）：
 *  - 间隔 1s、首次立刻执行一次（不等第一个 1s）；
 *  - `RUNNING` 只有 queued / running / cancelling 三个值，其余状态一律视为终态；
 *  - `onDone` 只触发一次；
 *  - `stop()` 后不再发请求。
 *
 * 修掉的缺陷：旧实现 tick 的 catch 分支 `return` 之后**不再排下一次 setTimeout**，
 * 于是任何一次网络抖动都会让轮询永久停住，界面停在最后一次状态（注释却写着
 * 「忽略单次失败，下次轮询继续」）。现在改为连续失败计数，达到上限才放弃并回调
 * `onGiveUp`，让界面能明确说「状态获取失败」而不是静静卡住。
 *
 * 本模块**不 import 任何东西**（连 api 都不引）：取数函数由调用方注入。
 * 这样它能在 Node 里直接跑测试，也避免核心状态机被网络层绑死。
 * 绑定 /api 的那一层见 `tasks-api.ts`。
 */

export const POLL_MS = 1000

/** 视为「还在跑」的状态；其余（含 awaiting_approval / partial 等）都停止轮询 */
export const RUNNING: Record<string, 1> = {
  queued: 1,
  running: 1,
  cancelling: 1,
}

/** 与旧 `CPAsyncRun.isRunning()` 同义 */
export function isRunning(status: string | null | undefined): boolean {
  return Boolean(status && RUNNING[status])
}

/** 连续失败多少次后放弃（用户已确认的行为变更） */
export const MAX_CONSECUTIVE_FAILURES = 5

export interface TaskDetail {
  task?: { status?: string; [key: string]: unknown }
  steps?: unknown[]
  result?: unknown
  pending?: unknown
  [key: string]: unknown
}

export interface PollerOptions {
  taskId: string
  /** 取任务详情。由调用方注入（生产环境见 tasks-api.ts） */
  fetchTask: (taskId: string) => Promise<TaskDetail>
  onUpdate?: (detail: TaskDetail) => void
  /** 终态回调，只触发一次 */
  onDone?: (detail: TaskDetail) => void
  /** 单次失败（仍会继续重试） */
  onError?: (err: unknown) => void
  /** 连续失败达到上限，轮询已放弃 */
  onGiveUp?: (err: unknown) => void
  /** 仅供测试与特殊场景覆盖 */
  intervalMs?: number
  maxFailures?: number
}

export interface Poller {
  stop(): void
  readonly stopped: boolean
  readonly failures: number
}

export function createPoller(opts: PollerOptions): Poller {
  const interval = opts.intervalMs ?? POLL_MS
  const maxFailures = opts.maxFailures ?? MAX_CONSECUTIVE_FAILURES
  const fetchTask = opts.fetchTask

  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false
  let done = false
  let failures = 0

  const stop = () => {
    stopped = true
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  const schedule = () => {
    if (stopped) return
    timer = setTimeout(tick, interval)
  }

  async function tick(): Promise<void> {
    if (stopped) return
    let detail: TaskDetail
    try {
      detail = await fetchTask(opts.taskId)
      failures = 0
    } catch (err) {
      failures += 1
      opts.onError?.(err)
      if (failures >= maxFailures) {
        stop()
        opts.onGiveUp?.(err)
        return
      }
      // 关键修复：单次失败要继续轮询，而不是就此停住
      schedule()
      return
    }
    if (stopped) return
    opts.onUpdate?.(detail)
    const status = detail.task?.status || ''
    if (!RUNNING[status]) {
      if (!done) {
        done = true
        opts.onDone?.(detail)
      }
      return
    }
    schedule()
  }

  // 首次立刻执行，不等第一个间隔
  void tick()

  return {
    stop,
    get stopped() {
      return stopped
    },
    get failures() {
      return failures
    },
  }
}
