/**
 * 指标计数：数字从上一值滚到新值，终值永远是后端给的真值。
 *
 * 直接改 textContent 而不走 React state —— 每帧一次 setState 会把整页重渲染几十次。
 * 非数字（区间、占位符）原样输出，不猜。
 */
import { useEffect, useRef } from 'react'
import { reduced, tokenMs } from '@/lib/motion'

export function CountUp({ value, duration }: { value: unknown; duration?: number }) {
  const ref = useRef<HTMLSpanElement>(null)
  const shown = useRef(0)
  const frame = useRef(0)
  const target = typeof value === 'number' && Number.isFinite(value) ? value : null

  useEffect(() => {
    const node = ref.current
    if (!node) return
    if (target === null) {
      node.textContent = String(value)
      return
    }
    const from = shown.current
    shown.current = target
    cancelAnimationFrame(frame.current)
    if (reduced() || from === target) {
      node.textContent = String(target)
      return
    }
    const span = duration ?? tokenMs('--dur-5', 420)
    const start = performance.now()
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / span)
      const eased = 1 - Math.pow(1 - progress, 3)
      node.textContent = String(Math.round(from + (target - from) * eased))
      if (progress < 1) frame.current = requestAnimationFrame(step)
    }
    frame.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame.current)
  }, [target, value, duration])

  return (
    <span ref={ref} data-count-up>
      {target === null ? String(value) : '0'}
    </span>
  )
}