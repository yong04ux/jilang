/**
 * 顶栏：抽屉开关 + 面包屑 + 生成方式标识 + AI 助手入口。
 * 对应旧 shell.js:166-179（结构）与 206-242（标识文案）。
 */
import { Icon } from '@/components/Icon'
import { useHealthStore, providerFlagText } from '@/features/health/health'

export function Topbar({
  activeKey,
  drawerOpen,
  onOpenDrawer,
}: {
  activeKey: string
  drawerOpen: boolean
  onOpenDrawer: () => void
}) {
  const health = useHealthStore((s) => s.data)
  const failed = useHealthStore((s) => s.failed)

  const nav = window.CPCatalog?.NAV ?? []
  const labels: Record<string, string> = {}
  nav.forEach((g) => g.items.forEach((i) => (labels[i.key] = i.label)))
  const current = labels[activeKey] || activeKey

  const flag = providerFlagText(health, failed)
  const flagClass =
    'proto-flag' + (flag.tone === 'warn' ? ' is-warn' : flag.tone === 'ok' ? ' is-ok' : '')

  return (
    <>
      <div className="topbar-left">
        <button
          type="button"
          className="btn-icon"
          id="nav-open"
          aria-label="打开全部导航"
          aria-expanded={drawerOpen ? 'true' : 'false'}
          onClick={onOpenDrawer}
        >
          <Icon name="menu" />
        </button>
        <nav className="crumb" id="crumb" aria-label="面包屑">
          <a href="/dashboard" data-link="">
            工作空间
          </a>
          <span className="crumb-sep">/</span>
          <span className="crumb-current">{current}</span>
        </nav>
      </div>

      <div className="topbar-right">
        <span className={flagClass} id="provider-flag" title={flag.title}>
          <Icon name={flag.tone === 'warn' ? 'alert' : 'info'} />
          <span>{flag.text}</span>
        </span>
        <a className="pill-action" href="/workbench" data-link="">
          <Icon name="sparkles" />
          <span>AI 助手</span>
        </a>
      </div>
    </>
  )
}
