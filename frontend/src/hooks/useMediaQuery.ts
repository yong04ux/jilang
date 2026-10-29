/**
 * 订阅一条媒体查询。
 *
 * 外壳用它是为了替代原 layout.css 里「窄屏强制退回图标栏」的
 * `display: none !important` —— 那组规则靠 CSS 硬压，和 Tailwind 的条件类名
 * 会互相打架。改成在 JS 里算：窄屏时展开态不生效，DOM 只剩一套形态。
 *
 * 用 matchMedia 而不是监听 resize：后者每次拖动都会触发更新，
 * 前者只在跨越断点时回调。
 */
import { useEffect, useState } from 'react'

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia(query).matches
      : false,
  )

  useEffect(() => {
    if (!window.matchMedia) return
    const list = window.matchMedia(query)
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches)
    setMatches(list.matches)
    list.addEventListener('change', onChange)
    return () => list.removeEventListener('change', onChange)
  }, [query])

  return matches
}

/** 外壳的窄屏断点：与 tailwind.css 的 `shell`（981px）保持一致 */
export function useShellNarrow(): boolean {
  return useMediaQuery('(max-width: 980px)')
}
