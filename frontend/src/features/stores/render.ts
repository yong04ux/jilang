/**
 * 店铺经营助手的渲染层：表格与卡片产出 HTML 字符串。
 *
 * 为什么是字符串而不是 JSX：里面全是表格式排版（`st-table` 七列、缩略信息、
 * 行内展开），改写成 JSX 只会增加面积而不改变 DOM 结果；`.st-*` 类名与表格结构
 * 也是验收脚本的锚点。React 负责外壳、状态、事件与图表生命周期。
 *
 * 数据纪律：
 *  - 所有数字来自 /api/marketplace/*，前端不造任何一个业绩指标；
 *  - 后端没给的维度就不出卡片，不摆空壳；
 *  - 示例店铺统一打「示例」徽标。
 */
import { esc, fmtTime, icon } from '@/lib/ui'
import {
  orderStatus,
  orderTone,
  platform as labelPlatform,
  returnStatus,
  returnTone,
  site as labelSite,
} from '@/lib/labels'

type Dict = Record<string, any>

/* ------------------------------------------------------------ 结构定义 */

export const TABS = [
  { key: 'authorize', label: '店铺授权', path: '/stores/authorize' },
  { key: 'dashboard', label: '经营看板', path: '/stores' },
  { key: 'product', label: '单品分析', path: '/stores/product' },
  { key: 'ledger', label: '经营明细', path: '/stores/ledger' },
] as const

export const RANGES = [
  { key: '1d', label: '今日' },
  { key: '7d', label: '近 7 天' },
  { key: '30d', label: '近 30 天' },
] as const

export const SEGMENTS = [
  { key: 'overview', label: '概览' },
  { key: 'orders', label: '订单' },
  { key: 'ads', label: '广告' },
  { key: 'inventory', label: '库存' },
  { key: 'aftersales', label: '售后' },
] as const

export const LEDGERS = [
  { key: 'listing', label: 'Listing' },
  { key: 'orders', label: '订单列表' },
  { key: 'aftersales', label: '售后订单' },
  { key: 'fba', label: '库存明细' },
] as const

export const HEAD: Record<string, { title: string; desc: string }> = {
  authorize: {
    title: '店铺授权',
    desc: '绑定店铺后，商品、订单与广告数据会同步过来。也可以先用示例店铺把整个流程走通。',
  },
  dashboard: {
    title: '经营看板',
    desc: '这家店最近一段时间的经营情况。每个数字都由订单与广告数据聚合得出。',
  },
  product: {
    title: '单品分析',
    desc: '挑一个商品，看它的销售走势、广告表现和库存风险。',
  },
  ledger: {
    title: '经营明细',
    desc: '按类型查看明细表，行可以展开看完整字段。',
  },
}

/* ------------------------------------------------------------ 小工具 */

export function money(value: unknown, currency?: string): string {
  return window.CPChart!.moneyFull(Number(value) || 0, currency)
}

export function num(value: unknown): string {
  const n = Number(value)
  if (!isFinite(n)) return '—'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 1 })
}

export function pctText(value: unknown): string {
  const n = Number(value)
  if (!isFinite(n)) return '—'
  return n.toFixed(2) + '%'
}

export function pill(text: unknown, tone?: string): string {
  return '<span class="st-pill st-pill--' + (tone || 'muted') + '">' + esc(text) + '</span>'
}

/**
 * 环比涨跌。inverse=true 用于成本类指标（ACOS / CPC 降才是好事）。
 * 上一窗口没有数据时显示破折号，不写成 0% —— 那是在编一个不存在的对比。
 */
export function delta(value: unknown, inverse?: boolean): string {
  if (value === null || value === undefined || !isFinite(Number(value))) {
    return '<span class="st-metric-delta is-flat">无对比</span>'
  }
  const n = Number(value)
  if (Math.abs(n) < 0.05) return '<span class="st-metric-delta is-flat">持平</span>'
  const up = n > 0
  const good = inverse ? !up : up
  return (
    '<span class="st-metric-delta ' + (good ? 'is-good' : 'is-bad') + '">' +
    (up ? '▲' : '▼') + ' ' + Math.abs(n).toFixed(1) +
    '%<span style="opacity:.6"> 环比</span></span>'
  )
}

export function metric(label: string, valueHtml: string, deltaHtml?: string): string {
  return (
    '<div class="st-metric">' +
    '<span class="st-metric-label">' + esc(label) + '</span>' +
    '<span class="st-metric-value">' + valueHtml + '</span>' +
    (deltaHtml || '') +
    '</div>'
  )
}

export function card(title: string | null, body: string, extra?: string | null, opts?: { flush?: boolean }): string {
  const options = opts || {}
  return (
    '<section class="st-card">' +
    (title
      ? '<header class="st-card-head"><div class="st-card-title">' +
        esc(title) + '</div>' +
        (extra ? '<div class="st-card-extra">' + extra + '</div>' : '') +
        '</header>'
      : '') +
    '<div class="st-card-body' + (options.flush ? ' st-card-body--flush' : '') + '">' +
    body +
    '</div></section>'
  )
}

type HeaderItem = string | { label: string; align?: 'right' }

