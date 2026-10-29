/**
 * shadcn/ui · Progress
 *
 * 纪律：**只在确有确定进度时使用**。任务执行是流式的，进度未知时不要
 * 编一个百分比 —— 那种场景用不确定态（indeterminate，见 value=null）。
 */
import * as React from 'react'
import * as ProgressPrimitive from '@radix-ui/react-progress'
import { cn } from '@/lib/utils'

function Progress({
  className,
  value,
  ...props
}: React.ComponentProps<typeof ProgressPrimitive.Root>) {
  const indeterminate = value === null || value === undefined
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      className={cn('relative h-1.5 w-full overflow-hidden rounded-full bg-muted', className)}
      value={indeterminate ? undefined : value}
      {...props}
    >
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className={cn(
          'h-full rounded-full bg-primary transition-transform duration-300',
          indeterminate && 'w-1/3 animate-indeterminate',
        )}
        style={indeterminate ? undefined : { transform: `translateX(-${100 - (value as number)}%)` }}
      />
    </ProgressPrimitive.Root>
  )
}

export { Progress }
