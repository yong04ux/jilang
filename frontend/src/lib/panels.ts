/**
 * 分栏与排序 —— 从旧 `js/panels.js` 迁移。
 *
 * 1) `split(container, opts)`：react-resizable-panels 的等价实现。
 *    在前两个子节点之间插一条 1px 拖拽条，比例写进 `--split-a` 并落 localStorage；
 *    <=960px 时由 CSS 接管、自动退化为上下堆叠。
 * 2) `sortable(list, opts)`：dnd-kit 的等价实现，基于原生 draggable。
 *
 * 与 charts 一样不 import 任何东西，方便在浏览器里与旧实现逐项对照。
 */

type SplitContainer = HTMLElement & { __cpSplit?: SplitApi }

interface SplitOptions {
  storageKey?: string
  min?: number
  max?: number
  defaultSize?: number
  label?: string
}

interface SplitApi {
  setSize(ratio: number): void
  getSize(): number
  destroy(): void
}

const NARROW = typeof window !== 'undefined' ? window.matchMedia('(max-width: 960px)') : null

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export function split(container: HTMLElement | null, options: SplitOptions = {}): SplitApi | null {
  if (!container) return null
  const node = container as SplitContainer

  /* 幂等：重复 render 时不重复挂载 */
  if (node.__cpSplit) return node.__cpSplit

  const existing = node.querySelector(':scope > .split-handle') as HTMLElement | null
  const handle =
    existing ||
    (() => {
      const panes = Array.prototype.filter.call(node.children, (child: Element) => {
        return !child.classList.contains('split-handle')
      }) as HTMLElement[]
      if (panes.length < 2) return null
      const bar = document.createElement('div')
      bar.className = 'split-handle'
      panes[0].after(bar)
      return bar
    })()

  if (!handle) return null
  // TS 在嵌套闭包里不保留窄化，这里固定成非空引用
  const bar: HTMLElement = handle

  const key = options.storageKey || 'cp.split:' + (node.id || 'pane')
  const min = options.min === undefined ? 0.28 : options.min
  const max = options.max === undefined ? 0.78 : options.max
  const fallback = options.defaultSize === undefined ? 0.58 : options.defaultSize

  let value = fallback
  try {
    const saved = parseFloat(localStorage.getItem(key) as string)
    if (!Number.isNaN(saved)) value = clamp(saved, min, max)
  } catch {
    /* 隐私模式忽略 */
  }

  function apply(next: number, persist: boolean): void {
    value = clamp(next, min, max)
    node.style.setProperty('--split-a', (value * 100).toFixed(2) + '%')
    bar.setAttribute('aria-valuenow', String(Math.round(value * 100)))
    bar.setAttribute('aria-valuemin', String(Math.round(min * 100)))
    bar.setAttribute('aria-valuemax', String(Math.round(max * 100)))
    if (persist) {
      try {
        localStorage.setItem(key, String(value))
      } catch {
        /* 忽略 */
      }
    }
  }

  bar.setAttribute('role', 'separator')
  bar.setAttribute('aria-orientation', 'vertical')
  bar.setAttribute('aria-label', options.label || '调整分栏宽度')
  bar.tabIndex = 0

  let dragging = false

  function onPointerDown(event: PointerEvent): void {
    if (NARROW && NARROW.matches) return
    if (event.button !== undefined && event.button !== 0) return
    dragging = true
    node.classList.add('is-resizing')
    document.body.classList.add('is-resizing')
    bar.setPointerCapture(event.pointerId)
    event.preventDefault()
  }

  function onPointerMove(event: PointerEvent): void {
    if (!dragging) return
    const rect = node.getBoundingClientRect()
    if (rect.width === 0) return
    apply((event.clientX - rect.left) / rect.width, false)
  }

  function onPointerUp(event: PointerEvent): void {
    if (!dragging) return
    dragging = false
    node.classList.remove('is-resizing')
    document.body.classList.remove('is-resizing')
    if (bar.hasPointerCapture && bar.hasPointerCapture(event.pointerId)) {
      bar.releasePointerCapture(event.pointerId)
    }
    apply(value, true)
  }

  function onKeyDown(event: KeyboardEvent): void {
    const step = event.shiftKey ? 0.08 : 0.02
    if (event.key === 'ArrowLeft') {
      apply(value - step, true)
      event.preventDefault()
    } else if (event.key === 'ArrowRight') {
      apply(value + step, true)
      event.preventDefault()
    } else if (event.key === 'Home') {
      apply(min, true)
      event.preventDefault()
    } else if (event.key === 'End') {
      apply(max, true)
      event.preventDefault()
    }
  }

  function onReset(): void {
    apply(fallback, true)
  }

  bar.addEventListener('pointerdown', onPointerDown)
  bar.addEventListener('pointermove', onPointerMove)
  bar.addEventListener('pointerup', onPointerUp)
  bar.addEventListener('pointercancel', onPointerUp)
  bar.addEventListener('keydown', onKeyDown)
  bar.addEventListener('dblclick', onReset)

  const api: SplitApi = {
    setSize(ratio: number) {
      apply(ratio, true)
    },
    getSize() {
      return value
    },
    destroy() {
      bar.removeEventListener('pointerdown', onPointerDown)
      bar.removeEventListener('pointermove', onPointerMove)
      bar.removeEventListener('pointerup', onPointerUp)
      bar.removeEventListener('pointercancel', onPointerUp)
      bar.removeEventListener('keydown', onKeyDown)
      bar.removeEventListener('dblclick', onReset)
      delete node.__cpSplit
    },
  }

  node.__cpSplit = api
  return api
}

interface SortableOptions {
  item?: string
  onStart?(el: HTMLElement): void
  onEnd?(ids: Array<string | null>): void
}

export function sortable(
  list: HTMLElement | null,
  options: SortableOptions = {},
): { refresh(): void; items(): HTMLElement[] } | null {
  if (!list) return null
  const host: HTMLElement = list
  const itemSel = options.item || ':scope > *'
  let dragEl: HTMLElement | null = null

  const items = (): HTMLElement[] =>
    Array.prototype.slice.call(host.querySelectorAll(itemSel)) as HTMLElement[]

  function bind(): void {
    items().forEach((el) => {
      if (el.dataset.sortable === '1') return
      el.dataset.sortable = '1'
      el.draggable = true
      el.classList.add('drag-item')

      el.addEventListener('dragstart', (event) => {
        dragEl = el
        el.classList.add('is-dragging')
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = 'move'
          event.dataTransfer.setData('text/plain', el.dataset.id || '')
        }
        options.onStart?.(el)
      })

      el.addEventListener('dragend', () => {
        el.classList.remove('is-dragging')
        items().forEach((node) => node.classList.remove('is-drop-target'))
        dragEl = null
        options.onEnd?.(items().map((node) => node.dataset.id || null))
      })

      el.addEventListener('dragover', (event) => {
        if (!dragEl || dragEl === el) return
        event.preventDefault()
        const box = el.getBoundingClientRect()
        const before = event.clientY - box.top < box.height / 2
        host.insertBefore(dragEl, before ? el : el.nextSibling)
        items().forEach((node) => {
          node.classList.toggle('is-drop-target', node === el)
        })
      })

      el.addEventListener('drop', (event) => {
        event.preventDefault()
      })
    })
  }

  bind()
  return { refresh: bind, items }
}

export const panelsApi = { split, sortable }
