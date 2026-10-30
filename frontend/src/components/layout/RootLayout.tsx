/**
 * 应用外壳骨架。
 *
 * DOM 形状必须与旧 index.html 一致（`.app > aside.sidebar + .main >
 * header.topbar + .source-banner + main#view-root`）——layout.css 的
 * flex 链依赖这条结构，`.view-root > .mount-slot > .view` 少一层布局就塌。
 *
 * 外壳的**样式**（app 网格 / 侧栏 / 顶栏）已全部改为 Tailwind；
 * 保留 `.app` `.sidebar` `.topbar` 这些类名只是验收脚本钩子，不承载样式。
 * 窄屏强制退回图标栏由 useShellNarrow 在 JS 里决定，不靠 CSS 强覆盖。
 */
import type { ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { SourceBanner } from './SourceBanner'
import { useUiStore } from '@/stores/uiStore'
import { useShellNarrow } from '@/hooks/useMediaQuery'
import { cn } from '@/lib/utils'

export function RootLayout({ activeKey, children }: { activeKey: string; children: ReactNode }) {
  const storedExpanded = useUiStore((s) => s.expanded)
  const drawerOpen = useUiStore((s) => s.drawerOpen)
  const setDrawerOpen = useUiStore((s) => s.setDrawerOpen)
  const narrow = useShellNarrow()
  const expanded = storedExpanded && !narrow

  return (
    <div
      className={cn(
        'app grid min-h-screen',
        expanded
          ? 'grid-cols-[var(--sidebar-w-expanded)_minmax(0,1fr)]'
          : 'grid-cols-[var(--sidebar-w)_minmax(0,1fr)]',
      )}
    >
      <aside
        className={cn(
          'sidebar sticky top-0 z-120 flex h-screen flex-col overflow-visible border-r border-border bg-card',
          expanded ? 'items-stretch px-2 pt-3 pb-2' : 'items-center px-1.5 pt-2.5 pb-2',
        )}
        id="sidebar"
        aria-label="主导航"
      >
        <Sidebar activeKey={activeKey} />
      </aside>

      {/* .main 的样式仍在 layout.css（含 min-height:100vh），这里不加重复的工具类 */}
      <div className="main">
        {/* 顶栏样式在 Tailwind 里（原 layout.css 的 .topbar 段已删除） */}
        <header
          id="topbar"
          className="topbar sticky top-0 z-100 flex h-topbar items-center justify-between gap-3 border-b border-border bg-card px-5 wide:px-4 max-narrow:gap-2 max-narrow:px-3"
        >
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