export function table(headers: HeaderItem[], rows: string[], opts?: { empty?: string; maxHeight?: string }): string {
  const options = opts || {}
  const head = headers
    .map((item) => {
      const label = typeof item === 'string' ? item : item.label
      const align = typeof item === 'string' ? '' : item.align === 'right' ? ' class="num"' : ''
      return '<th' + align + '>' + esc(label) + '</th>'
    })
    .join('')
  const body = rows.length
    ? rows.join('')
    : '<tr><td colspan="' + headers.length + '"><div class="cp-chart-empty" style="min-height:96px">' +
      esc(options.empty || '这个时间范围内没有数据') + '</div></td></tr>'
  return (
    '<div class="st-table-wrap' + (options.maxHeight ? '" style="max-height:' + options.maxHeight + '' : '') + '">' +
    '<table class="st-table"><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table>' +
    '</div>'
  )
}

export function loading(text?: string): string {
  return (
    '<div class="st-loading">' +
    '<div class="skeleton skeleton-line" style="height:44px"></div>' +
    '<div class="skeleton skeleton-line" style="height:180px"></div>' +
    '<div class="skeleton skeleton-line" style="height:120px"></div>' +
    '</div>' +
    (text ? '<p class="t-xs t-muted mt-3">' + esc(text) + '</p>' : '')
  )
}

export function storeOptions(stores: Dict[], currentId: string): string {
  return stores
    .map(
      (item) =>
        '<option value="' + esc(item.connection_id) + '"' +
        (item.connection_id === currentId ? ' selected' : '') + '>' +
        esc(item.shop_name) + ' · ' + esc(item.marketplace) + '</option>',
    )
    .join('')
}

/* ------------------------------------------------------------ 页面骨架 */

export function shellHtml(view: string, actions: string, body: string): string {
  const head = HEAD[view] || HEAD.dashboard
  const tabs = TABS.map(
    (tab) =>
      '<a class="st-tab' + (tab.key === view ? ' is-active' : '') + '" href="' +
      tab.path + '" data-link' + (tab.key === view ? ' aria-current="page"' : '') + '>' +
      esc(tab.label) + '</a>',
  ).join('')
  return (
    '<div class="view"><div class="page page--store"><div class="page-inner">' +
    '<div class="page-head"><div><h1 class="page-title">' + esc(head.title) + '</h1>' +
    '<p class="page-desc">' + esc(head.desc) + '</p></div>' +
    '<div class="page-actions">' + (actions || '') + '</div></div>' +
    '<nav class="st-tabs" aria-label="店铺经营助手">' + tabs + '</nav>' +
    '<div id="st-stage">' + body + '</div>' +
    '</div></div></div>'
  )
}

/* ------------------------------------------------------ 未绑定店铺引导 */

export function step(index: number, title: string, desc: string): string {
  return (
    '<div class="st-step">' +
    '<span class="st-step-no">' + index + '</span>' +
    '<p class="st-step-title">' + esc(title) + '</p>' +
    '<p class="st-step-desc">' + esc(desc) + '</p>' +
    '</div>'
  )
}

export function unboundState(): string {
  return (
    card(
      '还没有绑定店铺',
      '<p class="t-sm t-muted" style="margin:0 0 14px">绑定之后，这里会显示这家店真实的商品、订单、广告与库存。' +
        '现在可以先加一个示例店铺，把整个流程走一遍。</p>' +
        '<div class="row gap-2"><button type="button" class="btn btn-primary btn-sm" id="st-unbound-add">' +
        icon('plus') + '添加示例店铺</button>' +
        '<a class="btn btn-sm btn-secondary" href="/data" data-link>去导入商品文件</a></div>',
    ) +
    '<div class="st-steps mt-3">' +
    step(1, '选择店铺', '选平台与站点，填一个你自己认得出来的店铺名。') +
    step(2, '确认站点', '一个店铺对应一个站点；多站点请分别绑定。') +
    step(3, '开始同步', '同步完成后，商品、订单与广告数据会在这里按日汇总。') +
    '</div>'
  )
}

/* ------------------------------------------------------------ 工具栏 */

export interface StoreCtx {
  view: string
  range: string
  segment: string
  ledger: string
  asin: string
  storeId: string
  stores: Dict[]
}

export function toolbar(ctx: StoreCtx, extra?: string): string {
  const rangeSeg = RANGES.map(
    (item) =>
      '<button type="button" data-range="' + item.key + '"' +
      (item.key === ctx.range ? ' class="is-active"' : '') + '>' + esc(item.label) + '</button>',
  ).join('')
  return (
    '<div class="st-toolbar">' +
    (ctx.stores.length
      ? '<span class="st-select"><select id="st-store" aria-label="选择店铺">' +
        storeOptions(ctx.stores, ctx.storeId) + '</select>' + icon('chevronDown') + '</span>'
      : '') +
    (extra || '') +
    '<div class="st-toolbar-right"><div class="st-seg" role="group" aria-label="时间范围">' +
    rangeSeg + '</div></div></div>'
  )
}

/* --------------------------------------------------- 子页：店铺授权 */

