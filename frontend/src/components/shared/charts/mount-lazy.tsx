/**
 * 图表的「命令式入口」——给字符串渲染的页面用。
 *
 * 为什么单独一层：`features/skills/blocks.ts` 是 .ts（返回 HTML 字符串），
 * 写不了 JSX；店铺页也不该重复写 lazy + Suspense 的样板。
 * 这里把两个图表包成函数，调用方只管传数据。
 *
 * 用法：
 *   unmountCharts()                 // 改写 innerHTML 之前
 *   stage.innerHTML = html
 *   mountTrend(host, { series })    // 宿主已在文档里，再挂图
 */
import { Suspense, lazy, type ReactElement } from 'react'
import { mountChart, unmountCharts } from './mount'
import type { TrendChartProps } from './TrendChart'
import type { BarChartProps } from './BarChart'

/* Recharts 约 350 KB（raw）/ 100 KB（gzip）：按需加载，页面先出内容再补图 */
const TrendChart = lazy(() =>
  import('./TrendChart').then((m) => ({ default: m.TrendChart })),
)
const BarChart = lazy(() => import('./BarChart').then((m) => ({ default: m.BarChart })))

/** 固定高度占位，避免图到达时页面跳动 */
function placeholder(height: number): ReactElement {
  return <div style={{ height }} />
}

export function mountTrend(host: HTMLElement | null, props: TrendChartProps): void {
  mountChart(
    host,
    <Suspense fallback={placeholder(props.height ?? 148)}>
      <TrendChart {...props} />
    </Suspense>,
  )
}

export function mountBars(host: HTMLElement | null, props: BarChartProps): void {
  mountChart(
    host,
    <Suspense fallback={placeholder(props.height ?? 168)}>
      <BarChart {...props} />
    </Suspense>,
  )
}

export { unmountCharts, chartHostCount } from './mount'
