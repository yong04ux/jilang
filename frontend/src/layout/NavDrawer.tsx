/**
 * 全量导航抽屉（窄屏用）。对应旧 shell.js:292-347。
 * 打开时：显示遮罩、焦点落到第一个链接、Esc 关闭、点链接后自动关闭。
 */
import { useEffect, useRef } from 'react'
import { Icon } from '@/components/Icon'

export function NavDrawer({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const drawerRef = useRef<HTMLDivElement>(null)
  const nav = window.CPCatalog?.NAV ?? []

  useEffect(() => {
    if (!open) return
    const first = drawerRef.current?.querySelector('a') as HTMLElement | null
    first?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      {open && <div className="drawer-scrim" onClick={onClose} />}
      <div
        id="nav-drawer"
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="全部导航"
        hidden={!open}
        ref={drawerRef}
      >
        <div className="drawer-head" style={{ alignItems: 'center' }}>
          <a className="sidebar-brand" href="/dashboard" data-link="">
            <img src="/media/logo-mark.svg?v=2" alt="" width={26} height={26} />
            <span className="sidebar-brand-text">激浪</span>
          </a>
          <button type="button" className="btn-icon" id="nav-close" aria-label="关闭导航" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>
        <div className="drawer-body" style={{ padding: 'var(--sp-3)' }}>
          {nav.map((group) => (
            <div className="sidebar-group" key={group.group}>
              <div className="sidebar-group-title">{group.group}</div>
              {group.items.map((item) => (
                <a
                  className="nav-item"
                  href={item.path}
                  data-link=""
                  data-nav={item.key}
                  data-drawer-link=""
                  key={item.key}
                  onClick={onClose}
                >
                  <Icon name={item.icon} />
                  <span className="nav-item-label">{item.label}</span>
                </a>
              ))}
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
