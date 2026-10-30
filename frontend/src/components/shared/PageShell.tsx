/**
 * 页面骨架：`.mount-slot > .view` 的结构不能省。
 *
 * layout.css:379-392 用 `.view-root > .mount-slot` 与 `.mount-slot > .view`
 * 两级 flex 把高度撑满，少一层页面就会塌成内容高度。
 * 页面模块由 LegacyPage 提供这两层，React 页面由这里提供，两者 DOM 形状一致。
 */
import type { ReactNode } from 'react'

export function PageFrame({ children }: { children: ReactNode }) {
  return (
    <div className="mount-slot">
      <div className="view">{children}</div>
    </div>
  )
}

/** 对应旧 `CPPages.pageShell(title, desc, actions, body)`（misc.js:13-21） */
export function PageShell({
  title,
  desc,
  actions,
  children,
}: {
  title: string
  desc?: string
  actions?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div>
            <h1 className="page-title">{title}</h1>
            <p className="page-desc">{desc}</p>
          </div>
          <div className="page-actions">{actions || null}</div>
        </div>
        {children}
      </div>
    </div>
  )
}
