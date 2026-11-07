/**
 * 工作台（/dashboard）：首屏门面。
 *
 * 三条纪律：
 *  - 所有数字来自 /api/dashboard 与 /api/marketplace/metrics，前端不推算任何指标；
 *  - 还没有数据的模块保持空态，不显示推测性指标；
 *  - 趋势全 0 时不画贴底零线 —— 那是「空壳图」，什么信息都没给。
 *
 * 视觉：反调印刷 —— 巨型指标 + 跨列不等宽的阶梯反网格 + 硬框面板 + 校样清单。
 * 结构：KPI 带 / 经营概览 / 任务趋势 / 最近报告 / 近期任务 / 最近 Listing / 数据源状态。
 *
 * 趋势图用 `lib/charts.ts` 的手写内联 SVG：零依赖，28 项字节级对照；换 Recharts 会给
 * 本页 chunk 增加约 90 KB，收益只有可交互 tooltip，要用时单独评估体积。
 * `#dash-trend` 是 CPChart 的宿主，也是验收脚本钩子，别改。
 *
 * 验收脚本钩子走语义属性：`[data-kpi]` / `[data-kpi-label]` / `[data-dash-card]` /
 * `[data-task-table]`；空图占位符 `.cp-chart-empty` 由图表组件注入，保留类名。
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
import { Badge } from '@/components/ui/badge'
import { Alert, AlertTitle } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
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

/** 巨型指标 / 阶梯格子：跨列不等宽 + margin-top 错位，反网格的最小单元 */
function Tile({
  label,
  value,
  note,
  span = 3,
  stagger,
  giant,
  stamp,
}: {
  label: string
  value: unknown
  note?: string
  span?: 2 | 3 | 4 | 5
  stagger?: 14 | 20 | 30 | 40
  giant?: boolean
  stamp?: { text: string; tone?: 'danger' | 'done' }
}) {
  return (
    <div
      className={cn(
        'dtile',
        giant && 'dtile--giant',
        !giant && `dtile--w${span}`,
        stagger && `dtile--st${stagger}`,
      )}
      data-kpi
    >
      {stamp ? (
        <span className={cn('dtile-stamp', stamp.tone && `is-${stamp.tone}`)}>{stamp.text}</span>
      ) : null}
      <div className="dtile-lab" data-kpi-label>
        {label}
      </div>
      <div className="dtile-num">{String(value)}</div>
      {note ? <div className="dtile-sub">{note}</div> : null}
    </div>
  )
}

/** 硬框面板：表头带 + 内容区；data-dash-card 是验收锚点，恒定带上 */
function PressPanel({
  title,
  meta,
  action,
  className,
  bodyClass,
  children,
}: {
  title: string
  meta?: string
  action?: React.ReactNode
  className?: string
  bodyClass?: string
  children: React.ReactNode
}) {
  return (
    <section className={cn('press-panel', className)} data-dash-card="">
      <div className="ph">
        <span className="ph-title">{title}</span>
        {meta ? <span className="ph-meta">{meta}</span> : null}
        {action ? <span className="ph-act">{action}</span> : null}
      </div>
      <div className={cn('pb', bodyClass)}>{children}</div>
    </section>
  )
}

/** 空态：图标块 + 一句结论 + 一句下一步，不写「暂无数据」这种废话 */
function EmptyBlock({
  icon: Icon,
  title,
  desc,
  actions,
}: {
  icon: typeof FileText
  title: string
  desc: string
  actions?: React.ReactNode
}) {
  return (
    <div className="dash-empty">
      <span className="de-box">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <p className="de-title">{title}</p>
      <p className="de-desc">{desc}</p>
      {actions ? <div className="de-act">{actions}</div> : null}
    </div>
  )
}

/** 校样清单行：序号 + 圆点 + 名称/元信息 + 时间；有 task_id 才是链接 */
function ProofRow({
  index,
  name,
  meta,
  time,
  href,
  demo,
  image,
}: {
  index: number
  name: string
  meta: string
  time: string
  href?: string
  demo?: boolean
  image?: string | null
}) {
  const inner = (
    <>
      <span className="proof-ix">{String(index + 1).padStart(2, '0')}</span>
      {image ? (
        <img className="proof-thumb" src={image} alt="" loading="lazy" width={40} height={40} />
      ) : (
        <span className={cn('proof-dot', demo && 'is-demo')} aria-hidden="true" />
      )}
      <span className="proof-main">
        <span className="proof-nm">{name}</span>
        <span className="proof-mt">{meta}</span>
      </span>
      <span className="proof-tm">{time}</span>
    </>
  )
  return href ? (
    <a className="proof" href={href} data-link="">
      {inner}
    </a>
  ) : (
    <div className="proof">{inner}</div>
  )
}

