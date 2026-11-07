/**
 * 适配器：把「自己往容器里写 HTML」的页面模块挂进 React 树。
 *
 * 每次挂载做四件事：
 *   1. 给一个全新 `.mount-slot`（布局依赖 `.view-root > .mount-slot > .view` 这条链）；
 *   2. 调 `loader(host, params, query)`，页面自己往 host 里写 HTML；
 *   3. 异步失败时只在「还挂着」的情况下写错误块（已经切走就不覆盖新页面）；
 *   4. 挂载后 `CPIcon.hydrate` + `CPMotion.stagger` 进场 + 焦点复位 + 刷新顶栏标识。
 *
 * 关键约束：宿主 div 的子节点由页面模块用 innerHTML 管理，React 不渲染任何子节点，
 * 因此不会与 innerHTML 抢所有权。
 */
import { useEffect, useRef } from 'react'
import type { LegacyPageLoader } from '@/types/global'

function errorHtml(err: unknown): string {
  const message = (err as { message?: string } | null)?.message || String(err)
  const icon = window.CPUi ? window.CPUi.icon('alert') : ''
  const text = window.CPUi ? window.CPUi.esc(message) : message
  return (
    '<div class="view"><div class="page"><div class="page-inner">' +
    '<div class="callout callout-danger">' + icon +
    '<div><strong>页面加载失败</strong><br>' + text +
    '<div class="mt-2"><button type="button" class="btn btn-sm" ' +
    'onclick="location.reload()">刷新</button></div>' +
    '</div></div></div></div></div>'
  )
}

export function LegacyPage({
  loader,
  params,
  query,
}: {
  loader: LegacyPageLoader
  params: Record<string, string>
  query: Record<string, string>
}) {
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let alive = true

    const paintError = (err: unknown) => {
      if (!alive || !host.isConnected) return
      host.innerHTML = errorHtml(err)
      window.CPIcon?.hydrate(host)
    }

    let result: unknown
    try {
      result = loader(host, params, query)
    } catch (err) {
      paintError(err)
      return () => {
        alive = false
      }
    }

    const maybePromise = result as Promise<unknown> | undefined
    if (maybePromise && typeof maybePromise.catch === 'function') {
      maybePromise.catch(paintError)
    }

    window.CPIcon?.hydrate(document)

    // 页面进场：主区块按序淡入（reduced-motion 下 CPMotion 自己会跳过）
    const stage = (host.querySelector('.page-inner') ||
      host.querySelector('.view')) as HTMLElement | null
    if (stage && window.CPMotion) {
      window.CPMotion.stagger(stage, { selector: ':scope > *', step: 22, y: 5 })
    }

    document.getElementById('view-root')?.focus({ preventScroll: true })
    window.CPShell?.loadProvider?.()

    return () => {
      alive = false
    }
    // params/query 故意不进依赖：换参数靠路由 key 触发重挂，而不是在这里重跑
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loader])

  return <div className="mount-slot" ref={hostRef} />
}
