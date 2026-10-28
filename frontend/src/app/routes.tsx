/**
 * 路由表的唯一真源。路径、顺序、navKey 与旧 `js/app.js:50-75` 一一对应。
 *
 * S2 阶段所有页面都还是旧模块，用 LegacyPage 适配器挂入；
 * 每迁完一页就把对应的 `legacy(...)` 换成真组件，路径不变。
 */
import { LegacyPage } from '@/legacy/LegacyPage'
import { AgentsPage } from '@/pages/agents/AgentsPage'
import { DashboardPage } from '@/pages/dashboard/DashboardPage'
import { TasksPage } from '@/pages/tasks/TasksPage'
import type { LegacyPageLoader } from '@/types/global'
import type { RouteDef, RoutePageProps } from './router'

function legacy(loader: LegacyPageLoader) {
  return function LegacyRoute({ params, query }: RoutePageProps) {
    return <LegacyPage loader={loader} params={params} query={query} />
  }
}

/* 旧页面模块在经典脚本里定义，晚于本模块求值也没关系：
   这里只是包一层取值函数，真正读取发生在挂载时。 */
const workbenchLoader: LegacyPageLoader = (root, params, query) =>
  window.CPPageWorkbench?.entry(root, params, query)

/* 深链 /tasks/{id}：同一个组件，只是带上初始抽屉任务。
   点行开抽屉走的是 history.replaceState，不经路由，所以列表不会重挂。 */
function TasksRoute() {
  return <TasksPage />
}

function TaskDetailRoute({ params }: RoutePageProps) {
  return <TasksPage key={`task:${params.id}`} initialTaskId={params.id} />
}

const dataLoader: LegacyPageLoader = (root, params, query) =>
  window.CPPageData?.render(root, params, query)

const skillsLoader: LegacyPageLoader = (root, params, query) =>
  window.CPPageSkills?.render(root, params, query)

const settingsLoader: LegacyPageLoader = (root, params, query) =>
  window.CPPageSettings?.render(root, params, query)

const storesLoader = (view: string): LegacyPageLoader => (root, _params, query) =>
  window.CPPageStores?.render(root, view, query ?? {})

export const ROUTES: RouteDef[] = [
  { path: '/dashboard', navKey: 'dashboard', Page: DashboardPage },
  { path: '/workbench', navKey: 'workbench', Page: legacy(workbenchLoader) },
  { path: '/tasks', navKey: 'tasks', Page: TasksRoute },
  // 深链 /tasks/xxx = 列表页 + 详情抽屉；点行开抽屉时旧代码走 history.replaceState，
  // 不经过路由，所以这里不会把列表整页重挂。
  { path: '/tasks/:id', navKey: 'tasks', Page: TaskDetailRoute },
  { path: '/data', navKey: 'data', Page: legacy(dataLoader) },
  { path: '/agents', navKey: 'agents', Page: AgentsPage },
  { path: '/skills', navKey: 'skills', Page: legacy(skillsLoader) },
  { path: '/stores', navKey: 'stores', Page: legacy(storesLoader('dashboard')) },
  { path: '/stores/authorize', navKey: 'stores', Page: legacy(storesLoader('authorize')) },
  { path: '/stores/product', navKey: 'stores', Page: legacy(storesLoader('product')) },
  { path: '/stores/ledger', navKey: 'stores', Page: legacy(storesLoader('ledger')) },
  { path: '/settings', navKey: 'settings', Page: legacy(settingsLoader) },
]

/**
 * 未开放的能力不进路由也不进导航：直接落到 404，
 * 界面上不解释「为什么还没做」，只给出现在能去哪。
 */
export const NOT_FOUND_NAV_KEY = 'dashboard'
