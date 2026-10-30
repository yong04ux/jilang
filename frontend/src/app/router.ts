/**
 * 极简 History 路由 —— 逐条移植自旧 `js/router.js`，额外接上 React 订阅。
 *
 * 三条必须保留的旧语义：
 *  1. 「同路径 + 同查询串」时只重绘、不动历史（router.js:80-89 的注释解释了原因：
 *     早先只比 pathname 会让 `/skills → /skills?skill=x` 既不更新地址栏也不进历史）；
 *  2. `force` 跳过上面的捷径，强制 push 一条历史；
 *  3. 只拦截带 `data-link` 的站内链接，且跳过外链、`#`、修饰键与中键。
 *
 * 另外提供「不通知路由的静默改地址」语义 —— 页面模块（tasks 抽屉、stores 筛选）
 * 直接调 `history.replaceState`，地址变了但页面不重绘。React 侧只要不监听
 * history 变动就天然等价，所以这里不额外处理。
 */
import type { ComponentType } from 'react'
import { flushSync } from 'react-dom'

export interface RoutePageProps {
  params: Record<string, string>
  query: Record<string, string>
  path: string
}

export interface RouteDef {
  path: string
  navKey: string
  Page: ComponentType<RoutePageProps>
}

interface Compiled {
  re: RegExp
  keys: string[]
}

export interface RouterSnapshot {
  /** 通知时刻的 location.pathname + location.search */
  path: string
  /** 每次通知自增；作为页面 key 的一部分，保证「原路径重绘」也能真正重挂 */
  nonce: number
}

export interface MatchResult {
  route: RouteDef | null
  params: Record<string, string>
  path: string
}

/* ------------------------------------------------------------------ 路径处理 */

/** 去掉 ?query 与 #hash，去掉尾部斜杠（router.js:31-36） */
export function normalize(path: string): string {
  if (!path) return '/'
  const clean = path.split('?')[0].split('#')[0]
  if (clean.length > 1 && clean.endsWith('/')) return clean.slice(0, -1)
  return clean || '/'
}

/** 手写查询串解析：`?a=b&c=d`（router.js:58-64） */
export function parseQuery(path: string): Record<string, string> {
  const query: Record<string, string> = {}
  const raw = (path.split('?')[1] || '').split('#')[0]
  raw.split('&').forEach((pair) => {
    if (!pair) return
    const kv = pair.split('=')
    query[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || '')
  })
  return query
}

/**
 * 把 `/tasks/:id` 编译成正则（router.js:12-29）。
 * 注意顺序：先把 :param 换成哨兵，再转义特殊字符，最后把哨兵换成捕获组 ——
 * 直接在已转义串上替换会因为 `/` 变成 `\/` 而匹配不到。
 */
function compile(path: string): Compiled {
  const keys: string[] = []
  const SENTINEL = '\u0000'
  let pattern = path
    .replace(/\/+$/, '')
    .replace(/:([A-Za-z0-9_]+)/g, (_m, key: string) => {
      keys.push(key)
      return SENTINEL
    })
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    .replace(/\\\//g, '/')
    .split(SENTINEL)
    .join('([^/]+)')
  if (!pattern) pattern = '/'
  return { re: new RegExp('^' + pattern + '$'), keys }
}

const compiledCache = new Map<string, Compiled>()

export function matchRoutes(routes: RouteDef[], path: string): MatchResult {
  const clean = normalize(path)
  for (const route of routes) {
    let compiled = compiledCache.get(route.path)
    if (!compiled) {
      compiled = compile(route.path)
      compiledCache.set(route.path, compiled)
    }
    const m = compiled.re.exec(clean)
    if (!m) continue
    const params: Record<string, string> = {}
    compiled.keys.forEach((key, idx) => {
      params[key] = decodeURIComponent(m[idx + 1])
    })
    return { route, params, path: clean }
  }
  return { route: null, params: {}, path: clean }
}

/* ------------------------------------------------------------------ 订阅模型 */

/**
 * 初始路径：根路径统一落到 /dashboard（登录前后 URL 一致）。
 * 放在模块求值时做，而不是放进 React 的 effect —— 这样首帧就是正确路由，
 * 也避免在 effect 里触发同步刷新。
 */
function initialPath(): string {
  if (location.pathname === '/' || location.pathname === '/index.html') {
    history.replaceState({}, '', '/dashboard')
  }
  return location.pathname + location.search
}

let snapshot: RouterSnapshot = { path: initialPath(), nonce: 0 }
const listeners = new Set<() => void>()

/**
 * 提交路由变更。
 *
 * **必须同步生效**：旧 `CPRouter.go()` 是「pushState 后立刻调用 handler 写 DOM」，
 * 调用方（页面模块代码、仓库里的验收脚本）都依赖「go() 返回时 DOM 已经是新页面」。
 * 例如 ui_skills_shot 会在 go() 之后马上 `querySelector('#sk-form')` 并点运行按钮，
 * 若这里只是通知订阅者、等 React 异步提交，拿到的会是上一页的表单，点错按钮。
 */
function notify(nextPath?: string): void {
  const apply = () => {
    snapshot = {
      path: nextPath ?? location.pathname + location.search,
      nonce: snapshot.nonce + 1,
    }
    listeners.forEach((fn) => fn())
  }
  flushSync(apply)
}

export function subscribeRouter(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getRouterSnapshot(): RouterSnapshot {
  return snapshot
}

/* ------------------------------------------------------------------ 导航动作 */

export interface GoOptions {
  replace?: boolean
  force?: boolean
}

export function go(path: string, opts?: GoOptions): void {
  const targetQuery = (path.split('?')[1] || '').split('#')[0]
  const currentQuery = location.search.replace(/^\?/, '')
  const shortcut =
    normalize(path) === normalize(location.pathname) &&
    targetQuery === currentQuery &&
    !(opts && opts.force)

  if (shortcut) {
    notify(path)
    return
  }

  if (opts && opts.replace) history.replaceState({}, '', path)
  else history.pushState({}, '', path)
  notify(path)
  window.scrollTo({ top: 0, behavior: 'auto' })
}

/** 对应旧 `CPRouter.render(path)`：不碰 history，只按给定路径重绘 */
export function renderPath(path: string): void {
  notify(path)
}

/** 旧 `CPRouter` 的 `current` 字段形态（极少被用，保留以免调用点报错） */
export function currentPath(): string {
  return snapshot.path
}

/* ------------------------------------------------------- 全局监听（只装一次） */

let installed = false

export function installRouterListeners(): void {
  if (installed) return
  installed = true

  window.addEventListener('popstate', () => {
    notify(location.pathname + location.search)
  })

  document.addEventListener('click', (event) => {
    const target = event.target as Element | null
    const anchor = target?.closest?.('a[data-link]') as HTMLAnchorElement | null
    if (!anchor) return
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
    const href = anchor.getAttribute('href')
    if (!href || href.startsWith('http') || href.startsWith('#')) return
    event.preventDefault()
    go(href)
  })
}
