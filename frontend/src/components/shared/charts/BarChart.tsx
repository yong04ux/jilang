/**
 * 柱状图（Recharts）—— 24 小时分布、成本构成这类「分类 + 单值」的数据。
 *
 * 与 TrendChart 共用同一套视觉语言：
 *  - 柱色 `--chart-2`（浅蓝），hover 加深到 `--chart-1`
 *  - 网格只用水平虚线，颜色 `--border`
 *  - 卡片零阴影，tooltip 用 `--card` + `--border` + `--shadow-md`
 *  - 数字 tabular-nums
 *
 * 分类多时（如 24 小时）自动抽稀刻度，否则 X 轴会糊成一片。
 */
import {
  Bar,
  BarChart as RBarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { money, num } from '@/lib/charts'

export interface BarPoint {
  /** X 轴显示文案 */
  label: string
  value: number
}

export interface BarChartProps {
  series: BarPoint[]
  height?: number
  /** Y 轴与 tooltip 的数值格式；金钱类传 currency 走货币符号 */
  format?: 'number' | 'money'
  currency?: string
  label?: string
  emptyText?: string
  /** 柱宽上限，24 根柱子时不要铺满 */
  maxBarSize?: number
}

function tickInterval(count: number): number {
  if (count <= 8) return 0
  return Math.ceil(count / 8) - 1
}

export function BarChart({
  series,
  height = 168,
  format = 'number',
  currency = 'USD',
  label,
  emptyText = '这段时间没有数据',
  maxBarSize = 28,
}: BarChartProps) {
  const rows = Array.isArray(series) ? series : []
  const hasValue = rows.some((r) => Number(r.value) > 0)

  // 全 0 不画一排贴底空柱 —— 那是「空壳图」，什么信息都没给
  if (!rows.length || !hasValue) {
    return <div className="cp-chart-empty">{emptyText}</div>
  }

  const fmt = (v: number) => (format === 'money' ? money(v, currency) : num(v))

  return (
    <div style={{ height }} role="img" aria-label={label || '柱状图'}>
      <ResponsiveContainer width="100%" height="100%">
        <RBarChart data={rows} margin={{ top: 6, right: 6, bottom: 0, left: 0 }} barCategoryGap="18%">
          <CartesianGrid
            vertical={false}
            stroke="var(--border)"
            strokeDasharray="3 4"
            strokeOpacity={0.9}
          />
          <XAxis
            dataKey="label"
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
            tickFormatter={(v: number) => fmt(v)}
          />
          <Tooltip
            cursor={{ fill: 'var(--accent)' }}
            content={({ active, payload, label: rawLabel }) => {
              if (!active || !payload || !payload.length) return null
              const point = payload[0]?.payload as BarPoint | undefined
              return (
                <div className="rounded-md border border-border bg-popover px-2 py-1.5 text-xs shadow-md">
                  <div className="text-[11px] text-muted-foreground">{String(rawLabel || '')}</div>
                  <div className="mt-0.5 font-medium tabular-nums text-foreground">
                    {fmt(Number(point?.value ?? 0))}
                  </div>
                </div>
              )
            }}
          />
          <Bar dataKey="value" radius={[2, 2, 0, 0]} maxBarSize={maxBarSize} isAnimationActive={false}>
            {rows.map((row, i) => (
              <Cell key={i} fill="var(--chart-2)" />
            ))}
          </Bar>
        </RBarChart>
      </ResponsiveContainer>
    </div>
  )
}