export function authorizeHtml(stores: Dict[], sources: Dict[]): string {
  const rows = stores.map((item) => {
    const summary = item.last_sync_summary || {}
    const counts: string[] = []
    if (summary.products) counts.push(summary.products + ' 个商品')
    if (summary.orders) counts.push(summary.orders + ' 笔订单')
    const sample = Boolean(item.is_demo) || item.mode === 'mock'
    return (
      '<tr>' +
      '<td><div class="st-cell-product"><div>' +
      '<strong style="color:var(--foreground)">' + esc(item.shop_name) + '</strong>' +
      '<small>' + esc(labelPlatform(item.platform)) + ' · ' + esc(labelSite(item.marketplace)) + '</small>' +
      '</div></div></td>' +
      '<td>' + (sample ? pill('示例店铺', 'brand') : pill('已连接', 'ok')) + '</td>' +
      '<td class="t-muted">' + (item.last_sync_at ? esc(fmtTime(item.last_sync_at)) : '还没同步过') + '</td>' +
      '<td class="t-muted">' + esc(counts.join(' · ') || '—') + '</td>' +
      '<td class="num">' +
      '<button type="button" class="btn btn-sm" data-sync="' + esc(item.connection_id) + '">同步</button>' +
      '</td></tr>'
    )
  })

  const sourceRows = sources.map((item) => {
    let tone = 'muted'
    let label = '未设置'
    if (item.mode === 'upload') {
      tone = 'muted'
      label = '你的文件'
    } else if (item.configured && item.mode === 'live') {
      tone = 'ok'
      label = '已连接'
    } else if (item.configured) {
      tone = 'brand'
      label = '示例数据'
    }
    return (
      '<tr><td>' + esc(item.label) + '</td>' +
      '<td class="t-muted">' + esc(item.detail || '') + '</td>' +
      '<td>' + pill(label, tone) + '</td>' +
      '<td class="t-muted">' + (item.last_sync_at ? esc(fmtTime(item.last_sync_at)) : '—') + '</td></tr>'
    )
  })

  return (
    card(
      '已绑定店铺',
      table(
        [{ label: '店铺' }, { label: '状态' }, { label: '最后同步' }, { label: '同步内容' }, { label: '操作', align: 'right' }],
        rows,
        { empty: '还没有绑定店铺' },
      ),
      stores.length ? stores.length + ' 个店铺' : '',
      { flush: true },
    ) +
    '<div id="st-form"></div>' +
    (sourceRows.length
      ? card(
          '各数据域的数据来源',
          table([{ label: '数据域' }, { label: '说明' }, { label: '来源' }, { label: '最后同步' }], sourceRows),
          null,
          { flush: true },
        )
      : '')
  )
}

export function createStoreFormHtml(platformList: Dict[], defaultPlatform: string, currentMarkets: string[]): string {
  return (
    '<form id="st-create" class="st-card" style="padding:16px;margin-top:12px">' +
    '<div class="st-card-title">添加示例店铺</div>' +
    '<p class="t-xs t-muted" style="margin:6px 0 0">示例店铺带一组固定的商品与订单，用来试用同步、看板与分析流程；' +
    '它不代表你的真实经营数据。</p>' +
    '<div class="grid-2 mt-3">' +
    '<label class="field"><span class="field-label">平台</span><select name="platform">' +
    platformList
      .map(
        (item) =>
          '<option value="' + esc(item.key) + '"' + (item.key === defaultPlatform ? ' selected' : '') + '>' +
          esc(item.label || item.key) + '</option>',
      )
      .join('') +
    '</select></label>' +
    '<label class="field"><span class="field-label">站点</span><select name="marketplace">' +
    currentMarkets.map((code) => '<option value="' + esc(code) + '">' + esc(labelSite(code)) + '</option>').join('') +
    '</select></label>' +
    '<label class="field field-span-2"><span class="field-label">店铺名称</span>' +
    '<input name="shop_name" required placeholder="例如 我的试用店铺" /></label>' +
    '</div>' +
    '<div class="row gap-2 mt-3">' +
    '<button type="submit" class="btn btn-primary btn-sm">添加</button>' +
    '<button type="button" class="btn btn-quiet btn-sm" id="st-cancel">取消</button>' +
    '</div></form>'
  )
}

/* --------------------------------------------------- 子页：经营看板 */

