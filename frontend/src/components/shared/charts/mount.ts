/**
 * 把 Recharts 组件挂进「字符串渲染」的容器里。
 *
 * 背景：店铺页与技能页的结果区是 `innerHTML` 拼出来的（`render.ts` / `blocks.ts`），
 * 图表宿主 `#st-trend` / `#st-hours` 只是字符串里的一个占位 div。
 * React 组件没法直接塞进 innerHTML，所以这里用 `createRoot` 命令式挂载。
 *
 * 三条纪律：
 *  1. **重绘前必须 `unmountCharts()`**。innerHTML 一换，旧宿主就脱离文档了，
 *     不卸载就会泄漏 root 与它的事件监听。
 *  2. 同一个宿主复用同一个 root（只 render），避免每次重绘都重建组件树。
 *  3. 宿主集合用 Map，卸载时逐个 unmount —— React 不允许在 render 期间卸载，
 *     调用点都在 effect 里，是安全的。
 */
import { createRoot, type Root } from 'react-dom/client'
import type { ReactNode } from 'react'

const roots = new Map<HTMLElement, Root>()

/** 在宿主里渲染（或更新）一棵 React 树 */
export function mountChart(host: HTMLElement | null, node: ReactNode): void {
  if (!host) return
  // `cp-chart` 是「这个宿主里有图表」的稳定标记：旧 charts.ts 会加，
  // 验收脚本（ui_skills_shot / ui_store_shot）按它断言，这里保持同名。
  host.classList.add('cp-chart')
  let root = roots.get(host)
  if (!root) {
    root = createRoot(host)
    roots.set(host, root)
  }
  root.render(node)
}

/** 重绘 innerHTML 之前调用：卸载全部图表，释放 root */
export function unmountCharts(): void {
  roots.forEach((root) => root.unmount())
  roots.clear()
}

/** 当前挂着的图表数量（诊断用） */
export function chartHostCount(): number {
  return roots.size
}
