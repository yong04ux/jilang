/**
 * shadcn/ui · Button（new-york，React 19 写法：无 forwardRef，用 data-slot）
 *
 * 高度对齐项目的控件尺度（tokens.css：--h-sm 28 / --h-md 32 / --h-lg 36），
 * 而不是 shadcn 默认的 h-9/h-10 —— 迁就现有页面密度。
 */
import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium outline-none transition-[color,background-color,box-shadow,transform] duration-150 ease-out disabled:pointer-events-none disabled:opacity-50 disabled:shadow-none disabled:transform-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg]:size-4",
  {
    variants: {
      variant: {
        default:
          'bg-primary text-primary-foreground shadow-[3px_3px_0_var(--ink)] hover:bg-primary-hover hover:-translate-x-px hover:-translate-y-px hover:shadow-[4px_4px_0_var(--ink)] active:translate-x-[2px] active:translate-y-[2px] active:shadow-none',
        secondary:
          'bg-secondary text-secondary-foreground shadow-[3px_3px_0_var(--ink)] hover:bg-accent hover:-translate-x-px hover:-translate-y-px hover:shadow-[4px_4px_0_var(--ink)] active:translate-x-[2px] active:translate-y-[2px] active:shadow-none',
        outline:
          'border border-border bg-card text-foreground shadow-[3px_3px_0_var(--ink)] hover:bg-accent hover:-translate-x-px hover:-translate-y-px hover:shadow-[4px_4px_0_var(--ink)] active:translate-x-[2px] active:translate-y-[2px] active:shadow-none',
        ghost: 'text-foreground hover:bg-accent active:translate-y-px',
        link: 'text-primary underline-offset-4 hover:underline',
        destructive:
          'bg-destructive text-primary-foreground shadow-[3px_3px_0_var(--ink)] hover:opacity-90 hover:-translate-x-px hover:-translate-y-px hover:shadow-[4px_4px_0_var(--ink)] active:translate-x-[2px] active:translate-y-[2px] active:shadow-none',
      },
      size: {
        default: 'h-8 px-3',
        sm: 'h-7 px-2.5 text-xs',
        lg: 'h-9 px-4',
        icon: 'size-8',
        'icon-sm': 'size-7',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  busy = false,
  disabled,
  children,
  ...props
}: React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean; busy?: boolean }) {
  const Comp = asChild ? Slot : 'button'
  // asChild 时 Slot 只接受单个子元素：spinner 不能成为兄弟节点，否则整棵树抛错
  const content =
    busy && !asChild ? (
      <>
        <span className="cp-spin" aria-hidden="true" />
        {children}
      </>
    ) : (
      children
    )
  return (
    <Comp
      data-slot="button"
      data-variant={variant ?? 'default'}
      data-busy={busy ? 'true' : undefined}
      aria-busy={busy || undefined}
      disabled={disabled || busy}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    >
      {content}
    </Comp>
  )
}

export { Button, buttonVariants }
