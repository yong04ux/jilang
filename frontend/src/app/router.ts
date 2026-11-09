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
import { animate, reduced, tokenMs } from '@/lib/motion'

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

const PAGE_SEL = ':scope > .view, :scope > .mount-slot > .view'

/* 幽灵层放在 closed shadow root 里：document.querySelector 穿不过去，
   验收脚本在 go() 之后同步查询时不会把旧页元素多数一遍，也不会撞重复 id。
   宿主与样式表只建一次，后续换页只换内容，避免首次克隆时闪一下无样式。 */
let ghostHost: HTMLDivElement | null = null
let ghostShadow: ShadowRoot | null = null

function ghostShell(): ShadowRoot | null {
  if (ghostShadow && ghostHost?.isConnected) return ghostShadow
  if (typeof document === 'undefined' || typeof Element === 'undefined') return null
  if (typeof Element.prototype.attachShadow !== 'function') return null
  const host = document.createElement('div')
  host.className = 'cp-page-ghost'
  host.setAttribute('aria-hidden', 'true')
  const shadow = host.attachShadow({ mode: 'closed' })
  document.querySelectorAll('link[rel="stylesheet"], style').forEach((node) => {
    shadow.appendChild(node.cloneNode(true))
  })
  const slot = document.createElement('div')
  slot.className = 'cp-page-ghost-slot'
  shadow.appendChild(slot)
  document.body.appendChild(host)
  ghostHost = host
  ghostShadow = shadow
  return shadow
}

function takeGhostSlot(): HTMLElement | null {
  const shadow = ghostShell()
  const slot = shadow?.lastElementChild as HTMLElement | null
  if (!slot) return null
  slot.textContent = ''
  return slot
}

function hideGhost(): void {
  if (!ghostHost) return
  ghostHost.style.display = 'none'
  ghostHost.style.opacity = ''
  ghostHost.style.transform = ''
  const slot = ghostShadow?.lastElementChild as HTMLElement | null
  if (slot) slot.textContent = ''
}

/** 新页进场由 JS 负责时，关掉 `.view` 自带的 CSS 进场，避免双重动画 */
function markFed(root: HTMLElement | null): void {
  root?.querySelector<HTMLElement>(PAGE_SEL)?.classList.add('view--fed')
}

/**
 * 走纸式切页：先把旧页克隆成一张贴在同一位置的「纸」，再同步换页，
 * 最后旧纸向左抽走、新页从右推入。
 *
 * 为什么不用 View Transitions：`document.startViewTransition()` 的更新回调是
 * 异步调用的，go() 会在 DOM 换页之前就返回，而验收脚本依赖「go() 返回即新页面」
 * 的同步语义。克隆方案能在一次同步调用里完成换页并拿到旧页快照。
 *
 * 超大 DOM 不克隆（>2500 节点）只做新页进场，避免克隆开销拖慢切页。
 */
function pageFeed(apply: () => void, slide: boolean): void {
  const root = document.getElementById('view-root')
  const gate = document.getElementById('auth-gate')
  const hasPage = Boolean(root?.querySelector(PAGE_SEL))
  if (!root || !hasPage || reduced() || (gate && !gate.hidden)) {
    // 没有旧页可克隆时保留 CSS 兜底进场，不做标记
    apply()
    return
  }

  const rect = root.getBoundingClientRect()
  const ghostRoot = root.cloneNode(true) as HTMLElement
  const cheap = ghostRoot.querySelectorAll('*').length <= 2500
  let box: HTMLDivElement | null = null

  if (cheap && rect.width > 0) {
    const slot = takeGhostSlot()
    if (slot && ghostHost) {
      ghostRoot.removeAttribute('id')
      ghostRoot.classList.add('view--fed')
      ghostRoot.style.position = 'absolute'
      ghostRoot.style.left = '0'
      ghostRoot.style.top = '0'
      ghostRoot.style.width = rect.width + 'px'
      slot.appendChild(ghostRoot)
      box = ghostHost
      box.style.display = 'block'
      box.style.opacity = ''
      box.style.transform = ''
      box.style.left = rect.left + 'px'
      box.style.top = rect.top + 'px'
      box.style.width = rect.width + 'px'
      box.style.height = rect.height + 'px'
    }
  }

  document.documentElement.dataset.cpFeed = '1'
  try {
    apply()
  } catch (err) {
    hideGhost()
    delete document.documentElement.dataset.cpFeed
    throw err
  }
  markFed(root)

  const next = root.querySelector<HTMLElement>(PAGE_SEL)
  const duration = tokenMs('--dur-3', 280)
  const jobs: Promise<unknown>[] = []
  if (box) {
    jobs.push(
      animate(
        box,
        slide
          ? [
              { opacity: 1, transform: 'none', offset: 0 },
              // 先带着整张纸滑出去，后段才淡掉——一上来就淡会像交叉溶解，不像抽纸
              { opacity: 1, transform: 'translate3d(-15px,0,0)', offset: 0.45 },
              { opacity: 0, transform: 'translate3d(-28px,0,0)', offset: 1 },
            ]
          : [{ opacity: 1 }, { opacity: 0 }],
        { duration, easing: 'cubic-bezier(.4,0,.2,1)', fill: 'forwards' },
      ),
    )
  }
  if (next) {
    jobs.push(
      animate(
        next,
        slide
          ? [{ opacity: 0, transform: 'translate3d(30px,0,0)' }, { opacity: 1, transform: 'none' }]
          : [{ opacity: 0 }, { opacity: 1 }],
        { duration: duration + 40 },
      ),
    )
  }
  const done = () => {
    hideGhost()
    // 等遗留页的挂载 effect 跑完再摘标记（它的 stagger 靠这个标记跳过）
    window.setTimeout(() => {
      delete document.documentElement.dataset.cpFeed
    }, 240)
  }
  if (jobs.length) void Promise.all(jobs).then(done, done)
  else done()
}

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
  // 同路径重绘是「刷新」，不做横向抽纸；换页才走纸
  const slide = normalize(nextPath ?? location.pathname + location.search) !== normalize(snapshot.path)
  pageFeed(() => flushSync(apply), slide)
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
  // 启动时先把幽灵层的样式表挂好（display:none），首次切页才不会闪一下无样式
  ghostShell()

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
