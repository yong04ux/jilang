/**
 * shadcn/ui · Sonner（Toast 渲染器）
 *
 * 为什么不直接替换 `lib/ui.ts` 的 `toast()`：
 * 那个函数被 7 个页面、约 30 处调用，且探针断言了 `.toast` 的 DOM。
 * 这一轮只提供**新组件可用的** toast 入口，旧调用点保持不动；
 * 等页面逐个改造时再统一收敛。
 */
import { Toaster as SonnerToaster } from 'sonner'

type ToasterProps = React.ComponentProps<typeof SonnerToaster>

function Toaster(props: ToasterProps) {
  return (
    <SonnerToaster
      position="top-center"
      offset={{ top: 56, bottom: 16 }}
      duration={3200}
      toastOptions={{
        classNames: {
          toast:
            'group flex items-start gap-2 rounded-md border border-border bg-popover p-3 text-sm text-popover-foreground shadow-md',
          description: 'text-xs text-muted-foreground',
          actionButton: 'rounded-sm bg-primary px-2 py-1 text-xs text-primary-foreground',
          cancelButton: 'rounded-sm bg-secondary px-2 py-1 text-xs text-secondary-foreground',
          success: '[&_[data-icon]]:text-success',
          error: '[&_[data-icon]]:text-destructive',
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
