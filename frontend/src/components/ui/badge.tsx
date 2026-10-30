/**
 * shadcn/ui · Badge
 *
 * 语义色只用于「状态」，不用于装饰：default 是蓝色实心（主状态），其余是描边。
 */
import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] font-medium leading-4 whitespace-nowrap [&_svg]:size-3',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        outline: 'border-border text-muted-foreground',
        success: 'border-success-line bg-success-soft text-success',
        warning: 'border-warning-line bg-warning-soft text-warning',
        danger: 'border-destructive-line bg-destructive-soft text-destructive',
        info: 'border-info-line bg-info-soft text-info',
      },
    },
    defaultVariants: { variant: 'secondary' },
  },
)

function Badge({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<'span'> & VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : 'span'
  return (
    <Comp data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
