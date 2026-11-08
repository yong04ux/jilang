/**
 * 页签墨条：一条绝对定位的指示条滑到当前项，代替「换 class 瞬间跳色」。
 *
 * 三种当前项标记都认：手写 `.is-active`、Radix 的 `data-state="active"` /
 * `aria-selected="true"`。遗留页整块 innerHTML 重绘会把墨条一起冲掉，
 * 所以每次量位置前先确认墨条还挂在条上，不在就补回去并重新生长。
 * 时长曲线全走 CSS 的 --dur-3 / --ease-out，reduced-motion 下直接落终态。
 */
import { reduced } from '@/lib/motion'

const ACTIVE = '.is-active, [aria-selected="true"], [data-state="active"]'

export interface InkBarOptions {
  /** 页签项选择器，默认直接子元素 */
  item?: string
  /** x = 底部横条（页签），y = 左侧竖条（分区导航） */
  axis?: 'x' | 'y'
  className?: string
}

export function inkBar(bar: HTMLElement | null, options: InkBarOptions = {}): () => void {
  if (!bar) return () => undefined
  const host: HTMLElement = bar
  const axis = options.axis ?? 'x'
  const itemSel = options.item ?? ':scope > *'
  const ink = document.createElement('span')
  ink.className = options.className ?? (axis === 'x' ? 'tab-ink' : 'set-ink')
  ink.setAttribute('aria-hidden', 'true')
  let born = false
  let frame = 0

  function target(): HTMLElement | null {
    const items = host.querySelectorAll<HTMLElement>(itemSel)
    for (let i = 0; i < items.length; i++) {
      if (items[i].matches(ACTIVE)) return items[i]
    }
    return null
  }

  function place(): void {
    if (!ink.isConnected) {
      host.appendChild(ink)
      born = false
    }
    const node = target()
    if (!node) {
      ink.style.opacity = '0'
      return
    }
    ink.style.opacity = '1'
    const off = axis === 'x' ? node.offsetLeft : node.offsetTop
    const size = axis === 'x' ? node.offsetWidth : node.offsetHeight
    const set = (value: number) => {
      if (axis === 'x') ink.style.width = value + 'px'
      else ink.style.height = value + 'px'
    }
    ink.style.transform = axis === 'x' ? 'translateX(' + off + 'px)' : 'translateY(' + off + 'px)'
    if (reduced()) {
      ink.style.transition = 'none'
      set(size)
      born = true
      return
    }
    if (!born) {
      // 首次：先零尺寸落位，再下一帧长出来，得到「墨条生长」而不是凭空出现
      born = true
      ink.style.transition = 'none'
      set(0)
      void ink.offsetWidth
      ink.style.transition = ''
      set(size)
      return
    }
    ink.style.transition = ''
    set(size)
  }

  function schedule(): void {
    cancelAnimationFrame(frame)
    frame = requestAnimationFrame(place)
  }

  host.addEventListener('click', schedule, true)
  const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(schedule) : null
  ro?.observe(bar)
  const mo = new MutationObserver((records) => {
    const onlyInk = records.every(
      (r) => r.addedNodes.length === 1 && r.addedNodes[0] === ink && r.removedNodes.length === 0,
    )
    if (!onlyInk) schedule()
  })
  mo.observe(bar, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class', 'data-state', 'aria-selected'],
  })
  schedule()

  return () => {
    cancelAnimationFrame(frame)
    host.removeEventListener('click', schedule, true)
    ro?.disconnect()
    mo.disconnect()
    ink.remove()
  }
}