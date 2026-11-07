/**
 * 竖排书脊：84px 墨底导航，中文竖排，图标全部退场。
 *
 * 品牌块兼任「全部导航」抽屉的入口 —— 书脊只有一种宽度，没有折叠态，
 * 抽屉才是唯一的「看全清单」出口。
 * 保留的锚点：#sidebar-brand、.nav-item[data-nav]（验收脚本用）。
 */
import { useUiStore } from '@/stores/uiStore'
import { AccountMenu } from './AccountMenu'

export function Sidebar({
  activeKey,
  onOpenDrawer,
}: {
  activeKey: string
  onOpenDrawer: () => void
}) {
  const drawerOpen = useUiStore((s) => s.drawerOpen)
  const nav = window.CPCatalog?.NAV ?? []
  const rail = window.CPCatalog?.RAIL_LABEL ?? {}

  return (
    <>
      <button
        type="button"
        className="spine-brand"
        id="sidebar-brand"
        aria-haspopup="dialog"
        aria-expanded={drawerOpen ? 'true' : 'false'}
        aria-label="打开全部导航"
        title="全部导航"
        onClick={onOpenDrawer}
      >
        <img src="/media/logo-mark.svg?v=3" alt="" width={34} height={34} />
      </button>

      <nav className="sidebar-nav" aria-label="主导航">
        {nav.map((group) => (
          <div className="sidebar-group" key={group.group}>
            {group.items.map((item) => {
              const active = item.key === activeKey
              return (
                <a
                  className="nav-item"
                  href={item.path}
                  data-link=""
                  data-nav={item.key}
                  title={`${group.group} · ${item.label}`}
                  aria-current={active ? 'page' : undefined}
                  key={item.key}
                >
                  <span className="nav-item-label">{rail[item.key] || item.label}</span>
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
