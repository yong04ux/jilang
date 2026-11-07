/**
 * 任务状态徽章。文案与色调来自 `lib/ui` 的 STATUS（唯一真源），
 * 与旧 `CPUi.statusBadge()` 的映射完全一致，只是从字符串换成组件。
 */
import { STATUS } from '@/lib/ui'

export function StatusBadge({ status }: { status: string }) {
  const meta = STATUS[status] || STATUS.queued
  return <span className={meta.cls}>{meta.label}</span>
}
