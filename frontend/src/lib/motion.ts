/**
 * 动效层 —— Motion（原 Framer Motion）的等价实现，基于 Web Animations API。
 *
 * 三条纪律（design.md:161-173）：
 *  1. 曲线与时长一律从 tokens.css 的 `--ease-*` / `--dur-*` 读，不写死数字；
 *  2. `prefers-reduced-motion: reduce` 下所有动画归零，直接落终态；
 *  3. JS 与 CSS 用同一套节奏，避免「边框先到、位移后到」。
 */

/* 惰性取媒体查询：模块求值时不做任何事，避免在无 window 的环境（Node 里跑
   语义对照脚本、将来的 SSR）直接抛错。 */
let reducedQuery: MediaQueryList | null | undefined

function mediaQuery(): MediaQueryList | null {
  if (reducedQuery === undefined) {
    reducedQuery =
      typeof window !== 'undefined' && typeof window.matchMedia === 'function'
        ? window.matchMedia('(prefers-reduced-motion: reduce)')
        : null
  }
  return reducedQuery
}

export function reduced(): boolean {
  return mediaQuery()?.matches ?? false
}

type Duration = number | string

function toMs(value: unknown, fallback: number): number {
  if (typeof value === 'number') return value
  if (typeof value === 'string' && /ms$/.test(value)) return parseFloat(value)
  if (typeof value === 'string' && /s$/.test(value)) return parseFloat(value) * 1000
  return fallback
}

function tokenMs(name: string, fallback: number): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name)
  return toMs(raw.trim(), fallback)
}

interface AnimateOptions {
  duration?: Duration
  delay?: number
  easing?: string
  fill?: FillMode
  iterations?: number
  onComplete?: () => void
}

interface FadeOptions {
  x?: number
  y?: number
  scale?: number
  duration?: Duration
  delay?: number
  onComplete?: () => void
}

/** 动画结束后把最后一帧写成 inline style，避免 fill 结束后回跳 */
function finish(el: HTMLElement, frames: Keyframe[]): void {
  const last = frames[frames.length - 1]
  if (!last) return
  Object.keys(last).forEach((key) => {
    if (key === 'offset' || key === 'easing') return
    el.style[key as unknown as 'opacity'] = String((last as Record<string, unknown>)[key])
  })
}

export function animate(
  el: Element | null,
  frames: Keyframe[],
  options: AnimateOptions = {},
): Promise<void> {
  const node = el as HTMLElement | null
  if (!node) return Promise.resolve()

  const duration =
    options.duration !== undefined ? toMs(options.duration, 180) : tokenMs('--dur-2', 180)
  const delay = toMs(options.delay, 0) || 0

  if (reduced() || duration === 0) {
    finish(node, frames)
    options.onComplete?.()
    return Promise.resolve()
  }

  if (typeof node.animate !== 'function') {
    finish(node, frames)
    return Promise.resolve()
  }

  const anim = node.animate(frames, {
    duration,
    delay,
    easing: options.easing || 'cubic-bezier(.16, 1, .3, 1)',
    fill: options.fill || 'backwards',
    iterations: options.iterations || 1,
  })

  return anim.finished
    .then(() => {
      finish(node, frames)
      options.onComplete?.()
    })
    .catch(() => {
      /* 被 cancel 视为完成 */
    })
}

export function fadeIn(el: Element | null, options: FadeOptions = {}): Promise<void> {
  const y = options.y === undefined ? 4 : options.y
  const x = options.x === undefined ? 0 : options.x
  const scale = options.scale === undefined ? 1 : options.scale
  const from =
    'translate3d(' + x + 'px,' + y + 'px,0)' + (scale === 1 ? '' : ' scale(' + scale + ')')
  return animate(
    el,
    [
      { opacity: 0, transform: from },
      { opacity: 1, transform: 'translate3d(0,0,0) scale(1)' },
    ],
    {
      duration: options.duration !== undefined ? options.duration : tokenMs('--dur-2', 180),
      delay: options.delay,
      onComplete: options.onComplete,
    },
  )
}

export function fadeOut(
  el: Element | null,
  options: FadeOptions & { remove?: boolean } = {},
): Promise<void> {
  const y = options.y === undefined ? 2 : options.y
  return animate(
    el,
    [
      { opacity: 1, transform: 'translate3d(0,0,0)' },
      { opacity: 0, transform: 'translate3d(0,' + y + 'px,0)' },
    ],
    {
      duration: options.duration !== undefined ? options.duration : tokenMs('--dur-1', 120),
      fill: 'forwards',
    },
  ).then(() => {
    const node = el as HTMLElement | null
    if (options.remove !== false && node?.parentNode) node.parentNode.removeChild(node)
    options.onComplete?.()
  })
}

interface StaggerOptions {
  selector?: string
  step?: number
  y?: number
  duration?: Duration
}

/** 交错进场：默认对 `[data-motion-item]` 按 24ms 步长依次淡入 */
export function stagger(container: Element | null, options: StaggerOptions = {}): Promise<unknown> {
  if (!container) return Promise.resolve()
  const items = container.querySelectorAll(options.selector || '[data-motion-item]')
  if (!items.length) return Promise.resolve()
  const step = options.step === undefined ? 24 : options.step
  const y = options.y === undefined ? 6 : options.y
  const jobs: Promise<void>[] = []
  Array.prototype.forEach.call(items, (el: Element, i: number) => {
    jobs.push(fadeIn(el, { y, delay: i * step, duration: options.duration }))
  })
  return Promise.all(jobs)
}

interface InViewOptions {
  rootMargin?: string
  threshold?: number
}

/** 进入视口一次性回调；不支持 IntersectionObserver 时立即执行 */
export function inView(
  el: Element | null,
  callback: ((el: Element | null) => void) | null,
  options: InViewOptions = {},
): () => void {
  if (!el || typeof IntersectionObserver !== 'function') {
    if (typeof callback === 'function') callback(el)
    return () => undefined
  }
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return
        io.unobserve(entry.target)
        if (typeof callback === 'function') callback(entry.target)
      })
    },
    {
      rootMargin: options.rootMargin || '0px 0px -10% 0px',
      threshold: options.threshold || 0.1,
    },
  )
  io.observe(el)
  return () => io.disconnect()
}

/** 按下微缩（Motion 的 whileTap 等价物） */
export function tap(el: Element | null, scale?: number): void {
  const node = el as HTMLElement | null
  if (!node) return
  const s = scale === undefined ? 0.985 : scale
  node.addEventListener('pointerdown', () => {
    if (reduced()) return
    node.style.transition = 'transform 90ms cubic-bezier(.16,1,.3,1)'
    node.style.transform = 'scale(' + s + ')'
  })
  ;['pointerup', 'pointerleave', 'pointercancel'].forEach((evt) => {
    node.addEventListener(evt, () => {
      node.style.transform = ''
    })
  })
}

export function scrollTo(el: Element | null, options: { block?: ScrollLogicalPosition } = {}): void {
  if (!el) return
  el.scrollIntoView({
    block: options.block || 'nearest',
    behavior: reduced() ? 'auto' : 'smooth',
  })
}

export const motionApi = {
  reduced,
  animate,
  fadeIn,
  fadeOut,
  stagger,
  inView,
  tap,
  scrollTo,
}
