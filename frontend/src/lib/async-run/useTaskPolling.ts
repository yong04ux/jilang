/**
 * 轮询 hook：把 `createPoller` 的生命周期挂到组件上。
 *
 * 三条取消路径都要覆盖（旧实现靠 `state.poller` 手工 stop，容易漏）：
 *  1. 组件卸载（切页、关闭抽屉）；
 *  2. taskId 变化（换了任务）；
 *  3. enabled 变 false（比如用户折叠了结果面板）。
 *
 * handlers 放在 ref 里：调用方每次渲染传入新函数是常态，不能让它们重建轮询器，
 * 否则每秒都会重启一次请求。
 */
import { useEffect, useRef } from 'react'
import { createPoller, type Poller, type TaskDetail } from './poller'
import { fetchTaskDetail } from './tasks-api'

export interface UseTaskPollingOptions {
  taskId: string | null | undefined
  onUpdate?: (detail: TaskDetail) => void
  onDone?: (detail: TaskDetail) => void
  onError?: (err: unknown) => void
  onGiveUp?: (err: unknown) => void
  enabled?: boolean
  intervalMs?: number
}

export function useTaskPolling(options: UseTaskPollingOptions): void {
  const ref = useRef(options)
  ref.current = options

  const pollerRef = useRef<Poller | null>(null)
  const taskId = options.taskId
  const enabled = options.enabled !== false

  useEffect(() => {
    if (!taskId || !enabled) return
    const poller = createPoller({
      taskId,
      fetchTask: fetchTaskDetail,
      intervalMs: ref.current.intervalMs,
      onUpdate: (detail) => ref.current.onUpdate?.(detail),
      onDone: (detail) => ref.current.onDone?.(detail),
      onError: (err) => ref.current.onError?.(err),
      onGiveUp: (err) => ref.current.onGiveUp?.(err),
    })
    pollerRef.current = poller
    return () => {
      poller.stop()
      if (pollerRef.current === poller) pollerRef.current = null
    }
  }, [taskId, enabled])
}
