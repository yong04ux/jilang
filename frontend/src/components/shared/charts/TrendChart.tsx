/**
 * 折线趋势图（Recharts）
 *
 * 为什么换成 Recharts：需要 hover 读数、X 轴按周期间隔抽稀、以及后续多序列
 * 叠加（经营看板的销售额/订单量双轴）。手写 SVG 每次加一种交互都要重算坐标系。
 *
 * 视觉必须沿用既有体系，不要退回 Recharts 默认样式：
 *  - 线色取 `--chart-1`（品牌蓝），柱/次序列取 `--chart-2`
 *  - 网格只用水平虚线，颜色 `--border`
 *  - 面积填充是**实色低透明度**，不是渐变（design.md 禁止渐变背景）
 *  - 卡片零阴影；tooltip 用 `--shadow-md` + `--card` + `--border`
 *  - 数字用 tabular-nums，避免跳动
 *
 * 空数据时不画贴底零线（原实现的纪律），直接给一句明确空态。
 */
import { money, num } from '@/lib/charts'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export interface TrendPoint {
  date: string
  value: number
}

export interface TrendChartProps {
  series: TrendPoint[]
  /** 图表高度（px）；外层容器宽度由 ResponsiveContainer 实测 */
  height?: number
  /** 数值格式：number 走千分位，money 走货币符号 */
  format?: 'number' | 'money'
  currency?: string
  /** 无障碍描述，同时用作 tooltip 的标题 */
  label?: string
  /** 空态文案 */
  emptyText?: string
}

/** 只保留 5 个刻度左右：日期标签太密反而看不清 */
function tickInterval(count: number): number {
  if (count <= 6) return 0
  return Math.ceil(count / 5) - 1
}

/** `2026-10-28` → `10-28` */
function shortDate(value: string): string {
  const parts = String(value || '').split('-')
  return parts.length >= 3 ? `${parts[1]}-${parts[2]}` : String(value || '')
}

/* 直接 import 格式化函数，不走 window.CPChart 门面：
   门面的类型声明是旧的单参数签名，而且这里本来就没有跨模块替换的需要。 */
function formatValue(value: number, format: TrendChartProps['format'], currency: string): string {
  return format === 'money' ? money(value, currency) : num(value)
}

export function TrendChart({
  series,
  height = 148,
  format = 'number',
  currency = 'USD',
  label,
  emptyText = '这段时间还没有数据',
}: TrendChartProps) {
  const rows = Array.isArray(series) ? series : []

  if (!rows.length) {
    return <div className="cp-chart-empty">{emptyText}</div>
  }

  return (
    <div style={{ height }} role="img" aria-label={label || '趋势图'}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 6, right: 6, bottom: 0, left: 0 }}>
          <CartesianGrid
            vertical={false}
            stroke="var(--border)"
            strokeDasharray="3 4"
            strokeOpacity={0.9}
          />
          <XAxis
            dataKey="date"
            tickFormatter={shortDate}
            interval={tickInterval(rows.length)}
            tickLine={false}
            axisLine={false}
            tick={{ fill: 'var(--faint)', fontSize: 10 }}
            dy={4}
          />
          <YAxis
            width={34}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
            tick={{ fill: 'var(--faint)', fontSize: 10 }}
            tickFormatter={(v: number) => formatValue(v, format, currency)}
          />
          <Tooltip
            cursor={{ stroke: 'var(--border-strong)', strokeWidth: 1 }}
            content={({ active, payload, label: rawLabel }) => {
              if (!active || !payload || !payload.length) return null
              const point = payload[0]?.payload as TrendPoint | undefined
              return (
                <div className="rounded-md border border-border bg-popover px-2 py-1.5 text-xs shadow-md">
                  <div className="text-[11px] text-muted-foreground">{String(rawLabel || '')}</div>
                  <div className="mt-0.5 font-medium tabular-nums text-foreground">
                    {formatValue(Number(point?.value ?? 0), format, currency)}
                  </div>
                </div>
              )
            }}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke="var(--chart-1)"
            strokeWidth={1.6}
            fill="var(--chart-1)"
            fillOpacity={0.08}
            /* 只有一个点时 Recharts 不画线也不画点，整块看着是空的 —— 显式补点 */
            dot={rows.length === 1 ? { r: 2.5, fill: 'var(--chart-1)', strokeWidth: 0 } : false}
            activeDot={{ r: 3, strokeWidth: 0, fill: 'var(--chart-1)' }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
