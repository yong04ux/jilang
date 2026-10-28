/**
 * 迁移期的全局门面对接层。
 *
 * React 接管外壳后，旧代码仍在两个方向依赖 `window.CP*`：
 *   1. 旧页面模块：`window.CPShell.getHealth()` / `window.CPAuth.user`（settings.js:58,289,478）；
 *   2. 仓库里的 Edge 探针：`window.CPAuth.load/logout/user`、`window.CPRouter.go`。
 * 这两类都不能因为迁移而消失，所以这里把同名门面指向 React 侧的实现，
 * 保证「一处实现、两种消费端」。S8 旧目录删除后再统一清理。
 */
import { go, normalize, renderPath, installRouterListeners } from './router'
import { getHealth, invalidateHealth, useHealthStore } from '@/features/health/health'
import { loadAuth, loadMe, logout, showGate, useAuthStore } from '@/stores/authStore'
import { useUiStore } from '@/stores/uiStore'

function navLabels(): Record<string, string> {
  const labels: Record<string, string> = {}
  const nav = window.CPCatalog?.NAV ?? []
  nav.forEach((group) => group.items.forEach((item) => (labels[item.key] = item.label)))
  return labels
}

export function installLegacyGlobals(): void {
  window.CPAuth = {
    load: (silent?: boolean) => loadAuth(Boolean(silent)),
    logout,
    show: (text?: string | null) => showGate(text ?? null),
    get user() {
      return useAuthStore.getState().user
    },
  }

  window.CPRouter = {
    // 路由表已移到 React（app/routes.tsx），旧代码不再自行定义路由
    define: () => undefined,
    start: () => undefined,
    go,
    render: (path?: string) => renderPath(path ?? location.pathname + location.search),
    resolve: (path: string) => ({ path: normalize(path) }),
    normalize,
    setOnChange: () => undefined,
    get current() {
      return { path: normalize(location.pathname) }
    },
  }

  window.CPShell = {
    getHealth,
    invalidateHealth,
    loadProvider: () => {
      void useHealthStore.getState().refresh(false)
    },
    loadUser: () => {
      void loadMe()
    },
    // 面包屑与选中态改由路由表的 navKey 推导，这里保留空实现以免旧调用点报错
    setNavKey: () => undefined,
    setExpanded: (value: boolean) => useUiStore.getState().setExpanded(value),
    openDrawer: () => useUiStore.getState().setDrawerOpen(true),
    closeDrawer: () => useUiStore.getState().setDrawerOpen(false),
    mountBanner: () => undefined,
    LABELS: navLabels(),
  }
}

let installed = false

/** 必须在首次渲染之前调用（LegacyPage 的子 effect 早于 App 的 effect 执行） */
export function bootstrap(): void {
  if (installed) return
  installed = true
  installLegacyGlobals()
  installRouterListeners()
}
