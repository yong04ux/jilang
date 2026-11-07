/**
 * shadcn/ui 的类名合成工具。
 *
 * `twMerge` 负责在冲突时保留后写的类（`p-2 p-4` → `p-4`），
 * 这是 shadcn 所有基元能安全接受 `className` 覆盖的前提。
 *
 * 注意本项目 Tailwind 用 `important` 模式输出（见 src/styles/tailwind.css），
 * twMerge 对 `!` 后缀/前缀的处理同样生效，不需要额外配置。
 */
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
