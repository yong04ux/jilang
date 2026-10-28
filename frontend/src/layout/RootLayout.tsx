/**
 * 应用外壳骨架。
 *
 * DOM 形状必须与旧 index.html 完全一致（`.app > aside.sidebar + .main >
 * header.topbar + .source-banner + main#view-root`）——layout.css:367-392 的
 * flex 链依赖这条结构，`.view-root > .mount-slot > .view` 少一层布局就塌。
 */
import type { ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { SourceBanner } from './SourceBanner'
import { useUiStore } from '@/stores/uiStore'

export function RootLayout({ activeKey, children }: { activeKey: string; children: ReactNode }) {
  const expanded = useUiStore((s) => s.expanded)
  const drawerOpen = useUiStore((s) => s.drawerOpen)
  const setDrawerOpen = useUiStore((s) => s.setDrawerOpen)

  return (
    <div className={expanded ? 'app is-expanded' : 'app'}>
      <aside className="sidebar" id="sidebar" aria-label="主导航">
        <Sidebar activeKey={activeKey} />
      </aside>

      <div className="main">
        <header className="topbar" id="topbar">
          <Topbar
            activeKey={activeKey}
            drawerOpen={drawerOpen}
            onOpenDrawer={() => setDrawerOpen(true)}
          />
        </header>
        <SourceBanner />
        <main className="view-root" id="view-root" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  )
}
