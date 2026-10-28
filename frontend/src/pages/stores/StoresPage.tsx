/**
 * 店铺与渠道 —— React 外壳 + TS 渲染层。
 *
 * 分工：React 管视图状态（店铺/时间范围/分区/明细类型/ASIN）、取数、事件委托、
 * URL 同步与图表绘制；表格与卡片的 HTML 由 `./render.ts` 产出。
 * 这样 DOM 输出与旧实现一致（探针断言的 `.st-*` 契约不变），状态与生命周期交给 React。
 *
 * 两个必须保住的行为：
 *  1. **切筛选条件只改地址、不重挂路由**：`syncUrl` 用 `history.replaceState`，刷新可复原；
 *  2. **未绑定店铺时出三步引导**，而不是空白或报错。
 *
 * DOM 所有权：`#st-stage` 的子节点完全由 createInnerHtml 的 paint effect 管理，
 * 不用 `dangerouslySetInnerHTML`（两者同时用会互相覆盖，React 重渲染时把画好的图抹掉）。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { esc, icon, toast } from '@/lib/ui'
import { go } from '@/app/router'
import { PageFrame } from '@/components/PageShell'
import {
  HEAD,
  LEDGERS,
  RANGES,
  SEGMENTS,
  authorizeHtml,
  buildLedger,
  card,
  createStoreFormHtml,
  dashboardTodosHtml,
  ledgerSegHtml,
  loading,
  productDetailHtml,
  productListHtml,
  segmentBody,
  toolbar,
  unboundState,
  type StoreCtx,
} from './render.ts'

type Dict = Record<string, any>

const PATHS: Record<string, string> = {
  dashboard: '/stores',
  authorize: '/stores/authorize',
  product: '/stores/product',
  ledger: '/stores/ledger',
}

const TABS = [
  { key: 'authorize', label: '店铺授权', path: '/stores/authorize' },
  { key: 'dashboard', label: '经营看板', path: '/stores' },
  { key: 'product', label: '单品分析', path: '/stores/product' },
  { key: 'ledger', label: '经营明细', path: '/stores/ledger' },
]

function syncUrl(ctx: StoreCtx): void {
  const base = PATHS[ctx.view] || '/stores'
  const pairs: string[] = []
  if (ctx.view !== 'authorize') {
    if (ctx.storeId) pairs.push('store=' + encodeURIComponent(ctx.storeId))
    pairs.push('range=' + encodeURIComponent(ctx.range))
  }
  if (ctx.view === 'dashboard' && ctx.segment !== 'overview') pairs.push('seg=' + ctx.segment)
  if (ctx.view === 'ledger' && ctx.ledger !== 'listing') pairs.push('kind=' + ctx.ledger)
  if (ctx.view === 'product' && ctx.asin) pairs.push('asin=' + encodeURIComponent(ctx.asin))
  const url = pairs.length ? base + '?' + pairs.join('&') : base
  // 只改地址，不通知路由（router 只在 popstate / go() 时重绘）
  history.replaceState(history.state, '', url)
}

function pick(list: readonly { key: string }[], value: string | undefined, fallback: string): string {
  return list.some((item) => item.key === value) ? String(value) : fallback
}

function errorCallout(message: string): string {
  return '<div class="callout callout-danger">' + icon('alert') + '<div>' + esc(message) + '</div></div>'
}

export function StoresPage({ view, query }: { view: string; query: Record<string, string> }) {
  const [stores, setStores] = useState<Dict[] | null>(null)
  const [storesError, setStoresError] = useState<string | null>(null)
  const [storeId, setStoreId] = useState(query.store || '')
  const [range, setRange] = useState(() => pick(RANGES, query.range, '30d'))
  const [segment, setSegment] = useState(() => pick(SEGMENTS, query.seg, 'overview'))
  const [ledger, setLedger] = useState(() => pick(LEDGERS, query.kind, 'listing'))
  const [asin, setAsin] = useState(query.asin || '')
  const [trendKey, setTrendKey] = useState('salesAmount')

  const [dash, setDash] = useState<Dict | null>(null)
  const [products, setProducts] = useState<Dict[]>([])
  const [detail, setDetail] = useState<Dict | null>(null)
  const [ledgerItems, setLedgerItems] = useState<Dict[]>([])
  const [sources, setSources] = useState<Dict[]>([])
  const [busy, setBusy] = useState(true)
  const [viewError, setViewError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [platformMeta, setPlatformMeta] = useState<{ catalog: Dict[]; defaultPlatform: string }>({
    catalog: [],
    defaultPlatform: 'amazon',
  })

  const stageRef = useRef<HTMLDivElement>(null)
  const ctx: StoreCtx = useMemo(
    () => ({ view, range, segment, ledger, asin, storeId, stores: stores || [] }),
    [view, range, segment, ledger, asin, storeId, stores],
  )

  /* ---------------------------------------------------------- 店铺列表 */
  useEffect(() => {
    let alive = true
    api
      .get<{ items?: Dict[] }>('/api/stores')
      .then((res) => {
        if (!alive) return
        const items = res.items || []
        setStores(items)
        setStoresError(null)
        setStoreId((prev) => prev || (items[0] ? items[0].connection_id : ''))
      })
      .catch((err: unknown) => {
        if (!alive) return
        setStoresError((err as Error).message)
        setStores([])
      })
      .finally(() => {
        if (alive) setBusy(false)
      })
    return () => {
      alive = false
    }
  }, [])

  /* ---------------------------------------------------- 各子页取数 */

  useEffect(() => {
    if (view !== 'dashboard' || !storeId) return
    let alive = true
    setBusy(true)
    api
      .get<Dict>(
        '/api/marketplace/dashboard?connection_id=' + encodeURIComponent(storeId) +
          '&range=' + encodeURIComponent(range),
      )
      .then((data) => {
        if (!alive) return
        setDash(data)
        setViewError(null)
      })
      .catch((err: unknown) => {
        if (alive) setViewError((err as Error).message)
      })
      .finally(() => {
        if (alive) setBusy(false)
      })
    return () => {
      alive = false
    }
  }, [view, storeId, range])

  useEffect(() => {
    if (view !== 'product' || !storeId) return
    let alive = true
    api
      .get<{ items?: Dict[] }>(
        '/api/marketplace/products?limit=100&connection_id=' + encodeURIComponent(storeId),
      )
      .then((res) => {
        if (alive) setProducts(res.items || [])
      })
      .catch((err: unknown) => {
        if (alive) setViewError((err as Error).message)
      })
    return () => {
      alive = false
    }
  }, [view, storeId])

  useEffect(() => {
    if (view !== 'product' || !storeId) return
    if (!asin) {
      setDetail(null)
      return
    }
    let alive = true
    setBusy(true)
    api
      .get<Dict>(
        '/api/marketplace/products/' + encodeURIComponent(asin) + '/detail?connection_id=' +
          encodeURIComponent(storeId),
      )
      .then((data) => {
        if (!alive) return
        setDetail(data)
        setViewError(null)
      })
      .catch((err: unknown) => {
        if (alive) setViewError((err as Error).message)
      })
      .finally(() => {
        if (alive) setBusy(false)
      })
    return () => {
      alive = false
    }
  }, [view, storeId, asin])

  useEffect(() => {
    if (view !== 'ledger' || !storeId) return
    let alive = true
    setBusy(true)
    api
      .get<{ items?: Dict[] }>(
        '/api/marketplace/ledger?kind=' + encodeURIComponent(ledger) +
          '&connection_id=' + encodeURIComponent(storeId),
      )
      .then((res) => {
        if (!alive) return
        setLedgerItems(res.items || [])
        setViewError(null)
      })
      .catch((err: unknown) => {
        if (alive) setViewError((err as Error).message)
      })
      .finally(() => {
        if (alive) setBusy(false)
      })
    return () => {
      alive = false
    }
  }, [view, storeId, ledger])

  useEffect(() => {
    if (view !== 'authorize') return
    let alive = true
    api
      .get<{ items?: Dict[] }>('/api/marketplace/sources')
      .then((res) => {
        if (alive) setSources(res.items || [])
      })
      .catch(() => {
        /* 拿不到就不显示 */
      })
    return () => {
      alive = false
    }
  }, [view])

  /* ------------------------------------------- 一次性组装并绘制 */

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return

    const toolsHtml = (): string => {
      if (view === 'authorize') return ''
      if (!(stores || []).length) return ''
      if (view === 'product') {
        return toolbar(
          ctx,
          '<span class="st-select st-select--asin">' + icon('search') +
            '<input id="st-asin-input" list="st-asin-list" placeholder="搜索 ASIN / SKU / 商品名"' +
            ' value="' + esc(asin) + '" aria-label="搜索商品" />' +
            '</span>' +
            '<datalist id="st-asin-list">' +
            products
              .map((item) => '<option value="' + esc(item.asin) + '">' + esc(item.name) + ' · ' + esc(item.sku) + '</option>')
              .join('') +
            '</datalist>',
        )
      }
      if (view === 'ledger') {
        return toolbar(ctx, '<div class="st-seg" role="group" aria-label="明细类型">' + ledgerSegHtml(ledger) + '</div>')
      }
      return toolbar(ctx)
    }

    let body: string
    if (storesError) {
      body = errorCallout('店铺列表加载失败：' + storesError)
    } else if (stores === null) {
      body = loading()
    } else if (view === 'authorize') {
      body = authorizeHtml(stores, sources)
    } else if (!stores.length) {
      body = unboundState()
    } else if (viewError) {
      body = errorCallout(viewError)
    } else if (view === 'dashboard') {
      body = dash
        ? dashboardTodosHtml({ ...dash, __segment: segment }) +
          '<div id="st-seg-body">' + segmentBody(ctx, dash) + '</div>'
        : loading()
    } else if (view === 'product') {
      if (!asin) body = productListHtml(products)
      else body = detail ? productDetailHtml(detail) : loading()
    } else {
      if (busy && !ledgerItems.length) body = loading()
      else {
        const currency = (ledgerItems[0] && ledgerItems[0].currency) || 'USD'
        const built = buildLedger(ledger, ledgerItems, currency)
        body = card(built.title, built.html, ledgerItems.length + ' 行', { flush: true })
      }
    }

    stage.innerHTML =
      (view === 'dashboard' && dash && !viewError ? toolsHtml() + '<div id="st-dash">' + body + '</div>' :
        toolsHtml() + body)
    window.CPIcon?.hydrate(stage)

    /* 图表：容器已在文档里，宽度才量得到 */
    if (view === 'dashboard' && dash && !viewError) {
      const trendHost = stage.querySelector('#st-trend') as HTMLElement | null
      if (trendHost) {
        window.CPChart?.line(trendHost, {
          series: (dash.metrics?.salesTrend || []).map((item: Dict) => ({
            date: item.date,
            value: item[trendKey],
          })),
          format: trendKey === 'salesAmount' ? 'money' : 'number',
          currency: dash.currency,
          height: 232,
          label: '业绩走势',
        })
      }
      const hourHost = stage.querySelector('#st-hours') as HTMLElement | null
      if (hourHost) {
        window.CPChart?.bars(hourHost, {
          series: (dash.metrics?.hourDistribution || []).map((item: Dict) => ({
            hour: item.hour,
            label: item.hour + ' 点',
            value: item.orderCount,
          })),
          format: 'number',
          height: 168,
          label: '24 小时下单分布',
        })
      }
    }
    if (view === 'product' && detail && !viewError) {
      const trendHost = stage.querySelector('#st-trend') as HTMLElement | null
      if (trendHost) {
        window.CPChart?.line(trendHost, {
          series: (detail.trend || []).map((item: Dict) => ({ date: item.date, value: item.salesAmount })),
          format: 'money',
          currency: detail.currency || detail.product?.currency,
          height: 232,
          label: '单品销售走势',
        })
      }
    }
  }, [view, stores, storesError, sources, busy, viewError, dash, segment, products, asin, detail,
    ledger, ledgerItems, trendKey, ctx])

  /* -------------------------------------------------- 事件委托 */

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return

    const onChange = (event: Event) => {
      const target = event.target as HTMLInputElement
      if (target.id === 'st-store') setStoreId(target.value)
      else if (target.id === 'st-asin-input') setAsin(target.value.trim().toUpperCase())
    }

    const onClick = async (event: MouseEvent) => {
      const el = (event.target as Element).closest(
        '[data-range],[data-seg-key],[data-seg],[data-trend-key],[data-kind],[data-sync],[data-pick],[data-expand],#st-unbound-add,#st-cancel',
      ) as HTMLElement | null
      if (!el) return

      if (el.id === 'st-unbound-add') {
        go('/stores/authorize')
        return
      }
      if (el.id === 'st-cancel') {
        setShowCreate(false)
        return
      }
      if (el.hasAttribute('data-range')) {
        const next = el.getAttribute('data-range') || '30d'
        setRange(next)
        syncUrl({ ...ctx, range: next })
        return
      }
      if (el.hasAttribute('data-seg-key') || el.hasAttribute('data-seg')) {
        const next = el.getAttribute('data-seg-key') || el.getAttribute('data-seg') || 'overview'
        setSegment(next)
        syncUrl({ ...ctx, segment: next })
        return
      }
      if (el.hasAttribute('data-trend-key')) {
        setTrendKey(el.getAttribute('data-trend-key') || 'salesAmount')
        return
      }
      if (el.hasAttribute('data-kind')) {
        const next = el.getAttribute('data-kind') || 'listing'
        setLedger(next)
        syncUrl({ ...ctx, ledger: next })
        return
      }
      if (el.hasAttribute('data-pick')) {
        event.preventDefault()
        const next = el.getAttribute('data-pick') || ''
        setAsin(next)
        syncUrl({ ...ctx, asin: next })
        return
      }
      if (el.hasAttribute('data-sync')) {
        const id = el.getAttribute('data-sync') || ''
        el.setAttribute('disabled', '1')
        el.textContent = '同步中…'
        try {
          const result = await api.post<{ products?: number; orders?: number }>(
            '/api/stores/' + encodeURIComponent(id) + '/sync',
            {},
          )
          toast('同步完成：' + (result.products || 0) + ' 个商品 / ' + (result.orders || 0) + ' 笔订单', 'ok')
          const res = await api.get<{ items?: Dict[] }>('/api/stores')
          setStores(res.items || [])
        } catch (err) {
          toast((err as Error).message, 'danger')
          el.removeAttribute('disabled')
          el.textContent = '同步'
        }
        return
      }
      if (el.hasAttribute('data-expand')) {
        const row = el.closest('tr')
        if (!row) return
        const next = row.nextElementSibling as HTMLElement | null
        if (next && next.classList.contains('st-detail-row')) {
          next.remove()
          return
        }
        const index = Number(el.getAttribute('data-expand'))
        const currency = (ledgerItems[0] && ledgerItems[0].currency) || 'USD'
        const built = buildLedger(ledger, ledgerItems, currency)
        const item = ledgerItems[index]
        if (!item) return
        const tr = document.createElement('tr')
        tr.className = 'st-detail-row'
        tr.innerHTML = '<td colspan="' + built.cols + '">' + built.detail(item) + '</td>'
        row.after(tr)
      }
    }

    stage.addEventListener('change', onChange)
    stage.addEventListener('click', onClick)
    return () => {
      stage.removeEventListener('change', onChange)
      stage.removeEventListener('click', onClick)
    }
  }, [ctx, ledger, ledgerItems])

  /* 新增店铺表单：插到授权页的 #st-form 里 */
  useEffect(() => {
    const host = stageRef.current?.querySelector('#st-form') as HTMLElement | null
    if (!host) return
    if (!showCreate) {
      host.innerHTML = ''
      return
    }
    const catalog = platformMeta.catalog.length
      ? platformMeta.catalog
      : [{ key: 'amazon', label: 'Amazon', marketplaces: ['US'] }]
    const spec = catalog.filter((item) => item.key === platformMeta.defaultPlatform)[0]
    const markets = spec && spec.marketplaces && spec.marketplaces.length ? spec.marketplaces : ['US']
    host.innerHTML = createStoreFormHtml(catalog, platformMeta.defaultPlatform, markets)

    const form = host.querySelector('#st-create') as HTMLFormElement | null
    if (!form) return
    const platformSelect = form.querySelector('[name="platform"]') as HTMLSelectElement
    const marketSelect = form.querySelector('[name="marketplace"]') as HTMLSelectElement
    const fillMarkets = () => {
      const found = catalog.filter((item) => item.key === platformSelect.value)[0]
      const list = found && found.marketplaces && found.marketplaces.length ? found.marketplaces : ['US']
      marketSelect.innerHTML = list
        .map((code: string) => '<option value="' + esc(code) + '">' + esc(code) + '</option>')
        .join('')
    }
    platformSelect.addEventListener('change', fillMarkets)
    form.addEventListener('submit', async (event) => {
      event.preventDefault()
      try {
        await api.post('/api/stores', {
          platform: platformSelect.value,
          marketplace: marketSelect.value.trim().toUpperCase() || 'US',
          shop_name: (form.querySelector('[name="shop_name"]') as HTMLInputElement).value.trim(),
          mode: 'mock',
        })
        toast('店铺已添加', 'ok')
        setShowCreate(false)
        const res = await api.get<{ items?: Dict[] }>('/api/stores')
        setStores(res.items || [])
      } catch (err) {
        toast((err as Error).message, 'danger')
      }
    })
  }, [showCreate, platformMeta, view, stores])

  const head = HEAD[view] || HEAD.dashboard

  return (
    <PageFrame>
      <div className="page page--store">
        <div className="page-inner">
          <div className="page-head">
            <div>
              <h1 className="page-title">{head.title}</h1>
              <p className="page-desc">{head.desc}</p>
            </div>
            <div className="page-actions">
              {view === 'authorize' ? (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  id="st-add"
                  onClick={async () => {
                    const meta = await api
                      .get<{ catalog?: Dict[]; default_platform?: string }>('/api/platforms')
                      .catch(() => ({ catalog: [], default_platform: 'amazon' }))
                    setPlatformMeta({
                      catalog: meta.catalog || [],
                      defaultPlatform: meta.default_platform || 'amazon',
                    })
                    setShowCreate(true)
                  }}
                >
                  <span
                    style={{ display: 'contents' }}
                    dangerouslySetInnerHTML={{ __html: icon('plus') }}
                  />
                  添加店铺
                </button>
              ) : null}
            </div>
          </div>

          <nav className="st-tabs" aria-label="店铺经营助手">
            {TABS.map((tab) => (
              <a
                className={'st-tab' + (tab.key === view ? ' is-active' : '')}
                href={tab.path}
                data-link=""
                aria-current={tab.key === view ? 'page' : undefined}
                key={tab.key}
              >
                {tab.label}
              </a>
            ))}
          </nav>

          {/* 子节点由上面的 paint effect 独占写入 */}
          <div ref={stageRef} id="st-stage" />
        </div>
      </div>
    </PageFrame>
  )
}