/* 经营概览：4 个核心指标，来自 /api/marketplace/metrics，点进去是完整经营看板 */
function ShopOverview({ m, className }: { m: Dict; className?: string }) {
  const sm = m.salesMetrics || {}
  const currency = m.currency || 'USD'
  const chart = window.CPChart
  const money = (v: unknown) => (chart ? chart.moneyFull(v, currency) : '—')
  const num = (v: unknown) => (chart ? chart.num(v) : '—')

  const deltaTag = (value: unknown) => {
    if (value === null || value === undefined || !isFinite(Number(value))) {
      return <div className="ov-delta flat">无对比数据</div>
    }
    const n = Number(value)
    if (Math.abs(n) < 0.05) return <div className="ov-delta flat">基本持平</div>
    return (
      <div className={cn('ov-delta', n > 0 ? 'up' : 'down')}>
        {n > 0 ? '▲' : '▼'} {Math.abs(n).toFixed(1)}%
        <span className="opacity-70"> 环比</span>
      </div>
    )
  }

  const cell = (key: string, label: string, format: (v: unknown) => string) => {
    const item = sm[key] || { value: 0, changePct: null }
    return (
      <div className="ov-cell" key={key}>
        <div className="ov-lab">{item.label || label}</div>
        <div className="ov-val">{format(item.value)}</div>
        {deltaTag(item.changePct)}
      </div>
    )
  }

  return (
    <PressPanel
      className={cn('dash-ov', className)}
      title="经营概览"
      meta={`近 ${m.days || 30} 天`}
      action={
        <a className="ph-all" href="/stores" data-link="">
          经营看板
        </a>
      }
      bodyClass="pb-tight"
    >
      <div className="ov-grid">
        {cell('salesAmount', '销售额', money)}
        {cell('unitCount', '销量', num)}
        {cell('orderCount', '订单量', num)}
        {cell('aov', '客单价', money)}
      </div>
      <div className="ov-foot">这家店近 {m.days || 30} 天的销售，与上一个等长周期对比。</div>
    </PressPanel>
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
        <PageShell title="工作台">
          <div className="dash-root">
            <div className="dash-tiles">
              <div className="dtile dtile--giant" data-kpi>
                <Skeleton className="h-3 w-20" />
                <Skeleton className="mt-2 h-20 w-28" />
              </div>
              {[0, 1, 2, 3].map((i) => (
                <div className="dtile dtile--w2" key={i} data-kpi>
                  <Skeleton className="h-3 w-14" />
                  <Skeleton className="mt-2 h-12 w-12" />
                </div>
              ))}
            </div>
            <div className="dash-grid">
              {[0, 1].map((i) => (
                <div className="press-panel" key={i} data-dash-card="">
                  <div className="ph">
                    <Skeleton className="h-3.5 w-24" />
                  </div>
                  <div className="pb">
                    <Skeleton className="h-36 w-full" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </PageShell>
      </PageFrame>
    )
  }

  if (view.kind === 'error') {
    return (
      <PageFrame>
        <PageShell title="工作台">
          <div className="dash-root">
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
          </div>
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
  const awaiting = Number(stats.awaiting_approval) || 0

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
        actions={
          <Button size="sm" variant="secondary" asChild>
            <a href="/workbench" data-link="">
              <Sparkles />
              去 AI 助手
            </a>
          </Button>
        }
      >
        <div className="dash-root">
          {needsKey ? (
            <div className="dash-alert" role="alert">
              <span className="al-no" aria-hidden="true">
                !
              </span>
              <div className="al-body">
                <strong className="al-strong">还差一步：配置你自己的 API Key。</strong>
                <div className="al-p">
                  激浪不提供模型额度，竞品分析与 Listing 生成都用你自己的 Key。Key 加密保存，只用于你的账号，随时可以删除。
                  <a className="underline underline-offset-2" href="/settings" data-link="">
                    去「设置 → 模型与密钥」
                  </a>
                  配置后回到这里发起第一个任务。想先看效果？
                  <a className="underline underline-offset-2" href="/workbench" data-link="">
                    去 AI 助手用示例数据跑一次
                  </a>
                  。
                </div>
              </div>
            </div>
          ) : null}

          {/* 反网格 KPI 带：巨型首格 + 不等宽 + 阶梯错位，全部数字来自服务端 */}
          <div className="dash-tiles">
            <Tile giant label="任务总数" value={stats.total || 0} note="含全部状态 · 均来自服务端" />
            <Tile span={2} stagger={20} label="进行中" value={stats.running || 0} note="运行中与排队中" />
            <Tile span={2} stagger={40} label="报告" value={stats.reports || 0} note="竞品分析结果" />
            <Tile span={2} stagger={14} label="Listing" value={stats.listings || 0} note="草稿与版本" />
            <Tile
              span={2}
              stagger={30}
              label="待审批"
              value={awaiting}
              note="需要人工确认"
              stamp={{ text: awaiting > 0 ? '需处理' : '无积压', tone: awaiting > 0 ? 'danger' : 'done' }}
            />
          </div>

          {shop ? <ShopOverview m={shop} className="c12" /> : null}

          <div className="dash-grid">
            <PressPanel
              className="c7"
              title="任务趋势"
              meta="近 14 天 · 每天新建"
              action={
                <a className="ph-all" href="/tasks" data-link="">
                  查看全部
                </a>
              }
            >
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
                    emptyText="这 14 天还没有新建任务 · 不画假折线"
                  />
                </Suspense>
              </div>
            </PressPanel>

            <PressPanel className="c5 stagger" title="最近报告" meta="竞品分析">
              {reports.length ? (
                reports.map((r, i) => (
                  <ProofRow
                    key={i}
                    index={i}
                    name={String(r.product_name ?? '')}
                    meta={`${labelPlatform(r.platform)} · ${labelSite(r.marketplace)}${r.is_demo ? ' · 示例' : ''}`}
                    time={fmtTime(r.created_at)}
                    demo={Boolean(r.is_demo)}
                    image={r.image}
                    href={r.task_id ? `/tasks/${r.task_id}` : undefined}
                  />
                ))
              ) : (
                <EmptyBlock
                  icon={FileText}
                  title="还没有报告"
                  desc="生成第一份竞品分析后，报告会出现在这里。"
                />
              )}
            </PressPanel>

            <PressPanel
              className="c8"
              title="近期任务"
              meta="最近执行记录"
              bodyClass="pb-tight"
              action={
                tasks.length ? (
                  <a className="ph-all" href="/tasks" data-link="">
                    查看全部
                  </a>
                ) : null
              }
            >
              {tasks.length ? (
                <div className="table-wrap tasks-table" data-task-table>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>任务</th>
                        <th className="col-optional">类型</th>
                        <th>状态</th>
                        <th className="num col-optional">创建</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tasks.map((t, i) => (
                        <tr key={t.task_id || i} data-status={t.status}>
                          <td>
                            <a href={`/tasks/${t.task_id}`} data-link="">
                              {t.title}
                            </a>
                          </td>
                          <td className="col-optional t-muted">{taskType(t.type)}</td>
                          <td>
                            <StatusBadge status={t.status} />
                          </td>
                          <td className="num col-optional t-muted">{fmtTime(t.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
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
            </PressPanel>

            <PressPanel className="c4 stagger" title="最近 Listing" meta="草稿与版本" data-dash-card="">
              {listings.length ? (
                listings.map((l, i) => (
                  <ProofRow
                    key={i}
                    index={i}
                    name={String(l.product_name ?? '')}
                    meta={`${labelSite(l.marketplace)} · ${labelLanguage(l.language)}`}
                    time={fmtTime(l.created_at)}
                    href={l.task_id ? `/tasks/${l.task_id}` : undefined}
                  />
                ))
              ) : (
                <EmptyBlock
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
            </PressPanel>

            {sources.length ? (
              <PressPanel
                className="c12"
                title="数据源状态"
                meta="每个数据域当前用的哪份数据"
                data-dash-card=""
                action={
                  <a className="ph-all" href="/settings#data" data-link="">
                    数据源设置
                  </a>
                }
              >
                {sources.map((s, i) => (
                  <div className="proof" key={i}>
                    <span className="proof-main">
                      <span className="proof-nm">{s.label}</span>
                      {s.detail ? <span className="proof-mt">{s.detail}</span> : null}
                    </span>
                    <span className="proof-tm">{badgeFor(s)}</span>
                  </div>
                ))}
              </PressPanel>
            ) : null}
          </div>

          {/* 巨型描边排版收尾：真实任务总数，治短页面死白 */}
          <div className="bigfill">
            <span className="bf-n">{String(stats.total || 0).padStart(2, '0')}</span>
            <span className="bf-t">
              条任务记录
              <em>状态与数字均来自服务端</em>
            </span>
          </div>
        </div>
      </PageShell>
    </PageFrame>
  )
}
