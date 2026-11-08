/**
 * 滚动揭示：把 CPMotion 里闲置的 inView 接上。
 *
 * 初始隐藏交给 CSS（`html.cp-reveal-on [data-reveal]:not([data-revealed])`），
 * 不用 JS 设 opacity——设置页的区块是数据回来后才挂载的**新节点**，
 * JS 在挂载时藏一遍只会藏在马上被替换掉的旧节点上，新节点照样先露出来。
 *
 * 观察器挂在 #view-root 上，晚出现的区块也能接住；揭示后打 data-revealed。
 * 另挂滚动扫尾（瞬移到底部时中间区块从未相交）与 1.2s 兜底。
 * reduced-motion 直接跳过，连开关都不加，元素保持可见。
 */
import { useLayoutEffect } from 'react'
import { fadeIn, inView, reduced } from '@/lib/motion'

export function usePageReveal(routeKey: string, readyKey: string | null): void {
  useLayoutEffect(() => {
    if (reduced()) return
    const root = document.getElementById('view-root')
    if (!root) return
    document.documentElement.classList.add('cp-reveal-on')

    const pending = new Set<HTMLElement>()
    const stops: Array<() => void> = []

    const show = (node: HTMLElement) => {
      if (!pending.delete(node)) return
      node.setAttribute('data-revealed', '')
      void fadeIn(node, { y: 10 })
    }

    const attach = (node: HTMLElement) => {
      if (node.hasAttribute('data-revealed') || pending.has(node)) return
      pending.add(node)
      stops.push(
        inView(node, (el) => show(el as HTMLElement), { rootMargin: '0px 0px -6% 0px', threshold: 0.04 }),
      )
    }

    const scan = (scope: ParentNode) => {
      scope.querySelectorAll<HTMLElement>('[data-reveal]').forEach(attach)
    }

    scan(root)
    const mo = new MutationObserver((records) => {
      records.forEach((record) => {
        record.addedNodes.forEach((node) => {
          if (node.nodeType !== 1) return
          const el = node as HTMLElement
          if (el.matches('[data-reveal]')) attach(el)
          scan(el)
        })
      })
    })
    mo.observe(root, { childList: true, subtree: true })

    const sweep = () => {
      pending.forEach((node) => {
        if (node.getBoundingClientRect().top < window.innerHeight * 0.92) show(node)
      })
    }

    let frame = 0
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(sweep)
    }
    const safety = window.setTimeout(sweep, 1200)
    window.addEventListener('scroll', onScroll, { passive: true })

    return () => {
      window.clearTimeout(safety)
      window.removeEventListener('scroll', onScroll)
      cancelAnimationFrame(frame)
      mo.disconnect()
      stops.forEach((stop) => stop())
      // 已挂载但没来得及揭示的，撤掉观察时立即显形，避免永久隐藏
      pending.forEach((node) => node.setAttribute('data-revealed', ''))
      pending.clear()
    }
  }, [routeKey, readyKey])
}