/**
 * 列表重排的 FLIP 补间。
 *
 * deps 变化后（筛选/排序/搜索），在 layout 阶段量出新旧位置：
 * 留下的项先反向位移再播放回原位，首次出现的项淡入。用 offsetLeft/offsetTop 而不是
 * getBoundingClientRect，因为后者会把上一次动画的 transform 算进去，连续筛选会漂移。
 *
 * 被移除的项由 React 直接卸载，这里不做退场——要退场得给每一项留挂载壳，
 * 代价远大于收益。
 */
import { useLayoutEffect, useRef, type RefObject } from 'react'
import { animate, fadeIn, reduced, tokenMs } from '@/lib/motion'

export interface FlipListOptions {
  /** 稳定 key 的属性名，默认 data-flip-key；退而求其次读 data-task-row */
  keyAttr?: string
  /** 位移补间时长（毫秒），默认读 --dur-3 */
  duration?: number
}

export function useFlipList(
  ref: RefObject<HTMLElement | null>,
  deps: unknown[],
  options: FlipListOptions = {},
): void {
  const prev = useRef<Map<string, { x: number; y: number }> | null>(null)
  const keyAttr = options.keyAttr ?? 'data-flip-key'

  useLayoutEffect(() => {
    const host = ref.current
    if (!host) return
    const items = Array.from(host.children) as HTMLElement[]
    const keyOf = (node: HTMLElement, index: number) =>
      node.getAttribute(keyAttr) ?? node.getAttribute('data-task-row') ?? String(index)

    const next = new Map<string, { x: number; y: number }>()
    items.forEach((node, index) => {
      next.set(keyOf(node, index), { x: node.offsetLeft, y: node.offsetTop })
    })

    const before = prev.current
    prev.current = next
    if (!before || reduced()) return

    const duration = options.duration ?? tokenMs('--dur-3', 280)
    items.forEach((node, index) => {
      const key = keyOf(node, index)
      const from = before.get(key)
      const to = next.get(key)
      if (!to) return
      if (!from) {
        void fadeIn(node, { y: 6, duration: tokenMs('--dur-2', 180) })
        return
      }
      const dx = from.x - to.x
      const dy = from.y - to.y
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return
      // 上一轮没播完又换了筛选：先清掉旧动画，避免 transform 叠加
      node.getAnimations().forEach((animation) => animation.cancel())
      void animate(
        node,
        [{ transform: 'translate(' + dx + 'px,' + dy + 'px)' }, { transform: 'none' }],
        { duration },
      )
    })
    // deps 是调用方给的「列表签名」，故意不展开
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}