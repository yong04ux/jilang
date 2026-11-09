/**
 * 应用外壳骨架。
 *
 * DOM 形状必须与旧 index.html 一致（`.app > aside.sidebar + .main >
 * header.topbar + .source-banner + main#view-root`）——layout.css 的
 * flex 链依赖这条结构，`.view-root > .mount-slot > .view` 少一层布局就塌。
 *
 * 外壳样式全部在 layout.css（竖排书脊 + 跑马灯顶栏），这里只出结构。
 * 保留 `.app` `.sidebar` `.topbar` 这些类名是验收脚本的锚点。
 */
import type { ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { SourceBanner } from './SourceBanner'
import { ImageLightbox } from '@/components/shared/ImageLightbox'
import { useUiStore } from '@/stores/uiStore'

export function RootLayout({ activeKey, children }: { activeKey: string; children: ReactNode }) {
  const drawerOpen = useUiStore((s) => s.drawerOpen)
  const setDrawerOpen = useUiStore((s) => s.setDrawerOpen)

  return (
    <div className="app">
      <aside className="sidebar" id="sidebar" aria-label="主导航">
        <Sidebar activeKey={activeKey} onOpenDrawer={() => setDrawerOpen(true)} />
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
      <ImageLightbox />
    </div>
  )
}
