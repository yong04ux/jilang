/** shadcn/ui · Input —— 高度取 --h-md（32px），与现有表单一致 */
import * as React from 'react'
import { cn } from '@/lib/utils'

function Input({ className, type, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        'flex h-8 w-full min-w-0 rounded-md border border-input bg-card px-2.5 py-1 text-sm text-foreground',
        'placeholder:text-muted-foreground/70',
        'outline-none transition-[color,box-shadow] focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-ring/25',
        'disabled:cursor-not-allowed disabled:opacity-60',
        'aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20',
        'file:mr-2 file:border-0 file:bg-transparent file:text-xs file:font-medium',
        className,
      )}
      {...props}
    />
  )
}

export { Input }