export function dashboardTodosHtml(data: Dict): string {
  const inventory = data.inventory || { totals: {} }
  const returns = data.returns || []
  const health = data.health || { items: [] }
  const pendingReturns = returns.filter((item: Dict) => item.status !== 'refunded').length

  const todos = [
    { label: '已断货 SKU', value: inventory.totals.outOfStock || 0, tone: 'danger', seg: 'inventory', note: '可售库存为 0' },
    { label: '库存偏低', value: inventory.totals.lowStock || 0, tone: 'warning', seg: 'inventory', note: '可售不足 15 件' },
    { label: '滞销 SKU', value: inventory.totals.slowMoving || 0, tone: 'warning', seg: 'inventory', note: '30 天无销量' },
    { label: '待处理售后', value: pendingReturns, tone: pendingReturns ? 'warning' : 'ok', seg: 'aftersales', note: '等待审核或处理' },
    { label: '违规警告', value: health.warnings || 0, tone: health.warnings ? 'warning' : 'ok', seg: '', note: '平台账户状态' },
    { label: '政策违规', value: health.policyViolations || 0, tone: health.policyViolations ? 'danger' : 'ok', seg: '', note: '平台账户状态' },
  ]

  const todoHtml = todos
    .map((item) => {
      const tag = item.seg ? 'button' : 'div'
      const attrs = item.seg ? ' type="button" data-seg="' + item.seg + '"' : ''
      return (
        '<' + tag + ' class="st-todo st-todo--' + item.tone + '"' + attrs + '>' +
        '<span>' + esc(item.label) + '</span>' +
        '<strong>' + item.value + '</strong>' +
        '<small>' + esc(item.note) + '</small>' +
        '</' + tag + '>'
      )
    })
    .join('')

  const segHtml = SEGMENTS.map(
    (item) =>
      '<button type="button" data-seg-key="' + item.key + '"' +
      (item.key === (data.__segment || 'overview') ? ' class="is-active"' : '') + '>' + esc(item.label) + '</button>',
  ).join('')

  return (
    card('待处理事项', '<div class="st-todos">' + todoHtml + '</div>', '') +
    '<div class="st-toolbar" style="margin:14px 0 12px">' +
    '<div class="st-seg" role="group" aria-label="看板分区">' + segHtml + '</div>' +
    '<div class="st-toolbar-right">' + (data.store?.is_demo ? pill('示例店铺', 'brand') : '') + '</div></div>' +
    '<div id="st-seg-body"></div>'
  )
}

export function segButtonsHtml(segment: string): string {
  return SEGMENTS.map(
    (item) =>
      '<button type="button" data-seg-key="' + item.key + '"' +
      (item.key === segment ? ' class="is-active"' : '') + '>' + esc(item.label) + '</button>',
  ).join('')
}

export function segmentBody(ctx: StoreCtx, data: Dict): string {
  const m = data.metrics || {}
  const currency = data.currency || m.currency
  const ads = data.ads || { metrics: {}, campaigns: [], topProducts: [] }
  const inventory = data.inventory || { totals: {}, items: [], agingTotals: {} }
  const returns = data.returns || []
  const health = data.health || { items: [] }

  if (ctx.segment === 'orders') return ordersSegment(m, currency, data.orders || [])
  if (ctx.segment === 'ads') return adsSegment(ads, currency)
  if (ctx.segment === 'inventory') return inventorySegment(inventory)
  if (ctx.segment === 'aftersales') return aftersalesSegment(returns, currency)
  return overviewSegment(m, ads, currency, health)
}

function overviewSegment(m: Dict, ads: Dict, currency: string, health: Dict): string {
  const sm = m.salesMetrics || {}
  const cell = (key: string, formatter: (v: unknown) => string, inverse?: boolean) => {
    const item = sm[key] || { value: 0, changePct: null }
    return metric(item.label || key, formatter(item.value), delta(item.changePct, inverse))
  }

  const core =
    cell('salesAmount', (v) => money(v, currency)) +
    cell('unitCount', num) +
    cell('orderCount', num) +
    cell('aov', (v) => money(v, currency)) +
    metric('广告花费', money(ads.metrics?.spend || 0, currency), '') +
    metric('ACOS', pctText(ads.metrics?.acos || 0), '')

  const trendLabels: Record<string, string> = { salesAmount: '销售额', unitCount: '销量', orderCount: '订单量' }
  const trendSwitch = ['salesAmount', 'unitCount', 'orderCount']
    .map(
      (key) =>
        '<button type="button" data-trend-key="' + key + '"' +
        (key === 'salesAmount' ? ' class="is-active"' : '') + '>' + trendLabels[key] + '</button>',
    )
    .join('')

  const daily = (m.salesTrend || [])
    .slice()
    .reverse()
    .map(
      (item: Dict) =>
        '<tr><td>' + esc(item.date) + '</td>' +
        '<td class="num">' + money(item.salesAmount, currency) + '</td>' +
        '<td class="num">' + num(item.unitCount) + '</td>' +
        '<td class="num">' + num(item.orderCount) + '</td></tr>',
    )

  const healthCells = (health.items || [])
    .map((item: Dict) => metric(item.label, esc(item.value), ''))
    .join('')

  return (
    card('核心指标', '<div class="st-metrics">' + core + '</div>', '对比上一个等长周期 · ' + esc(m.range)) +
    card('业绩走势', '<div id="st-trend"></div>',
      '<div class="st-seg" role="group" aria-label="走势指标">' + trendSwitch + '</div>') +
    card('按日明细',
      table(
        [{ label: '日期' }, { label: '销售额', align: 'right' }, { label: '销量', align: 'right' }, { label: '订单量', align: 'right' }],
        daily,
        { maxHeight: '300px', empty: '这个时间范围内没有出单记录' },
      ),
      m.days + ' 天', { flush: true }) +
    (healthCells
      ? card('店铺绩效', '<div class="st-metrics st-metrics--five">' + healthCells + '</div>', esc(health.sourceLabel || ''))
      : '')
  )
}

