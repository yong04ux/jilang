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
import { tokenMs } from '@/lib/motion'
import { useMediaQuery } from '@/hooks/useMediaQuery'
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
  /** 撑满所在容器（面板等高时用），矮屏由 CSS 的 min-height 兜底 */
  fill?: boolean
  /** 数值格式：number 走千分位，money 走货币符号 */
  format?: 'number' | 'money'
  currency?: string
  /** 纵轴说明，例如「销售额（USD）」「任务数（个）」 */
  yLabel?: string
  /** 横轴说明，默认「日期」 */
  xLabel?: string
  /** 无障碍描述，同时用作 tooltip 的标题 */
  label?: string
  /** 空态文案 */
  emptyText?: string
}

interface DotArgs {
  cx?: number
  cy?: number
  index?: number
  payload?: TrendPoint
}

/** 均匀取 6 个日期刻度，且必定包含首尾两天——最右边的「今天」不能被抽掉 */
function pickTicks(rows: TrendPoint[]): string[] {
  const count = rows.length
  if (count <= 6) return rows.map((row) => row.date)
  const picks = new Set<number>()
  for (let i = 0; i < 6; i += 1) picks.add(Math.round(((count - 1) * i) / 5))
  return Array.from(picks)
    .sort((a, b) => a - b)
    .map((index) => rows[index].date)
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
  fill = false,
  format = 'number',
  currency = 'USD',
  yLabel,
  xLabel = '日期',
  label,
  emptyText = '这段时间还没有数据',
}: TrendChartProps) {
  const reduceMotion = useMediaQuery('(prefers-reduced-motion: reduce)')
  const rows = Array.isArray(series) ? series : []
  const resolvedYLabel = yLabel || (format === 'money' ? `金额（${currency}）` : '数值')
  // 稀疏序列才画点：只标有数的日子，零值留白；长序列不标，免得糊成一条珠链
  const renderDot = (props: DotArgs) => {
    const key = 'dot-' + (props.index ?? 0)
    const value = Number(props.payload?.value ?? 0)
    if (rows.length > 31 || props.cx == null || props.cy == null) return <g key={key} />
    if (!value && rows.length > 1) return <g key={key} />
    return (
      <circle
        key={key}
        cx={props.cx}
        cy={props.cy}
        r={2.4}
        fill="var(--paper-2)"
        stroke="var(--chart-1)"
        strokeWidth={2}
      />
    )
  }

  if (!rows.length) {
    return <div className="cp-chart-empty">{emptyText}</div>
  }

  return (
    <div
      className={fill ? 'cp-chart-fill' : undefined}
      style={fill ? { height: '100%' } : { height }}
      role="img"
      aria-label={`${label || '趋势图'}，横轴：${xLabel}，纵轴：${resolvedYLabel}`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 12, right: 22, bottom: 18, left: 4 }}>
          <CartesianGrid
            vertical={false}
            stroke="var(--border)"
            strokeDasharray="3 4"
            strokeOpacity={0.9}
          />
          <XAxis
            dataKey="date"
            tickFormatter={shortDate}
            ticks={pickTicks(rows)}
            interval={0}
            tickLine={false}
            axisLine={false}
            tick={{ fill: 'var(--faint)', fontSize: 10 }}
            dy={4}
            label={{
              value: xLabel,
              position: 'insideBottom',
              offset: -2,
              style: { fill: 'var(--faint)', fontSize: 10 },
            }}
          />
          <YAxis
            width={52}
            tickLine={false}
            axisLine={false}
            allowDecimals={false}
            tick={{ fill: 'var(--faint)', fontSize: 10 }}
            tickFormatter={(v: number) => formatValue(v, format, currency)}
            label={{
              value: resolvedYLabel,
              angle: -90,
              position: 'insideLeft',
              style: { textAnchor: 'middle', fill: 'var(--faint)', fontSize: 10 },
            }}
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
            /* 每日计数是离散量：直线段比平滑曲线更诚实，别把断层画成渐变 */
            type="linear"
            dataKey="value"
            stroke="var(--chart-1)"
            strokeWidth={2.2}
            fill="var(--chart-1)"
            fillOpacity={0.12}
            dot={renderDot}
            activeDot={{ r: 3.4, strokeWidth: 0, fill: 'var(--chart-1)' }}
            isAnimationActive={!reduceMotion}
            animationDuration={tokenMs('--dur-5', 420)}
            animationEasing="ease-out"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
