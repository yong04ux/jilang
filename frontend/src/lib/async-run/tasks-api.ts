/**
 * 轮询器的生产环境绑定：把 `/api/tasks/*` 接进来。
 *
 * 单独一层是为了让 `poller.ts` 保持零依赖、可在 Node 里直接测试。
 */
import { api } from '@/lib/api'
import type { TaskDetail } from './poller'

export function fetchTaskDetail(taskId: string): Promise<TaskDetail> {
  return api.get<TaskDetail>(`/api/tasks/${encodeURIComponent(taskId)}`)
}

/** 取消任务，返回后端给出的可读说明 */
export async function cancelTask(taskId: string): Promise<string> {
  const resp = await api.post<{ detail?: string }>(
    `/api/tasks/${encodeURIComponent(taskId)}/cancel`,
    {},
  )
  return resp?.detail || '已请求取消'
}