function ordersSegment(m: Dict, currency: string, orders: Dict[]): string {
  const regions = (m.regionDistribution || []).slice(0, 10).map(
    (item: Dict) =>
      '<tr><td>' + esc(labelSite(item.country) || item.country) + '</td>' +
      '<td class="num">' + num(item.orderCount) + '</td>' +
      '<td class="num">' + Number(item.share).toFixed(1) + '%</td></tr>',
  )
  return (
    '<div class="st-grid-2">' +
    card('地区订单分布',
      table([{ label: '地区' }, { label: '订单量', align: 'right' }, { label: '占比', align: 'right' }], regions,
        { empty: '窗口内没有地区订单' }),
      '窗口内 ' + num(m.orders) + ' 笔', { flush: true }) +
    card('下单时段分布', '<div id="st-hours"></div>', '当地时间 0-23 点') +
    '</div>' +
    card('订单列表', ordersTable(orders, currency),
      num(m.orders) + ' 笔订单' + (orders.length < m.orders ? '（展示最近 ' + orders.length + ' 笔）' : ''),
      { flush: true })
  )
}

function ordersTable(orders: Dict[], currency: string): string {
  const rows = (orders || []).map(
    (order) =>
      '<tr><td>' + esc(order.order_id) + '</td>' +
      '<td>' + esc(order.product_name || order.sku || '—') + '</td>' +
      '<td class="num">' + num(order.quantity) + '</td>' +
      '<td class="num">' + money(order.amount, currency) + '</td>' +
      '<td>' + pill(orderStatus(order.status), orderTone(order.status)) + '</td>' +
      '<td class="t-muted">' + esc(order.country || '—') + '</td>' +
      '<td class="t-muted">' + esc(fmtTime(order.created_at)) + '</td></tr>',
  )
  return table(
    [{ label: '订单号' }, { label: '商品' }, { label: '数量', align: 'right' },
      { label: '金额', align: 'right' }, { label: '状态' }, { label: '地区' }, { label: '下单时间' }],
    rows,
    { maxHeight: '420px', empty: '这个时间范围内没有订单' },
  )
}

function adsSegment(ads: Dict, currency: string): string {
  const a = ads.metrics || {}
  // 广告侧只有当前窗口，没有上一周期，所以一律不挂环比。挂一排「无对比」只是噪声。
  const metrics =
    metric('广告花费', money(a.spend || 0, currency)) +
    metric('广告销售额', money(a.adSales || 0, currency)) +
    metric('ACOS', pctText(a.acos || 0)) +
    metric('ROAS', (a.roas || 0).toFixed(2)) +
    metric('曝光量', num(a.impressions || 0)) +
    metric('点击量', num(a.clicks || 0)) +
    metric('CTR', pctText(a.ctr || 0)) +
    metric('CPC', money(a.cpc || 0, currency)) +
    metric('广告订单', num(a.adOrders || 0))

  const top = (ads.topProducts || []).map(
    (item: Dict) =>
      '<tr><td><div class="st-cell-product"><div>' +
      '<strong>' + esc(item.name) + '</strong><small>' + esc(item.asin || '—') + '</small>' +
      '</div></div></td>' +
      '<td class="num">' + money(item.spend, currency) + '</td>' +
      '<td class="num">' + money(item.sales, currency) + '</td>' +
      '<td class="num">' + pctText(item.acos) + '</td>' +
      '<td class="num">' + num(item.roas) + '</td></tr>',
  )

  const campaigns = (ads.campaigns || []).map(
    (item: Dict) =>
      '<tr><td>' + esc(item.name) + '</td>' +
      '<td>' + (item.status === 'active' ? pill('投放中', 'ok') : pill('已暂停', 'muted')) + '</td>' +
      '<td class="num">' + num(item.impressions) + '</td>' +
      '<td class="num">' + num(item.clicks) + '</td>' +
      '<td class="num">' + money(item.spend, currency) + '</td>' +
      '<td class="num">' + money(item.sales, currency) + '</td>' +
      '<td class="num">' + pctText(item.acos) + '</td></tr>',
  )

  // 广告活动有 7 列，半宽放不下（销售列会被裁掉），所以两张表都走整宽。
  return (
    card('广告指标', '<div class="st-metrics st-metrics--ads">' + metrics + '</div>', '近 30 天') +
    '<div class="mt-3">' +
    card('广告表现最好的商品',
      table([{ label: '商品' }, { label: '花费', align: 'right' }, { label: '广告销售额', align: 'right' },
        { label: 'ACOS', align: 'right' }, { label: 'ROAS', align: 'right' }], top, { empty: '还没有广告活动' }),
      null, { flush: true }) +
    '</div>' +
    '<div class="mt-3">' +
    card('广告活动',
      table([{ label: '活动' }, { label: '状态' }, { label: '曝光', align: 'right' },
        { label: '点击', align: 'right' }, { label: '花费', align: 'right' },
        { label: '销售额', align: 'right' }, { label: 'ACOS', align: 'right' }], campaigns,
        { maxHeight: '320px', empty: '还没有广告活动' }),
      null, { flush: true }) +
    '</div>'
  )
}

