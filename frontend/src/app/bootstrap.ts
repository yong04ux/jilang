/**
 * 全局门面对接层。
 *
 * 两类消费端通过 `window.CP*` 使用同一份实现：
 *   1. 以 HTML 字符串渲染的页面模块，例如 `window.CPShell.getHealth()`、`window.CPAuth.user`；
 *   2. 验收脚本，例如 `window.CPAuth.load/logout/user`、`window.CPRouter.go`。
 * 这里只做「把 React 侧实现挂到同名门面上」，不承担任何业务逻辑。
 */
import { go, normalize, renderPath, installRouterListeners } from './router'
import { getHealth, invalidateHealth, useHealthStore } from '@/lib/health/health'
import { loadAuth, loadMe, logout, showGate, useAuthStore } from '@/stores/authStore'
import { useUiStore } from '@/stores/uiStore'
import { chartApi } from '@/lib/charts'
import { api } from '@/lib/api'
import { iconApi } from '@/lib/icons'
import { motionApi } from '@/lib/motion'
import { panelsApi } from '@/lib/panels'
import { labelApi } from '@/lib/labels'
import { uiApi } from '@/lib/ui'
import { catalogApi } from '@/lib/catalog'
import { schemaFormApi } from '@/lib/schema-form/schema-form.ts'
import { renderApi } from '@/lib/render/render.ts'
import { presentApi } from '@/lib/async-run/present'
import { createPoller, isRunning, RUNNING } from '@/lib/async-run/poller'
import { cancelTask, fetchTaskDetail } from '@/lib/async-run/tasks-api'

function navLabels(): Record<string, string> {
  const labels: Record<string, string> = {}
  const nav = window.CPCatalog?.NAV ?? []
  nav.forEach((group) => group.items.forEach((item) => (labels[item.key] = item.label)))
  return labels
}

export function installLegacyGlobals(): void {
  /* ── 旧全局门面 ────────────────────────────────────────────────
     workbench 等页面仍按 `window.CPxxx` 取依赖，而这些经典脚本已全部搬进 TS。
     这里把门面指向 TS 实现：**一处实现、两种消费端**，不再有两套并存。
     它们必须在首次渲染前装好（LegacyPage 的子 effect 早于 App 的 effect）。 */
  window.CPChart = chartApi
  window.CPMotion = motionApi as unknown as Window['CPMotion']
  window.CPPanels = panelsApi as unknown as Window['CPPanels']
  window.CPApi = api as unknown as Window['CPApi']
  window.CPUi = uiApi as unknown as Window['CPUi']
  window.CPIcon = iconApi
  window.CPLabel = labelApi as unknown as Window['CPLabel']
  window.CPCatalog = catalogApi as unknown as Window['CPCatalog']
  window.CPSchemaForm = schemaFormApi as unknown as Window['CPSchemaForm']
  window.CPRender = renderApi as unknown as Window['CPRender']
  window.CPAsyncRun = {
    ...presentApi,
    RUNNING,
    isRunning,
    // 旧签名 poller({taskId,onUpdate,onDone,onError}) → 注入取数函数
    poller: (opts: Record<string, any>) =>
      createPoller({ ...(opts as { taskId: string }), fetchTask: fetchTaskDetail }),
    cancel: cancelTask,
  } as unknown as Window['CPAsyncRun']

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
