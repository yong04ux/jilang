/**
 * 图标组件：直接用 `src/lib/icons.ts` 的 SVG 字符串，不再经 `window.CPIcon`。
 *
 * 为什么包一层 `display: contents`：图标选择器（`.nav-item .icon`、
 * `.account-menu-item .icon`、`.proto-flag .icon` …）都是后代选择器，
 * 多一个不参与布局的宿主元素不影响命中，也不会破坏 flex 尺寸。
 */
import { svg } from '@/lib/icons'

export function Icon({ name, extraClass }: { name: string; extraClass?: string }) {
  const html = svg(name, null, extraClass)
  if (!html) return null
  return <span style={{ display: 'contents' }} dangerouslySetInnerHTML={{ __html: html }} />
}