function inventorySegment(inventory: Dict): string {
  const totals = inventory.totals || {}
  const aging = inventory.agingTotals || {}
  const maxAging = Math.max.apply(null, Object.keys(aging).map((key) => aging[key]).concat([1]))

  const rows = (inventory.items || []).map(
    (item: Dict) =>
      '<tr><td><div class="st-cell-product"><div>' +
      '<strong>' + esc(item.name) + '</strong><small>' + esc(item.sku) + '</small>' +
      '</div></div></td>' +
      '<td class="num">' + num(item.available) + '</td>' +
      '<td class="num">' + num(item.reserved) + '</td>' +
      '<td class="num">' + num(item.inbound) + '</td>' +
      '<td class="num">' + num(item.sold30d) + '</td>' +
      '<td class="num">' + (item.turnoverDays === null ? '—' : num(item.turnoverDays)) + '</td>' +
      '<td>' + pill(item.flagLabel, item.level === 'ok' ? 'ok' : item.level === 'danger' ? 'danger' : 'warning') + '</td></tr>',
  )

  const agingRows = Object.keys(aging)
    .map((label) => {
      const value = aging[label]
      return (
        '<div class="st-breakdown-row">' +
        '<span class="st-breakdown-name">' + esc(label) + ' 天</span>' +
        '<span class="st-breakdown-bar"><span style="width:' + Math.max(2, (value / maxAging) * 100) + '%"></span></span>' +
        '<span class="st-breakdown-value">' + num(value) + ' 件</span>' +
        '</div>'
      )
    })
    .join('')

  return (
    card('库存概览',
      '<div class="st-metrics st-metrics--five">' +
      metric('可售库存', num(totals.available || 0), '') +
      metric('已预留', num(totals.reserved || 0), '') +
      metric('在途库存', num(totals.inbound || 0), '') +
      metric('断货 SKU', num(totals.outOfStock || 0), '') +
      metric('低库存 SKU', num(totals.lowStock || 0), '') +
      '</div>', '') +
    card('库龄分布', '<div class="st-breakdown">' + agingRows + '</div>', '按可售件数') +
    card('库存明细',
      table([{ label: '商品' }, { label: '可售', align: 'right' }, { label: '预留', align: 'right' },
        { label: '在途', align: 'right' }, { label: '30 天销量', align: 'right' },
        { label: '可售天数', align: 'right' }, { label: '标记' }], rows,
        { maxHeight: '420px', empty: '这个店铺还没有商品' }),
      (inventory.items || []).length + ' 个 SKU', { flush: true })
  )
}

function aftersalesSegment(returns: Dict[], currency: string): string {
  const list = returns || []
  const refunded = list.filter((item) => item.status === 'refunded')
  const refundAmount = refunded.reduce((sum, item) => sum + Number(item.refund_amount || 0), 0)
  const pending = list.length - refunded.length

  const rows = list.map(
    (item) =>
      '<tr><td>' + esc(item.return_id) + '</td>' +
      '<td>' + esc(item.product_name || item.sku || '—') + '</td>' +
      '<td class="num">' + money(item.refund_amount, currency) + '</td>' +
      '<td>' + esc(item.reason) + '</td>' +
      '<td>' + pill(returnStatus(item.status), returnTone(item.status)) + '</td>' +
      '<td class="t-muted">' + esc(fmtTime(item.requested_at)) + '</td></tr>',
  )

  return (
    card('售后概览',
      '<div class="st-metrics st-metrics--three">' +
      metric('售后单量', num(list.length), '') +
      metric('已退款金额', money(refundAmount, currency), '') +
      metric('待处理', num(pending), '') +
      '</div>', '近 30 天') +
    card('售后订单',
      table([{ label: '售后单号' }, { label: '商品' }, { label: '退款金额', align: 'right' },
        { label: '原因' }, { label: '状态' }, { label: '申请时间' }], rows,
        { maxHeight: '420px', empty: '这段时间没有售后单' }),
      list.length + ' 笔', { flush: true })
  )
}

/* --------------------------------------------------- 子页：单品分析 */

export function productListHtml(products: Dict[], currencyFallback?: string): string {
  const rows = products.map(
    (item) =>
      '<tr><td><div class="st-cell-product"><div>' +
      '<a href="#" data-pick="' + esc(item.asin) + '">' + esc(item.name) + '</a>' +
      '<small>' + esc(item.asin) + ' · ' + esc(item.sku) + '</small>' +
      '</div></div></td>' +
      '<td class="num">' + money(item.price, item.currency || currencyFallback) + '</td>' +
      '<td class="num">' + num(item.rating) + '</td>' +
      '<td class="num">' + num(item.review_count) + '</td>' +
      '<td class="num">' + num(item.stock) + '</td>' +
      '<td>' + (item.stock > 0 ? pill('在售', 'ok') : pill('无库存', 'danger')) + '</td></tr>',
  )
  return card(
    '选择一个商品',
    table([{ label: '商品' }, { label: '价格', align: 'right' }, { label: '评分', align: 'right' },
      { label: '评论', align: 'right' }, { label: '库存', align: 'right' }, { label: '状态' }], rows,
      { empty: '这个店铺还没有商品' }),
    products.length + ' 个商品', { flush: true })
}

