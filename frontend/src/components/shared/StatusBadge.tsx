/**
 * 任务状态徽章。文案与色调来自 `lib/ui` 的 STATUS（唯一真源），
 * 与旧 `CPUi.statusBadge()` 的映射完全一致，只是从字符串换成组件。
 *
 * 状态真的变了才盖章（stamp-slam）：首帧不播，避免进页面时一墙徽章同时砸下来。
 * 换 key 让 React 重挂这个 span，动画才能在挂载时触发。
 */
import { useEffect, useRef } from 'react'
import { STATUS } from '@/lib/ui'

export function StatusBadge({ status }: { status: string }) {
  const meta = STATUS[status] || STATUS.queued
  const prev = useRef(status)
  const changed = prev.current !== status
  useEffect(() => {
    prev.current = status
  }, [status])
  const cls = changed ? meta.cls + ' stamp-slam' : meta.cls
  return (
    <span key={changed ? status : 'idle'} className={cls}>
      {meta.label}
    </span>
  )
}