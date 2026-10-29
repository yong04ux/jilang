/**
 * 路由级懒加载的占位骨架。
 *
 * 必须是 `.mount-slot > .view` 的形状：layout.css 靠这条两级 flex 链撑满高度，
 * 少一层会在 chunk 尚未到达的那一瞬间让页面塌成内容高度（肉眼可见的跳动）。
 *
 * 只用 Tailwind 类，不掺旧类名 —— 这一层是纯装饰，不与既有 CSS 抢同一个属性。
 */
import { Skeleton } from '@/components/ui/skeleton'

export function PageFallback() {
  return (
    <div className="mount-slot">
      <div className="view">
        <div className="mx-auto w-full max-w-[1120px] px-6 py-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex flex-col gap-2">
              <Skeleton className="h-6 w-32" />
              <Skeleton className="h-3.5 w-64" />
            </div>
            <Skeleton className="h-8 w-24" />
          </div>

          <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="rounded-lg border border-border bg-card p-4">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="mt-3 h-6 w-16" />
              </div>
            ))}
          </div>

          <div className="mt-4 rounded-lg border border-border bg-card p-4">
            <Skeleton className="h-3 w-24" />
            <div className="mt-4 flex flex-col gap-2">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
