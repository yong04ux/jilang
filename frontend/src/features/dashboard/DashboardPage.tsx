/**
 * 工作台 —— 首屏门面。
 *
 * 三条纪律（原注释保留，改造时一条没动）：
 *  - 所有数字来自 /api/dashboard 与 /api/marketplace/metrics，前端不推算任何指标；
 *  - 还没有数据的模块保持空态，不显示推测性指标；
 *  - 趋势全 0 时不画贴底零线 —— 那是「空壳图」，什么信息都没给。
 *
 * ── 本轮改造（Phase 4-1）────────────────────────────────────────────
 * 结构：KPI 行 / 经营概览 / 任务趋势 / 最近报告 / 近期任务 / 最近 Listing /
 * 数据源状态，全部换成 Card + Table + Badge + Alert + Skeleton。
 *
 * **趋势图仍是 `lib/charts.ts` 的手写内联 SVG，没有换 Recharts**：
 * 它已有 28 项字节级对照、零依赖，而我们只有折线一种图；换库会给本页 chunk
 * 增加约 90 KB，收益只有「可交互 tooltip」。要换单独做，并给出体积对比。
 * `#dash-trend` 这个 id 是 CPChart 的宿主，也是探针钩子，别改。
 *
 * 探针钩子已从样式类名换成语义属性：
 *   [data-kpi] / [data-kpi-label] / [data-dash-card] / [data-task-table]
 * 空的占位符 `.cp-chart-empty` 由本文件自己注入，保留类名。
 */
import { Suspense, lazy, useEffect, useState } from 'react'
import { FileText, ListChecks, ScrollText, Sparkles, TriangleAlert } from 'lucide-react'
import { api } from '@/lib/api'
import { getHealth } from '@/lib/health/health'
import { fmtTime } from '@/lib/ui'
import {
  language as labelLanguage,
  platform as labelPlatform,
  site as labelSite,
  taskType,
} from '@/lib/labels'
import { PageFrame, PageShell } from '@/components/shared/PageShell'
import { StatusBadge } from '@/components/shared/StatusBadge'
/* Recharts 单独成 chunk：它是本页最重的一块（约 350 KB raw），
   而 KPI / 列表 / 空态并不需要它。拆开后进工作台先看到数字，
   图表随后补上；也避免把它塞进任何其它页面。 */
const TrendChart = lazy(() =>
  import('@/components/shared/charts/TrendChart').then((m) => ({ default: m.TrendChart })),
)
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertTitle } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

type Dict = Record<string, any>

interface DashData {
  stats?: Dict
  recent_tasks?: Dict[]
  recent_reports?: Dict[]
  recent_listings?: Dict[]
  daily_tasks?: Dict[]
  data_sources?: Dict[]
}

type View =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: DashData; shop: Dict | null; needsKey: boolean }

/* ------------------------------------------------------------------ 小件 */

function Kpi({ label, value, note }: { label: string; value: unknown; note?: string }) {
  return (
    <div className="bg-card px-4 py-3.5" data-kpi>
      <div className="text-xs text-muted-foreground" data-kpi-label>
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums leading-tight">{String(value)}</div>
      {note ? <div className="mt-0.5 text-[11px] text-faint">{note}</div> : null}
    </div>
  )
}

/** 空态：图标 + 一句结论 + 一句下一步，不写「暂无数据」这种废话 */
function EmptyBlock({
  icon: Icon,
  title,
  desc,
  actions,
  compact,
}: {
  icon: typeof FileText
  title: string
  desc: string
  actions?: React.ReactNode
  compact?: boolean
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-1.5 text-center',
        compact ? 'px-4 py-6' : 'px-6 py-10',
      )}
    >
      <Icon className="size-5 text-faint" aria-hidden="true" />
      <p className="text-[13px] font-medium text-foreground">{title}</p>
      <p className="max-w-72 text-xs leading-relaxed text-muted-foreground">{desc}</p>
      {actions ? <div className="mt-2 flex flex-wrap justify-center gap-2">{actions}</div> : null}
    </div>
  )
}

