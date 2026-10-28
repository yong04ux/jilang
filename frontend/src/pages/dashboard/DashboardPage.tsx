/**
 * 工作台 —— 从旧 `js/pages/dashboard.js` 迁移。
 *
 * 版式：KPI 行 + 经营概览 + 任务趋势图 + 最近报告 / 近期任务 / 最近 Listing + 数据源状态。
 *
 * 三条纪律（原注释保留）：
 *  - 所有数字来自 /api/dashboard 与 /api/marketplace/metrics，前端不推算任何指标；
 *  - 还没有数据的模块保持空态，不显示推测性指标；
 *  - 趋势全 0 时不画贴底零线 —— 那是「空壳图」，什么信息都没给。
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { getHealth } from '@/features/health/health'
import { fmtTime } from '@/lib/ui'
import { language as labelLanguage, platform as labelPlatform, site as labelSite, taskType } from '@/lib/labels'
import { Icon } from '@/components/Icon'
import { PageFrame, PageShell } from '@/components/PageShell'
import { StatusBadge } from '@/components/StatusBadge'

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
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{String(value)}</div>
      {note ? <div className="kpi-note">{note}</div> : null}
    </div>
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
      return <span className="st-metric-delta is-flat">无对比</span>
    }
    const n = Number(value)
    if (Math.abs(n) < 0.05) return <span className="st-metric-delta is-flat">持平</span>
    return (
      <span className={`st-metric-delta ${n > 0 ? 'is-good' : 'is-bad'}`}>
        {n > 0 ? '▲' : '▼'} {Math.abs(n).toFixed(1)}%
        <span style={{ opacity: 0.6 }}> 环比</span>
      </span>
    )
  }

  const cell = (key: string, label: string, format: (v: unknown) => string) => {
    const item = sm[key] || { value: 0, changePct: null }
    return (
      <div className="st-metric" key={key}>
        <span className="st-metric-label">{item.label || label}</span>
        <span className="st-metric-value">{format(item.value)}</span>
        {deltaTag(item.changePct)}
      </div>
    )
  }

  return (
    <div className="card" style={{ marginTop: 'var(--sp-4)' }}>
      <div className="card-head">
        <div>
          <div className="card-title">经营概览</div>
          <div className="card-sub">
            这家店近 {m.days || 30} 天的销售情况，与上一个等长周期对比
          </div>
        </div>
        <a className="btn btn-quiet btn-sm" href="/stores" data-link="">
          经营看板
        </a>
      </div>
      <div className="card-body">
        <div className="st-metrics">
          {cell('salesAmount', '销售额', money)}
          {cell('unitCount', '销量', num)}
          {cell('orderCount', '订单量', num)}
          {cell('aov', '客单价', money)}
        </div>
      </div>
    </div>
  )
}

function EmptyBlock({
  iconName,
  title,
  desc,
  actions,
  padding,
}: {
  iconName: string
  title: string
  desc: string
  actions?: React.ReactNode
  padding?: string
}) {
  return (
    <div className="empty" style={padding ? { padding } : undefined}>
      <span className="empty-icon">
        <Icon name={iconName} />
      </span>
      <p className="empty-title">{title}</p>
      <p className="empty-desc">{desc}</p>
      {actions ? <div className="empty-actions">{actions}</div> : null}
    </div>
  )
}

/* ------------------------------------------------------------------ 页面 */

