/**
 * 全站图片放大层。
 *
 * 页面里的商品图来自 HTML 字符串与 React 两条渲染路径，所以用 document 级
 * 事件委托：任何带 data-zoom 的 <img> 点击后都能放大，不必逐个页面挂状态。
 */
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

interface Target {
  src: string
  title: string
}

interface Size {
  width: number
  height: number
}

export function ImageLightbox() {
  const [target, setTarget] = useState<Target | null>(null)
  const [base, setBase] = useState<Size | null>(null)
  const [scale, setScale] = useState(1)
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const img = (event.target as Element | null)?.closest?.('img[data-zoom]') as HTMLImageElement | null
      if (!img) return
      event.preventDefault()
      event.stopPropagation()
      const src = img.getAttribute('data-zoom-src') || img.currentSrc || img.src
      if (!src) return
      setTarget({ src, title: img.getAttribute('data-zoom-title') || img.alt || '商品图' })
      setBase(null)
      setScale(1)
    }
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [])

  useEffect(() => {
    if (!target) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setTarget(null)
    }
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKey)
    window.setTimeout(() => closeRef.current?.focus(), 0)
    return () => {
      document.body.style.overflow = previous
      document.removeEventListener('keydown', onKey)
    }
  }, [target])

  if (!target) return null

  const onLoad = (event: React.SyntheticEvent<HTMLImageElement>) => {
    const img = event.currentTarget
    const ratio = Math.min(
      (window.innerWidth * 0.88) / img.naturalWidth,
      (window.innerHeight * 0.76) / img.naturalHeight,
    )
    setBase({ width: img.naturalWidth * ratio, height: img.naturalHeight * ratio })
  }

  const width = base ? base.width * scale : undefined
  const height = base ? base.height * scale : undefined

  return createPortal(
    <div
      className="img-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={target.title}
      onClick={(event) => {
        if (event.target === event.currentTarget) setTarget(null)
      }}
    >
      <div className="img-lightbox-bar">
        <span className="img-lightbox-title">{target.title}</span>
        <div className="img-lightbox-tools">
          <button
            type="button"
            className="img-lightbox-btn"
            aria-label="缩小"
            disabled={scale <= 1}
            onClick={() => setScale((value) => Math.max(1, value - 0.5))}
          >
            −
          </button>
          <span className="img-lightbox-scale">{Math.round(scale * 100)}%</span>
          <button
            type="button"
            className="img-lightbox-btn"
            aria-label="放大"
            disabled={scale >= 3}
            onClick={() => setScale((value) => Math.min(3, value + 0.5))}
          >
            ＋
          </button>
          <button
            type="button"
            className="img-lightbox-btn"
            aria-label="重置"
            onClick={() => setScale(1)}
          >
            适应
          </button>
          <button
            ref={closeRef}
            type="button"
            className="img-lightbox-btn is-close"
            aria-label="关闭"
            onClick={() => setTarget(null)}
          >
            ×
          </button>
        </div>
      </div>
      <div
        className="img-lightbox-stage"
        onClick={(event) => {
          if (event.target === event.currentTarget) setTarget(null)
        }}
      >
        <img
          src={target.src}
          alt={target.title}
          width={width}
          height={height}
          style={{ width, height }}
          onLoad={onLoad}
          onClick={() => setScale((value) => (value === 1 ? 2 : 1))}
        />
      </div>
    </div>,
    document.body,
  )
}
