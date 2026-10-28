/**
 * 图标：把旧 `CPIcon.svg()` 产出的字符串塞进 DOM。
 *
 * 为什么包一层 `display: contents`：所有图标选择器（`.nav-item .icon`、
 * `.account-menu-item .icon`、`.proto-flag .icon` …）都是后代选择器，
 * 多一个不参与布局的宿主元素不影响命中，也不会破坏 flex 尺寸。
 * 图标数据仍在 `js/icons.js`（S3A 才搬到 TS），这里不复制一份。
 */
export function Icon({ name, extraClass }: { name: string; extraClass?: string }) {
  const html = window.CPIcon ? window.CPIcon.svg(name, null, extraClass) : ''
  if (!html) return null
  return (
    <span
      style={{ display: 'contents' }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