export function productDetailHtml(detail: Dict): string {
  const p = detail.product || {}
  const currency = detail.currency || p.currency
  const sm = detail.metrics || {}
  const ads = detail.adsMetrics || {}
  const inv = detail.inventory || null

  const summary =
    '<div class="st-product">' +
    '<span class="st-product-thumb">' + esc(String(p.asin || '?').slice(0, 2)) + '</span>' +
    '<div class="st-product-main">' +
    '<div class="st-product-meta">' + pill(p.asin || '—', 'brand') +
    '<span>' + esc(p.sku || '') + '</span></div>' +
    '<h2 class="st-product-title">' + esc(p.name || '') + '</h2>' +
    '<p class="st-product-sub">' + esc(labelPlatform((detail.store || {}).platform)) +
    (p.marketplace ? ' · ' + esc(labelSite(p.marketplace)) : '') +
    (p.status ? ' · ' + (p.status === 'active' ? '在售' : '已暂停') : '') + '</p>' +
    '</div>' +
    '<dl class="st-product-stats">' +
    '<div><dt>评分</dt><dd>' + num(p.rating) + '<small>/ 5</small></dd></div>' +
    '<div><dt>评论</dt><dd>' + num(p.review_count) + '</dd></div>' +
    '<div><dt>可售库存</dt><dd>' + num(p.stock) + '</dd></div>' +
    '</dl></div>'

  const metrics =
    metric('销售额', money((sm.salesAmount || {}).value, currency), delta((sm.salesAmount || {}).changePct)) +
    metric('销量', num((sm.unitCount || {}).value), delta((sm.unitCount || {}).changePct)) +
    metric('订单量', num((sm.orderCount || {}).value), delta((sm.orderCount || {}).changePct)) +
    metric('广告花费', money(ads.spend || 0, currency)) +
    metric('广告销售额', money(ads.adSales || 0, currency)) +
    metric('可售天数', inv && inv.turnoverDays !== null ? num(inv.turnoverDays) : '—')

  const warnings = (detail.warnings || [])
    .map(
      (item: Dict) =>
        '<div class="st-note' + (item.level === 'danger' ? ' st-note--warning' : '') + '">' +
        esc(item.text) + '</div>',
    )
    .join('')

  const adRows = (detail.ads || []).map(
    (item: Dict) =>
      '<tr><td>' + esc(item.name) + '</td>' +
      '<td>' + (item.status === 'active' ? pill('投放中', 'ok') : pill('已暂停', 'muted')) + '</td>' +
      '<td class="num">' + num(item.clicks) + '</td>' +
      '<td class="num">' + money(item.spend, currency) + '</td>' +
      '<td class="num">' + money(item.sales, currency) + '</td>' +
      '<td class="num">' + pctText(item.acos) + '</td></tr>',
  )

  return (
    summary +
    (warnings ? '<div class="mt-3">' + warnings + '</div>' : '') +
    card('核心指标', '<div class="st-metrics">' + metrics + '</div>', '近 30 天 · 对比上一个周期') +
    card('销售走势', '<div id="st-trend"></div>', '按日') +
    card('广告表现',
      adRows.length
        ? table([{ label: '活动' }, { label: '状态' }, { label: '点击', align: 'right' },
          { label: '花费', align: 'right' }, { label: '销售额', align: 'right' },
          { label: 'ACOS', align: 'right' }], adRows)
        : '<p class="t-sm t-muted" style="margin:0">这个商品近 30 天没有投放广告。</p>',
      null, { flush: adRows.length > 0 })
  )
}

/* --------------------------------------------------- 子页：经营明细 */

export function ledgerSegHtml(current: string): string {
  return LEDGERS.map(
    (item) =>
      '<button type="button" data-kind="' + item.key + '"' +
      (item.key === current ? ' class="is-active"' : '') + '>' + esc(item.label) + '</button>',
  ).join('')
}

export function detailPairs(pairs: Array<[string, unknown]>): string {
  return (
    '<dl class="st-detail">' +
    pairs
      .map(
        (pair) =>
          '<div class="st-detail-row-item"><dt>' + esc(pair[0]) + '</dt><dd>' +
          esc(pair[1] === null || pair[1] === undefined || pair[1] === '' ? '—' : pair[1]) + '</dd></div>',
      )
      .join('') +
    '</dl>'
  )
}

