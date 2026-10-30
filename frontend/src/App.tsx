/**
 * 应用根：启动编排 + 路由出口 + 外壳 + 登录门。
 *
 * 启动顺序照搬旧 `js/app.js:97-149`：
 *   1. 根路径统一落到 /dashboard（登录前后 URL 一致）；
 *   2. 顶栏生成方式标识先取一次（未登录也有意义）；
 *   3. 注册全局 401 处理（先读 wasSignedIn 再亮登录门）；
 *   4. /api/auth/status → 已登录才 loadMe 并渲染页面；
 *   5. cp:authenticated / cp:logout 常驻监听（换账号必须能刷新）。
 */
import { Suspense, useEffect } from 'react'
import { RootLayout } from '@/components/layout/RootLayout'
import { NavDrawer } from '@/components/layout/NavDrawer'
import { AuthGate } from '@/components/layout/AuthGate'
import { NotFoundPage } from '@/app/NotFoundPage'
import { PageFallback } from '@/components/shared/PageFallback'
import { ROUTES, NOT_FOUND_NAV_KEY } from './app/routes'
import { matchRoutes, parseQuery, renderPath } from './app/router'
import { useRouteSnapshot } from './app/useRoute'
import { api } from '@/lib/api'
import { loadAuth, loadMe, logout, showGate, useAuthStore } from '@/stores/authStore'
import { useHealthStore } from '@/lib/health/health'
import { useUiStore } from '@/stores/uiStore'

export default function App() {
  const user = useAuthStore((s) => s.user)
  const gateOpen = useAuthStore((s) => s.gateOpen)
  const snapshot = useRouteSnapshot()
  const drawerOpen = useUiStore((s) => s.drawerOpen)
  const setDrawerOpen = useUiStore((s) => s.setDrawerOpen)

  const match = matchRoutes(ROUTES, snapshot.path)
  const activeKey = match.route ? match.route.navKey : NOT_FOUND_NAV_KEY
  // 未登录 / 登录门亮着时不渲染业务页面：现有实现直接把 #view-root 清空
  const pageReady = Boolean(user) && !gateOpen
  const Page = match.route?.Page
  const routeKey = `${snapshot.path}#${snapshot.nonce}`
  const query = parseQuery(snapshot.path)

  useEffect(() => {
    // 1. 根路径 → /dashboard 的重定向在 app/router.ts 模块求值时已完成，
    //    首帧拿到的就是规范化后的路由，这里不再重复处理。

    // 2. 顶栏标识（与登录态无关，先取一次）
    void useHealthStore.getState().refresh(false)

    // 3. 401：已登录过才提示「会话过期」，否则静默交给登录门
    const onUnauthorized = () => {
      const wasSignedIn = Boolean(useAuthStore.getState().user)
      showGate(wasSignedIn ? '登录已过期，请重新登录' : null)
    }
    api.onUnauthorized(onUnauthorized)
    // 页面模块走的是 js/api.js 那套客户端，它的 401 也必须能亮登录门，
    // 否则会话过期时会停在「页面加载失败」而不是登录页。
    window.CPApi?.onUnauthorized(onUnauthorized)

    // 4. 读会话
    void loadAuth().then((current) => {
      if (!current) return
      void loadMe()
      void useHealthStore.getState().refresh(false)
    })

    // 5. 常驻监听
    const onAuthenticated = () => {
      void loadMe()
      void useHealthStore.getState().refresh(true)
      // 已启动过（换账号再登）：按当前地址重绘，让页面用新账号重新取数
      renderPath(location.pathname + location.search)
    }
    const onLogout = () => {
      // 退出只是亮出登录门，画面还在门后面；不清地址的话下次登录会看到上一个账号的页面
      history.replaceState({}, '', '/dashboard')
      renderPath('/dashboard')
    }
    const onDocumentClick = (event: MouseEvent) => {
      const target = event.target as Element | null
      if (target?.closest?.('#user-logout')) void logout()
    }

    window.addEventListener('cp:authenticated', onAuthenticated)
    window.addEventListener('cp:logout', onLogout)
    document.addEventListener('click', onDocumentClick)
    return () => {
      window.removeEventListener('cp:authenticated', onAuthenticated)
      window.removeEventListener('cp:logout', onLogout)
      document.removeEventListener('click', onDocumentClick)
    }
  }, [])

  return (
    <>
      <RootLayout activeKey={activeKey}>
        {pageReady ? (
          /* 页面都是 lazy 的：chunk 未到时先给同形状骨架，避免布局塌陷 */
          <Suspense fallback={<PageFallback />}>
            {Page ? (
              <Page key={routeKey} params={match.params} query={query} path={match.path} />
            ) : (
              <NotFoundPage key={routeKey} />
            )}
          </Suspense>
        ) : null}
      </RootLayout>

      <NavDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <AuthGate />
    </>
  )
}