export function DashboardPage() {
  const [view, setView] = useState<View>({ kind: 'loading' })
  const [nonce, setNonce] = useState(0)
  const trendRef = useRef<HTMLDivElement>(null)

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

  // 任务趋势图：数据拿到后再画，容器宽度才能实测
  useEffect(() => {
    const host = trendRef.current
    if (!host || view.kind !== 'ready') return
    const rows = view.data.daily_tasks || []
    const hasTrend = rows.some((d) => Number(d.count) > 0)
    if (!hasTrend) {
      host.innerHTML = '<div class="cp-chart-empty">这 14 天还没有新建任务</div>'
      return
    }
    host.innerHTML = ''
    window.CPChart?.line(host, {
      series: rows.map((d) => ({ date: d.date, value: d.count })),
      format: 'number',
      height: 148,
      label: '近 ' + rows.length + ' 天任务数量趋势',
    })
  }, [view])

  if (view.kind === 'loading') {
    return (
      <PageFrame>
        <div className="page">
          <div className="page-inner">
            <div className="skeleton" style={{ height: 92, marginBottom: 24 }} />
            <div className="skeleton" style={{ height: 220, marginBottom: 24 }} />
          </div>
        </div>
      </PageFrame>
    )
  }

  if (view.kind === 'error') {
    return (
      <PageFrame>
        <div className="page">
          <div className="page-inner">
            <div className="page-head">
              <div>
                <h1 className="page-title">工作台</h1>
              </div>
            </div>
            <div className="callout callout-danger">
              <Icon name="alert" />
              <div>
                <strong>加载失败</strong>
                <br />
                {view.message}
                <div className="mt-2">
                  <button
                    type="button"
                    className="btn btn-sm"
                    data-retry=""
                    onClick={() => setNonce((n) => n + 1)}
                  >
                    重试
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </PageFrame>
    )
  }

  const { data, shop, needsKey } = view
  const stats = data.stats || {}
  const tasks = data.recent_tasks || []
  const reports = data.recent_reports || []
  const listings = data.recent_listings || []
  const sources = data.data_sources || []

  return (
    <PageFrame>
      <PageShell
        title="工作台"
        desc="你的任务、报告与数据生成情况。还没有数据的模块会保持空态。"
        actions={
          <a className="btn btn-secondary btn-sm" href="/workbench" data-link="">
            <Icon name="sparkles" />
            去 AI 助手
          </a>
        }
      >
        {needsKey ? (
          <div className="callout callout-warn mt-4">
            <Icon name="alert" />
            <span>
              <strong>还差一步：配置你自己的 API Key。</strong>
              激浪不提供模型额度，竞品分析与 Listing 生成都用你自己的 Key。
              Key 加密保存，只用于你的账号，随时可以删除。
              <a href="/settings" data-link="">
                去「设置 → 模型与密钥」
              </a>
              配置后回到这里发起第一个任务。 想先看效果？
              <a href="/workbench" data-link="">
                去 AI 助手用示例数据跑一次
              </a>
              。
            </span>
          </div>
        ) : null}

        <div className="card dash-kpi">
          <div className="kpi-row">
            <Kpi label="任务总数" value={stats.total || 0} note="含全部状态" />
            <Kpi label="进行中" value={stats.running || 0} note="运行中与排队中" />
            <Kpi label="报告" value={stats.reports || 0} note="竞品分析结果" />
            <Kpi label="Listing" value={stats.listings || 0} note="草稿与版本" />
            <Kpi label="待审批" value={stats.awaiting_approval || 0} note="需要人工确认" />
          </div>
        </div>

        {shop ? <ShopOverview m={shop} /> : null}

        <div className="dash-grid">
          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">任务趋势</div>
                <div className="card-sub">近 14 天每天新建的任务数</div>
              </div>
              <a className="btn btn-quiet btn-sm" href="/tasks" data-link="">
                查看全部
              </a>
            </div>
            <div className="card-body">
              <div id="dash-trend" ref={trendRef} />
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">最近报告</div>
                <div className="card-sub">竞品分析结果</div>
              </div>
            </div>
            <div className="list">
              {reports.length ? (
                reports.map((r, i) => {
                  const body = (
                    <>
                      <span className="grow">
                        <span className="t-sm">{r.product_name}</span>
                        <span className="t-xs">
                          {labelPlatform(r.platform)} · {labelSite(r.marketplace)}
                        </span>
                      </span>
                      {r.is_demo ? (
                        <span className="mock-flag" title="示例数据，不是你店铺的真实经营数据">
                          示例
                        </span>
                      ) : null}
                      <span className="t-xs t-faint">{fmtTime(r.created_at)}</span>
                    </>
                  )
                  // 报告没有独立页面了，点进产出它的那条任务看结果
                  return r.task_id ? (
                    <a className="list-row" href={`/tasks/${r.task_id}`} data-link="" key={i}>
                      {body}
                    </a>
                  ) : (
                    <div className="list-row" key={i}>
                      {body}
                    </div>
                  )
                })
              ) : (
                <EmptyBlock
                  iconName="file"
                  title="还没有报告"
                  desc="生成第一份竞品分析后，报告会出现在这里。"
                  padding="var(--sp-5)"
                />
              )}
            </div>
          </div>
        </div>

        <div className="dash-grid mt-4" style={{ marginTop: 'var(--sp-5)' }}>
          <div className="card">
            <div className="card-head">
              <div>
                <div className="card-title">近期任务</div>
                <div className="card-sub">最近的执行记录</div>
              </div>
              {tasks.length ? (
                <a className="btn btn-quiet btn-sm" href="/tasks" data-link="">
                  查看全部
                </a>
              ) : null}
            </div>
            {tasks.length ? (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>任务</th>
                      <th>类型</th>
                      <th>状态</th>
                      <th className="num">创建</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tasks.map((t, i) => (
                      <tr key={t.task_id || i}>
                        <td>
                          <a href={`/tasks/${t.task_id}`} data-link="">
                            <strong>{t.title}</strong>
                          </a>
                        </td>
                        <td className="t-muted">{taskType(t.type)}</td>
                        <td>
                          <StatusBadge status={t.status} />
                        </td>
                        <td className="t-muted num">{fmtTime(t.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyBlock
                iconName="tasks"
                title="还没有任务"
                desc="在 AI 助手描述一个业务目标，Agent 会依次完成竞品分析、数据核对与 Listing 生成。"
                actions={
                  <>
                    <a className="btn btn-primary btn-sm" href="/workbench" data-link="">
                      发起第一个任务
                    </a>
                    <a className="btn btn-sm" href="/workbench" data-link="">
                      去 AI 助手描述目标
                    </a>
                  </>
                }
              />
            )}
          </div>

          <div className="col gap-4">
            <div className="card">
              <div className="card-head">
                <div className="card-title">最近 Listing</div>
              </div>
              <div className="list">
                {listings.length ? (
                  listings.map((l, i) => {
                    const body = (
                      <>
                        <span className="grow">
                          <span className="t-sm">{l.product_name}</span>
                          <span className="t-xs">
                            {labelSite(l.marketplace)} · {labelLanguage(l.language)}
                          </span>
                        </span>
                        <span className="t-xs t-faint">{fmtTime(l.created_at)}</span>
                      </>
                    )
                    return l.task_id ? (
                      <a className="list-row" href={`/tasks/${l.task_id}`} data-link="" key={i}>
                        {body}
                      </a>
                    ) : (
                      <div className="list-row" key={i}>
                        {body}
                      </div>
                    )
                  })
                ) : (
                  <EmptyBlock
                    iconName="listing"
                    title="还没有 Listing 草稿"
                    desc="基于已确认的商品事实生成，并自动做事实对齐质检。"
                    padding="var(--sp-5)"
                    actions={
                      <a className="btn btn-sm" href="/workbench" data-link="">
                        去生成
                      </a>
                    }
                  />
                )}
              </div>
            </div>
          </div>
        </div>

        {sources.length ? (
          <div className="card mt-4" style={{ marginTop: 'var(--sp-5)' }}>
            <div className="card-head">
              <div>
                <div className="card-title">数据源状态</div>
                <div className="card-sub">每个数据域现在用的是哪一份数据</div>
              </div>
              <a className="btn btn-quiet btn-sm" href="/settings#data" data-link="">
                数据源设置
              </a>
            </div>
            <div className="card-body">
              {sources.map((s, i) => {
                let badge: React.ReactNode
                if (s.mode === 'upload') badge = <span className="badge">你的文件</span>
                else if (s.configured && s.mode === 'live')
                  badge = <span className="badge badge-ok">已连接</span>
                else if (s.configured) badge = <span className="badge">示例数据</span>
                else badge = <span className="badge">未设置</span>
                return (
                  <div className="src-row" key={i}>
                    <span className="grow">
                      <span className="src-name">{s.label}</span>
                      <span className="src-desc">{s.detail || ''}</span>
                    </span>
                    <span className="src-flags">{badge}</span>
                  </div>
                )
              })}
            </div>
          </div>
        ) : null}
      </PageShell>
    </PageFrame>
  )
}