/** 明细表：返回表格 HTML 与「展开行」需要的列数与数据 */
export function buildLedger(
  kind: string,
  items: Dict[],
  currency: string,
): { title: string; html: string; cols: number; detail: (item: Dict) => string } {
  if (kind === 'listing') {
    const rows = items.map(
      (item, index) =>
        '<tr><td><div class="st-cell-product"><div>' +
        '<strong>' + esc(item.name) + '</strong>' +
        '<small>' + esc(item.asin) + ' · ' + esc(item.sku) + '</small>' +
        '</div></div></td>' +
        '<td class="num">' + money(item.price, item.currency || currency) + '</td>' +
        '<td class="num">' + num(item.rating) + '</td>' +
        '<td class="num">' + num(item.review_count) + '</td>' +
        '<td class="num">' + num(item.stock) + '</td>' +
        '<td>' + (item.status === 'active' ? pill('在售', 'ok') : pill('已暂停', 'muted')) + '</td>' +
        '<td class="num"><button type="button" class="st-detail-toggle" data-expand="' + index + '">' +
        '详情' + icon('chevronRight') + '</button></td></tr>',
    )
    return {
      title: 'Listing',
      html: table([{ label: '商品' }, { label: '价格', align: 'right' }, { label: '评分', align: 'right' },
        { label: '评论', align: 'right' }, { label: '库存', align: 'right' }, { label: '状态' },
        { label: '操作', align: 'right' }], rows, { maxHeight: '560px', empty: '这个店铺还没有商品' }),
      cols: 7,
      detail: (item) =>
        detailPairs([
          ['商品 ID', item.product_id],
          ['ASIN', item.asin],
          ['SKU', item.sku],
          ['站点', labelSite(item.marketplace) || item.marketplace],
          ['币种', item.currency],
          ['数据来源', item.is_demo ? '示例目录' : '同步数据'],
        ]),
    }
  }

  if (kind === 'orders') {
    const rows = items.map(
      (item, index) =>
        '<tr><td>' + esc(item.order_id) + '</td>' +
        '<td>' + esc(item.product_name || item.sku || '—') + '</td>' +
        '<td class="num">' + num(item.quantity) + '</td>' +
        '<td class="num">' + money(item.amount, item.currency || currency) + '</td>' +
        '<td>' + pill(orderStatus(item.status), orderTone(item.status)) + '</td>' +
        '<td class="t-muted">' + esc(item.country || '—') + '</td>' +
        '<td class="t-muted">' + esc(fmtTime(item.created_at)) + '</td>' +
        '<td class="num"><button type="button" class="st-detail-toggle" data-expand="' + index + '">' +
        '详情' + icon('chevronRight') + '</button></td></tr>',
    )
    return {
      title: '订单列表',
      html: table([{ label: '订单号' }, { label: '商品' }, { label: '数量', align: 'right' },
        { label: '金额', align: 'right' }, { label: '状态' }, { label: '地区' },
        { label: '下单时间' }, { label: '操作', align: 'right' }], rows,
        { maxHeight: '560px', empty: '这个时间范围内没有订单' }),
      cols: 8,
      detail: (item) =>
        detailPairs([
          ['订单号', item.order_id],
          ['ASIN', item.asin],
          ['SKU', item.sku],
          ['商品', item.product_name],
          ['数量', item.quantity],
          ['金额', money(item.amount, item.currency || currency)],
          ['履约状态', orderStatus(item.status)],
          ['目的国家', item.country],
        ]),
    }
  }

  if (kind === 'aftersales') {
    const rows = items.map(
      (item, index) =>
        '<tr><td>' + esc(item.return_id) + '</td>' +
        '<td>' + esc(item.product_name || item.sku || '—') + '</td>' +
        '<td class="num">' + money(item.refund_amount, item.currency || currency) + '</td>' +
        '<td>' + esc(item.reason) + '</td>' +
        '<td>' + pill(returnStatus(item.status), returnTone(item.status)) + '</td>' +
        '<td class="t-muted">' + esc(fmtTime(item.requested_at)) + '</td>' +
        '<td class="num"><button type="button" class="st-detail-toggle" data-expand="' + index + '">' +
        '详情' + icon('chevronRight') + '</button></td></tr>',
    )
    return {
      title: '售后订单',
      html: table([{ label: '售后单号' }, { label: '商品' }, { label: '退款金额', align: 'right' },
        { label: '原因' }, { label: '状态' }, { label: '申请时间' },
        { label: '操作', align: 'right' }], rows,
        { maxHeight: '560px', empty: '这段时间没有售后单' }),
      cols: 7,
      detail: (item) =>
        detailPairs([
          ['售后单号', item.return_id],
          ['原订单号', item.order_id],
          ['ASIN', item.asin],
          ['SKU', item.sku],
          ['退款金额', money(item.refund_amount, item.currency || currency)],
          ['退款原因', item.reason],
          ['状态', returnStatus(item.status)],
        ]),
    }
  }

  const rows = items.map(
    (item, index) =>
      '<tr><td><div class="st-cell-product"><div>' +
      '<strong>' + esc(item.name) + '</strong><small>' + esc(item.sku) + '</small>' +
      '</div></div></td>' +
      '<td class="num">' + num(item.available) + '</td>' +
      '<td class="num">' + num(item.reserved) + '</td>' +
      '<td class="num">' + num(item.inbound) + '</td>' +
      '<td>' + pill(item.flagLabel, item.level === 'ok' ? 'ok' : item.level === 'danger' ? 'danger' : 'warning') + '</td>' +
      '<td class="num"><button type="button" class="st-detail-toggle" data-expand="' + index + '">' +
      '库龄' + icon('chevronRight') + '</button></td></tr>',
  )
  return {
    title: '库存明细',
    html: table([{ label: '商品' }, { label: '可售', align: 'right' }, { label: '预留', align: 'right' },
      { label: '在途', align: 'right' }, { label: '标记' }, { label: '操作', align: 'right' }], rows,
      { maxHeight: '560px', empty: '这个店铺还没有商品' }),
    cols: 6,
    detail: (item) => {
      const aging = item.aging || {}
      const pairs: Array<[string, unknown]> = Object.keys(aging).map((key) => [key + ' 天', num(aging[key]) + ' 件'])
      pairs.push(['30 天销量', num(item.sold30d) + ' 件'])
      pairs.push(['可售天数', item.turnoverDays === null ? '—' : num(item.turnoverDays) + ' 天'])
      return detailPairs(pairs)
    },
  }
}
