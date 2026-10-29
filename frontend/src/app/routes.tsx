/**
 * 路由表的唯一真源。路径、顺序、navKey 与旧 `js/app.js:50-75` 一一对应。
 *
 * 每个页面都是 `lazy(() => import(...))`：首屏只下载外壳与登录门，
 * 页面 chunk 在首次进入时才拉。这是本项目唯一能显著压低首屏 JS 的手段 ——
 * 改造前所有页面打在一个 447 KB 的 chunk 里，首页要等全部页面代码解析完。
 *
 * 命名导出的页面在这里映射成 default，保持路由表只关心「一个组件」。
 */
import { lazy } from 'react'
import { LegacyPage } from '@/app/legacy'
import type { LegacyPageLoader } from '@/types/global'
import type { RouteDef, RoutePageProps } from './router'

const DashboardPage = lazy(() =>
  import('@/features/dashboard/DashboardPage').then((m) => ({ default: m.DashboardPage })),
)
const TasksPage = lazy(() =>
  import('@/features/tasks/TasksPage').then((m) => ({ default: m.TasksPage })),
)
const DataPage = lazy(() => import('@/features/data-assets/DataPage').then((m) => ({ default: m.DataPage })))
const AgentsPage = lazy(() =>
  import('@/features/agents/AgentsPage').then((m) => ({ default: m.AgentsPage })),
)
const SkillsPage = lazy(() =>
  import('@/features/skills/SkillsPage').then((m) => ({ default: m.SkillsPage })),
)
const StoresPage = lazy(() =>
  import('@/features/stores/StoresPage').then((m) => ({ default: m.StoresPage })),
)
const SettingsPage = lazy(() =>
  import('@/features/settings/SettingsPage').then((m) => ({ default: m.SettingsPage })),
)

function legacy(loader: LegacyPageLoader) {
  return function LegacyRoute({ params, query }: RoutePageProps) {
    return <LegacyPage loader={loader} params={params} query={query} />
  }
}

/* workbench 是 1600 行字符串渲染，单独切一个 chunk。
   依赖在模块内部懒取（见该文件 header），所以动态 import 是安全的。 */
const workbenchLoader: LegacyPageLoader = (root, params, query) =>
  import('@/features/workbench/workbench').then((m) =>
    m.entry(root, params as Record<string, string>, query as Record<string, string>),
  )

/* 深链 /tasks/{id}：同一个组件，只是带上初始抽屉任务。
   点行开抽屉走的是 history.replaceState，不经路由，所以列表不会重挂。 */
function TasksRoute() {
  return <TasksPage />
}

function TaskDetailRoute({ params }: RoutePageProps) {
  return <TasksPage key={`task:${params.id}`} initialTaskId={params.id} />
}

/* 广场与详情同一个路由，靠 ?skill= / ?batch= 区分（保住已有深链） */
function SkillsRoute({ query }: RoutePageProps) {
  return <SkillsPage query={query} />
}

/* ?section= 由页面自己滚动定位，路由只负责把 query 传进去 */
function SettingsRoute({ query }: RoutePageProps) {
  return <SettingsPage section={query.section} />
}

/* 四个子页共用一个组件，view 由路由决定；筛选条件走查询串并同步回地址 */
function StoresRoute({ view, query }: RoutePageProps & { view: string }) {
  return <StoresPage key={view} view={view} query={query} />
}

export const ROUTES: RouteDef[] = [
  { path: '/dashboard', navKey: 'dashboard', Page: DashboardPage },
  { path: '/workbench', navKey: 'workbench', Page: legacy(workbenchLoader) },
  { path: '/tasks', navKey: 'tasks', Page: TasksRoute },
  // 深链 /tasks/xxx = 列表页 + 详情抽屉；点行开抽屉时旧代码走 history.replaceState，
  // 不经过路由，所以这里不会把列表整页重挂。
  { path: '/tasks/:id', navKey: 'tasks', Page: TaskDetailRoute },
  { path: '/data', navKey: 'data', Page: DataPage },
  { path: '/agents', navKey: 'agents', Page: AgentsPage },
  { path: '/skills', navKey: 'skills', Page: SkillsRoute },
  { path: '/stores', navKey: 'stores', Page: (p: RoutePageProps) => <StoresRoute {...p} view="dashboard" /> },
  { path: '/stores/authorize', navKey: 'stores', Page: (p: RoutePageProps) => <StoresRoute {...p} view="authorize" /> },
  { path: '/stores/product', navKey: 'stores', Page: (p: RoutePageProps) => <StoresRoute {...p} view="product" /> },
  { path: '/stores/ledger', navKey: 'stores', Page: (p: RoutePageProps) => <StoresRoute {...p} view="ledger" /> },
  { path: '/settings', navKey: 'settings', Page: SettingsRoute },
]

/**
 * 未开放的能力不进路由也不进导航：直接落到 404，
 * 界面上不解释「为什么还没做」，只给出现在能去哪。
 */
export const NOT_FOUND_NAV_KEY = 'dashboard'
