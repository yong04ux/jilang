/**
 * 条件挂载组件的「退场在场证明」。
 *
 * `{open ? <Drawer/> : null}` 会在 open 变 false 的那一帧直接卸载，退场动画没机会播。
 * 这里把卸载推迟到退场时长走完：open=false 时先置 state='closed' 让 CSS 播退场，
 * 时长取自 tokens.css，reduced-motion 下立即卸载、不落中间态。
 */
import { useEffect, useState } from 'react'
import { reduced, tokenMs } from '@/lib/motion'

export type PresenceState = 'open' | 'closed'

export function usePresence(
  open: boolean,
  exitToken: '--dur-2' | '--dur-3' = '--dur-3',
): { mounted: boolean; state: PresenceState } {
  const [mounted, setMounted] = useState(open)
  const [state, setState] = useState<PresenceState>(open ? 'open' : 'closed')

  useEffect(() => {
    if (open) {
      setMounted(true)
      setState('open')
      return
    }
    setState((prev) => (prev === 'open' ? 'closed' : prev))
    if (!mounted) return
    if (reduced()) {
      setMounted(false)
      return
    }
    // +40ms：等 CSS 动画的最后一帧落地，避免卸载抢在 animationend 之前
    const timer = window.setTimeout(() => setMounted(false), tokenMs(exitToken, 280) + 40)
    return () => window.clearTimeout(timer)
  }, [open, mounted, exitToken])

  return { mounted, state }
}