/** shadcn/ui · Skeleton —— 加载态用，禁用动画时退化为静态灰块 */
import { cn } from '@/lib/utils'

function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="skeleton"
      className={cn('animate-pulse rounded-sm bg-muted', className)}
      {...props}
    />
  )
}

export { Skeleton }
