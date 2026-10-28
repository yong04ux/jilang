/**
 * 侧栏（图标栏 / 展开为文字栏）。
 * 结构与 class 逐条对齐旧 shell.js:83-164 —— layout.css 的展开态、
 * 图标尺寸、选中色都挂在这些类名上。
 */
import { useUiStore } from '@/stores/uiStore'
import { Icon } from '@/components/Icon'
import { AccountMenu } from './AccountMenu'

export function Sidebar({ activeKey }: { activeKey: string }) {
  const expanded = useUiStore((s) => s.expanded)
  const setExpanded = useUiStore((s) => s.setExpanded)

  const nav = window.CPCatalog?.NAV ?? []
  const rail = window.CPCatalog?.RAIL_LABEL ?? {}
  const brandLabel = expanded ? '收起导航' : '展开导航'

  const toggle = () => {
    setExpanded(!expanded)
    const brand = document.getElementById('sidebar-brand')
    if (brand && window.CPMotion) window.CPMotion.tap(brand)
  }

  return (
    <>
      <div className="sidebar-head">
        <button
          type="button"
          className="sidebar-brand"
          id="sidebar-brand"
          aria-expanded={expanded ? 'true' : 'false'}
          aria-label={brandLabel}
          title={brandLabel}
          onClick={toggle}
        >
          <img src="/media/logo-mark.svg?v=2" alt="" width={36} height={36} />
          <span className="sidebar-brand-text">激浪</span>
        </button>
      </div>

      <nav className="sidebar-nav" aria-label="主导航">
        {nav.map((group) => (
          <div className="sidebar-group" key={group.group}>
            <div className="sidebar-group-title">{group.group}</div>
            {group.items.map((item) => {
              const active = item.key === activeKey
              return (
                <a
                  className={active ? 'nav-item is-active' : 'nav-item'}
                  href={item.path}
                  data-link=""
                  data-nav={item.key}
                  title={item.label}
                  aria-current={active ? 'page' : undefined}
                  key={item.key}
                >
                  <Icon name={item.icon} />
                  <span className="nav-item-label">
                    <span className="nav-label-short">{rail[item.key] || item.label}</span>
                    <span className="nav-label-full">{item.label}</span>
                  </span>
                </a>
              )
            })}
          </div>
        ))}
      </nav>

      <div className="sidebar-foot">
        <AccountMenu />
      </div>
    </>
  )
}
