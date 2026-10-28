/**
 * 迁移期与旧模块互操作的类型声明。
 *
 * 为什么需要：S2 起外壳由 React 接管，但页面模块（js/pages/*.js）还是旧代码，
 * 两边要靠 window 上的全局对象互通。这些声明只描述「会用到的部分」，
 * 全部保持宽松类型 —— 目的是让 TS 编译通过，不是给旧代码补类型。
 */

export interface LegacyNavItem {
  key: string
  label: string
  icon: string
  path: string
}

export interface LegacyNavGroup {
  group: string
  items: LegacyNavItem[]
}

/** 旧页面模块的统一签名：(root, params, query) => void | Promise<unknown> */
export type LegacyPageLoader = (
  root: HTMLElement,
  params?: Record<string, string>,
  query?: Record<string, string>,
) => unknown

declare global {
  interface Window {
    CPUi?: {
      esc(value: unknown): string
      el(html: string): Element | null
      toast(message: string, tone?: 'ok' | 'danger'): void
      copy(text: string, label?: string): Promise<void>
      icon(name: string, cls?: string): string
      statusBadge(status: string): string
      statusLabel(status: string): string
      fmtTime(value: unknown): string
      [key: string]: unknown
    }
    CPIcon?: {
      svg(name: string, size?: number | null, extraClass?: string): string
      hydrate(root?: ParentNode | Element | null): void
      has(name: string): boolean
      names: string[]
    }
    CPCatalog?: {
      NAV: LegacyNavGroup[]
      RAIL_LABEL: Record<string, string>
      AGENTS: Array<{ key: string; name: string; desc: string; tags: string[] }>
      [key: string]: unknown
    }
    CPMotion?: {
      fadeIn(el: Element, opts?: Record<string, unknown>): Promise<unknown>
      fadeOut(el: Element, opts?: Record<string, unknown>): Promise<unknown>
      stagger(el: Element, opts?: Record<string, unknown>): Promise<unknown>[]
      tap(el: Element): void
      animate(el: Element, frames: unknown, opts?: Record<string, unknown>): Promise<unknown>
      [key: string]: unknown
    }
    CPPageDashboard?: { render: LegacyPageLoader }
    CPPageWorkbench?: { entry: LegacyPageLoader }
    CPPageTasks?: { render: LegacyPageLoader; detail: LegacyPageLoader }
    CPPageData?: { render: LegacyPageLoader }
    CPPageSettings?: { render: LegacyPageLoader }
    CPPageStores?: { render: (root: HTMLElement, view: string, query: Record<string, string>) => unknown }
    CPPageSkills?: { render: LegacyPageLoader }
    CPPages?: {
      agents: LegacyPageLoader
      notFound: (root: HTMLElement, path?: string) => unknown
    }
    /** 旧传输层（js/api.js）：迁移期页面还在用它，401 处理必须与 TS 实现共用同一个回调 */
    CPApi?: {
      get(path: string): Promise<unknown>
      post(path: string, body?: unknown): Promise<unknown>
      put(path: string, body?: unknown): Promise<unknown>
      del(path: string, body?: unknown): Promise<unknown>
      postForm(path: string, form: FormData): Promise<unknown>
      onUnauthorized(fn: (() => void) | null): void
    }
    /** 图表：仍是旧实现（S3 决定等首个消费页面再迁），React 页面通过 ref 挂宿主元素 */
    CPChart?: {
      line(host: Element, spec: Record<string, unknown>): void
      bars(host: Element, spec: Record<string, unknown>): void
      money(value: unknown): string
      moneyFull(value: unknown, currency?: string): string
      num(value: unknown): string
      pct(value: unknown): string
    }
    /** 迁移期门面（见 app/bootstrap.ts）：旧页面与仓库探针都离不开它们 */
    CPAuth?: {
      load(silent?: boolean): Promise<unknown>
      logout(): Promise<void>
      show(text?: string | null): void
      readonly user: unknown
    }
    CPRouter?: {
      define(...args: unknown[]): void
      start(...args: unknown[]): void
      go(path: string, opts?: { replace?: boolean; force?: boolean }): void
      render(path?: string): void
      resolve(path: string): unknown
      normalize(path: string): string
      setOnChange(fn: unknown): void
      readonly current: unknown
    }
    CPShell?: {
      getHealth(force?: boolean): Promise<unknown>
      invalidateHealth(): void
      loadProvider(): void
      loadUser(): void
      setNavKey(key: string): void
      setExpanded(value: boolean): void
      openDrawer(): void
      closeDrawer(): void
      mountBanner(): void
      LABELS: Record<string, string>
    }
  }
}

export {}