/** 卡片头：标题 + 说明 + 右侧动作（与 shadcn Card 组合用） */
function SectionHead({
  title,
  desc,
  action,
}: {
  title: string
  desc?: string
  action?: React.ReactNode
}) {
  return (
    <CardHeader className="flex-row items-start justify-between gap-3 space-y-0 pb-0">
      <div className="min-w-0">
        <CardTitle>{title}</CardTitle>
        {desc ? <CardDescription className="mt-0.5">{desc}</CardDescription> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </CardHeader>
  )
}

/* 经营概览：4 个核心指标，点进去是完整经营看板 */
function ShopOverview({ m }: { m: Dict }) {
  const sm = m.salesMetrics || {}
  const currency = m.currency || 'USD'
  const chart = window.CPChart
  const money = (v: unknown) => (chart ? chart.moneyFull(v, currency) : '—')
  const num = (v: unknown) => (chart ? chart.num(v) : '—')

  const deltaTag = (value: unknown) => {
    if (value === null || value === undefined || !isFinite(Number(value))) {
      return <span className="text-[11px] text-faint">无对比</span>
    }
    const n = Number(value)
    if (Math.abs(n) < 0.05) return <span className="text-[11px] text-faint">持平</span>
    return (
      <span className={cn('text-[11px] font-medium', n > 0 ? 'text-success' : 'text-destructive')}>
        {n > 0 ? '▲' : '▼'} {Math.abs(n).toFixed(1)}%
        <span className="opacity-60"> 环比</span>
      </span>
    )
  }

  const cell = (key: string, label: string, format: (v: unknown) => string) => {
    const item = sm[key] || { value: 0, changePct: null }
    return (
      <div className="bg-card px-4 py-3" key={key}>
        <div className="text-xs text-muted-foreground">{item.label || label}</div>
        <div className="mt-1 text-lg font-semibold tabular-nums leading-tight">
          {format(item.value)}
        </div>
        {deltaTag(item.changePct)}
      </div>
    )
  }

  return (
    <Card className="mt-4 gap-0 overflow-hidden">
      <SectionHead
        title="经营概览"
        desc={`这家店近 ${m.days || 30} 天的销售情况，与上一个等长周期对比`}
        action={
          <Button size="sm" variant="ghost" asChild>
            <a href="/stores" data-link="">
              经营看板
            </a>
          </Button>
        }
      />
      <div className="mt-3 grid grid-cols-2 gap-px border-t border-border bg-border md:grid-cols-4">
        {cell('salesAmount', '销售额', money)}
        {cell('unitCount', '销量', num)}
        {cell('orderCount', '订单量', num)}
        {cell('aov', '客单价', money)}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ 页面 */

export function DashboardPage() {
  const [view, setView] = useState<View>({ kind: 'loading' })
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let alive = true
    setView({ kind: 'loading' })

    // 三个请求互不依赖：一起发出，别串成瀑布。
    // 健康状态与顶栏共用同一份 15s 缓存，首屏只发一次。
    const healthPromise = getHealth().catch(() => null)
    const providerPromise = api.get<Dict>('/api/settings/providers').catch(() => null)

    ;(async () => {
      let data: DashData
      try {
        data = await api.get<DashData>('/api/dashboard')
      } catch (err) {
        if (alive) setView({ kind: 'error', message: (err as Error).message || String(err) })
        return
      }
      const providerInfo = await providerPromise
      const health = await healthPromise
      // 进站第一屏就要说清「还差一步：配自己的 Key」
      const needsKey =
        Boolean(providerInfo) &&
        !providerInfo!.active_config_id &&
        !(health && health.requires_api_key === false)

      let shop: Dict | null = null
      try {
        shop = await api.get<Dict>('/api/marketplace/metrics?range=30d')
      } catch {
        shop = null
      }
      if (alive) setView({ kind: 'ready', data, shop, needsKey })
    })()

    return () => {
      alive = false
    }
  }, [nonce])

  if (view.kind === 'loading') {
    return (
      <PageFrame>
        <PageShell title="工作台" desc="你的任务、报告与数据生成情况。还没有数据的模块会保持空态。">
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border xl:grid-cols-5">
            {[0, 1, 2, 3, 4].map((i) => (
              <div className="bg-card px-4 py-3.5" key={i}>
                <Skeleton className="h-3 w-14" />
                <Skeleton className="mt-2 h-6 w-10" />
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
            {[0, 1].map((i) => (
              <Card className="gap-0 p-4" key={i}>
                <Skeleton className="h-3.5 w-20" />
                <Skeleton className="mt-4 h-36 w-full" />
              </Card>
            ))}
          </div>
        </PageShell>
      </PageFrame>
    )
  }

  if (view.kind === 'error') {
    return (
      <PageFrame>
        <PageShell title="工作台" desc="">
          <Alert variant="destructive">
            <TriangleAlert />
            <AlertTitle>
              加载失败：{view.message}
              <div className="mt-2">
                <Button size="sm" variant="outline" data-retry="" onClick={() => setNonce((n) => n + 1)}>
                  重试
                </Button>
              </div>
            </AlertTitle>
          </Alert>
        </PageShell>
      </PageFrame>
    )
  }

  const { data, shop, needsKey } = view
  const stats = data.stats || {}
  const tasks = data.recent_tasks || []
  const reports = data.recent_reports || []
  const listings = data.recent_listings || []
  const sources = data.data_sources || []
  const hasTrend = (data.daily_tasks || []).some((d) => Number(d.count) > 0)

  const badgeFor = (s: Dict) => {
    if (s.mode === 'upload') return <Badge variant="secondary">你的文件</Badge>
    if (s.configured && s.mode === 'live') return <Badge variant="success">已连接</Badge>
    if (s.configured) return <Badge variant="secondary">示例数据</Badge>
    return <Badge variant="outline">未设置</Badge>
  }

  return (
    <PageFrame>
      <PageShell
        title="工作台"
        desc="你的任务、报告与数据生成情况。还没有数据的模块会保持空态。"
        actions={
          <Button size="sm" variant="secondary" asChild>
            <a href="/workbench" data-link="">
              <Sparkles />
              去 AI 助手
            </a>
          </Button>
        }
      >
        {needsKey ? (
          <Alert variant="warning" className="mt-4">
            <TriangleAlert />
            <AlertTitle>
              <strong>还差一步：配置你自己的 API Key。</strong>
            </AlertTitle>
            <div className="col-start-2 mt-1 text-xs leading-relaxed">
              激浪不提供模型额度，竞品分析与 Listing 生成都用你自己的 Key。
              Key 加密保存，只用于你的账号，随时可以删除。
              <a className="underline underline-offset-2" href="/settings" data-link="">
                去「设置 → 模型与密钥」
              </a>
              配置后回到这里发起第一个任务。想先看效果？
              <a className="underline underline-offset-2" href="/workbench" data-link="">
                去 AI 助手用示例数据跑一次
              </a>
              。
            </div>
          </Alert>
        ) : null}

        {/* KPI：一个容器 + 发丝分隔线，比五张独立卡片干净 */}
        <div className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border xl:grid-cols-5">
          <Kpi label="任务总数" value={stats.total || 0} note="含全部状态" />
          <Kpi label="进行中" value={stats.running || 0} note="运行中与排队中" />
          <Kpi label="报告" value={stats.reports || 0} note="竞品分析结果" />
          <Kpi label="Listing" value={stats.listings || 0} note="草稿与版本" />
          <Kpi label="待审批" value={stats.awaiting_approval || 0} note="需要人工确认" />
        </div>

        {shop ? <ShopOverview m={shop} /> : null}

        <div className="mt-4 grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <Card className="gap-0" data-dash-card>
            <SectionHead
              title="任务趋势"
              desc="近 14 天每天新建的任务数"
              action={
                <Button size="sm" variant="ghost" asChild>
                  <a href="/tasks" data-link="">
                    查看全部
                  </a>
                </Button>
              }
            />
            <CardContent className="pt-3">
              {/* 全 0 时不画贴底零线（原实现的纪律）：交给组件走空态 */}
              <div id="dash-trend">
                <Suspense
                  fallback={
                    <div style={{ height: 148 }}>
                      <Skeleton className="h-full w-full" />
                    </div>
                  }
                >
                  <TrendChart
                    series={
                      hasTrend
                        ? (data.daily_tasks || []).map((d) => ({
                            date: String(d.date || ''),
                            value: Number(d.count) || 0,
                          }))
                        : []
                    }
                    height={148}
                    label={`近 ${(data.daily_tasks || []).length} 天任务数量趋势`}
                    emptyText="这 14 天还没有新建任务"
                  />
                </Suspense>
              </div>
            </CardContent>
          </Card>

          <Card className="gap-0" data-dash-card>
            <SectionHead title="最近报告" desc="竞品分析结果" />
            {reports.length ? (
              <div className="mt-2 flex flex-col p-2">
                {reports.map((r, i) => {
                  const body = (
                    <>
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate text-[13px] text-foreground">
                          {r.product_name}
                        </span>
                        <span className="truncate text-[11px] text-muted-foreground">
                          {labelPlatform(r.platform)} · {labelSite(r.marketplace)}
                        </span>
                      </span>
                      {r.is_demo ? (
                        <Badge
                          variant="warning"
                          title="示例数据，不是你店铺的真实经营数据"
                        >
                          示例
                        </Badge>
                      ) : null}
                      <span className="shrink-0 text-[11px] text-faint">{fmtTime(r.created_at)}</span>
                    </>
                  )
                  // 报告没有独立页面了，点进产出它的那条任务看结果
                  return r.task_id ? (
                    <a
                      className="flex items-center gap-2.5 rounded-sm px-2 py-2 transition-colors hover:bg-accent"
                      href={`/tasks/${r.task_id}`}
                      data-link=""
                      key={i}
                    >
                      {body}
                    </a>
                  ) : (
                    <div className="flex items-center gap-2.5 px-2 py-2" key={i}>
                      {body}
                    </div>
                  )
                })}
              </div>
            ) : (
              <EmptyBlock
                compact
                icon={FileText}
                title="还没有报告"
                desc="生成第一份竞品分析后，报告会出现在这里。"
              />
            )}
          </Card>
        </div>

        <div className="mt-4 grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <Card className="gap-0" data-dash-card>
            <SectionHead
              title="近期任务"
              desc="最近的执行记录"
              action={
                tasks.length ? (
                  <Button size="sm" variant="ghost" asChild>
                    <a href="/tasks" data-link="">
                      查看全部
                    </a>
                  </Button>
                ) : null
              }
            />
            {tasks.length ? (
              <div className="mt-3 overflow-hidden rounded-b-lg border-t border-border" data-task-table>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>任务</TableHead>
                      <TableHead>类型</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>创建</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tasks.map((t, i) => (
                      <TableRow key={t.task_id || i}>
                        <TableCell>
                          <a
                            className="font-medium hover:text-primary"
                            href={`/tasks/${t.task_id}`}
                            data-link=""
                          >
                            {t.title}
                          </a>
                        </TableCell>
                        <TableCell className="text-muted-foreground">{taskType(t.type)}</TableCell>
                        <TableCell>
                          <StatusBadge status={t.status} />
                        </TableCell>
                        <TableCell className="text-[11px] whitespace-nowrap text-faint">
                          {fmtTime(t.created_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <EmptyBlock
                icon={ListChecks}
                title="还没有任务"
                desc="在 AI 助手描述一个业务目标，Agent 会依次完成竞品分析、数据核对与 Listing 生成。"
                actions={
                  <>
                    <Button size="sm" asChild>
                      <a href="/workbench" data-link="">
                        发起第一个任务
                      </a>
                    </Button>
                    <Button size="sm" variant="outline" asChild>
                      <a href="/workbench" data-link="">
                        去 AI 助手描述目标
                      </a>
                    </Button>
                  </>
                }
              />
            )}
          </Card>

          <Card className="gap-0" data-dash-card>
            <SectionHead title="最近 Listing" />
            {listings.length ? (
              <div className="mt-2 flex flex-col p-2">
                {listings.map((l, i) => {
                  const body = (
                    <>
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate text-[13px] text-foreground">
                          {l.product_name}
                        </span>
                        <span className="truncate text-[11px] text-muted-foreground">
                          {labelSite(l.marketplace)} · {labelLanguage(l.language)}
                        </span>
                      </span>
                      <span className="shrink-0 text-[11px] text-faint">{fmtTime(l.created_at)}</span>
                    </>
                  )
                  return l.task_id ? (
                    <a
                      className="flex items-center gap-2.5 rounded-sm px-2 py-2 transition-colors hover:bg-accent"
                      href={`/tasks/${l.task_id}`}
                      data-link=""
                      key={i}
                    >
                      {body}
                    </a>
                  ) : (
                    <div className="flex items-center gap-2.5 px-2 py-2" key={i}>
                      {body}
                    </div>
                  )
                })}
              </div>
            ) : (
              <EmptyBlock
                compact
                icon={ScrollText}
                title="还没有 Listing 草稿"
                desc="基于已确认的商品事实生成，并自动做事实对齐质检。"
                actions={
                  <Button size="sm" variant="outline" asChild>
                    <a href="/workbench" data-link="">
                      去生成
                    </a>
                  </Button>
                }
              />
            )}
          </Card>
        </div>

        {sources.length ? (
          <Card className="mt-4 gap-0" data-dash-card>
            <SectionHead
              title="数据源状态"
              desc="每个数据域现在用的是哪一份数据"
              action={
                <Button size="sm" variant="ghost" asChild>
                  <a href="/settings#data" data-link="">
                    数据源设置
                  </a>
                </Button>
              }
            />
            <CardContent className="mt-3 flex flex-col gap-2 pt-0">
              {sources.map((s, i) => (
                <div
                  className="flex items-center gap-3 rounded-md border border-border px-3 py-2"
                  key={i}
                >
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-[13px] font-medium text-foreground">
                      {s.label}
                    </span>
                    <span className="truncate text-[11px] text-muted-foreground">
                      {s.detail || ''}
                    </span>
                  </span>
                  <span className="shrink-0">{badgeFor(s)}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        ) : null}
      </PageShell>
    </PageFrame>
  )
}
