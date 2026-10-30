/**
 * 技能结果分块：按能力 key 分派到对应的产出块，产出 HTML 字符串由页面塞进结果区。
 * `competitor_analysis` / `listing_generation` 直接复用 `lib/render` 的报告与 Listing 渲染器。
 */
import { esc, icon } from '@/lib/ui'
import { kindBadge, money, renderListing, renderReport } from '@/lib/render/render.ts'
import { mountBars } from '@/components/shared/charts/mount-lazy'

type Dict = Record<string, any>

export function demoBanner(isDemo: boolean): string {
  if (!isDemo) return ''
  return (
    `<div class="callout callout-warn mb-3">${icon('alert')}` +
    `<div><strong>示例数据</strong><br>这份结果基于示例数据，不能用于真实经营决策。</div></div>`
  )
}

function summaryBlock(out: Dict): string {
  const points = (out.points || [])
    .map((p: Dict) => `<li>${esc(p.text)}${kindBadge(p.evidence_kind)}</li>`)
    .join('')
  return (
    `<div class="card card-pad"><div class="card-title">${esc(out.headline || '市场机会判断')}</div>` +
    `<ul class="sk-bullets mt-3">${points || '<li>这份报告里没有可用于归纳的结论。</li>'}</ul>` +
    ((out.limitations || []).length
      ? `<p class="t-xs t-muted mt-3">局限：${esc((out.limitations || []).join('；'))}</p>`
      : '') +
    `</div>`
  )
}

function miningBlock(out: Dict): string {
  const sections = [
    { title: '痛点', rows: out.pain_points || [], withShare: true },
    { title: '需求', rows: out.needs || [], withShare: false },
    { title: '购买顾虑', rows: out.concerns || [], withShare: false },
  ]
  return (
    sections
      .map((sec) => {
        const rows = sec.rows
          .map((r: Dict) => {
            const share =
              sec.withShare && r.share !== undefined && r.share !== null
                ? `<td class="num">${Math.round(r.share * 1000) / 10}%</td>`
                : sec.withShare
                  ? `<td class="num">—</td>`
                  : ''
            return `<tr><td>${esc(r.label)}</td><td class="num">${r.frequency || 0}</td>${share}</tr>`
          })
          .join('')
        return (
          `<div class="card mb-3"><div class="table-wrap"><table class="table">` +
          `<thead><tr><th>${esc(sec.title)}</th><th class="num">出现次数</th>` +
          (sec.withShare ? `<th class="num">占比</th>` : '') +
          `</tr></thead><tbody>${
            rows ||
            `<tr><td colspan="${sec.withShare ? 3 : 2}" class="t-muted">这份报告里没有这一类样本。</td></tr>`
          }</tbody></table></div></div>`
        )
      })
      .join('') +
    `<p class="t-xs t-muted">共 ${out.total_samples || 0} 条评论样本，其中 ${out.with_rating || 0} 条带星级。</p>`
  )
}

function qualityBlock(out: Dict): string {
  const row = (text: string, tone?: string) =>
    `<li><span class="badge ${tone || ''}">${
      tone === 'badge-danger' ? '必须改' : tone === 'badge-warn' ? '建议改' : '待确认'
    }</span> ${esc(text)}</li>`
  const errors = (out.errors || []).map((t: string) => row(t, 'badge-danger'))
  const warnings = (out.warnings || []).map((t: string) => row(t, 'badge-warn'))
  const pending = (out.pending_confirmations || []).map((t: string) => row(t, ''))
  const all = errors.concat(warnings).concat(pending)
  return (
    `<div class="card card-pad"><div class="row between">` +
    `<div class="card-title">检查结果</div>` +
    `<span class="badge ${out.passed ? 'badge-ok' : 'badge-danger'}">${
      out.passed ? '通过' : '需要处理'
    }</span></div>` +
    (all.length
      ? `<ul class="sk-bullets mt-3">${all.join('')}</ul>`
      : `<p class="t-sm t-soft mt-2">没有发现需要修改的地方。</p>`) +
    (out.policy_disclaimer ? `<p class="t-xs t-muted mt-3">${esc(out.policy_disclaimer)}</p>` : '') +
    `</div>`
  )
}

function validationBlock(out: Dict): string {
  const errors = out.errors || []
  const rows = errors
    .map(
      (e: Dict) =>
        `<tr><td class="num">${e.row || '—'}</td><td>${esc(e.field || '')}</td><td>${esc(
          e.message || '',
        )}</td></tr>`,
    )
    .join('')
  const preview = (out.preview || [])
    .map(
      (c: Dict) =>
        `<tr><td>${esc(c.name || '')}</td><td class="num">${
          c.price === null || c.price === undefined ? '—' : c.price
        }</td><td class="num">${c.rating === null || c.rating === undefined ? '—' : c.rating}</td></tr>`,
    )
    .join('')

  return (
    `<div class="card card-pad mb-3"><div class="row between">` +
    `<div class="card-title">${out.ok ? '校验通过' : '有需要修正的行'}</div>` +
    `<span class="badge ${out.ok ? 'badge-ok' : 'badge-warn'}">共 ${out.total_rows || 0} 行 · 有效 ${
      out.valid_rows || 0
    } 行</span></div>` +
    (errors.length
      ? `<div class="table-wrap mt-3"><table class="table"><thead><tr>` +
        `<th class="num">行</th><th>字段</th><th>问题</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : `<p class="t-sm t-soft mt-2">每一行都通过了字段检查。</p>`) +
    ((out.warnings || []).length
      ? `<p class="t-xs t-muted mt-3">${esc((out.warnings || []).join('；'))}</p>`
      : '') +
    `</div>` +
    (preview
      ? `<div class="card"><div class="table-wrap"><table class="table"><thead><tr>` +
        `<th>预览（前 5 个竞品）</th><th class="num">价格</th><th class="num">评分</th>` +
        `</tr></thead><tbody>${preview}</tbody></table></div></div>`
      : '') +
    (out.batch_id
      ? `<div class="row gap-2 mt-3"><a class="btn btn-sm" href="/skills?skill=competitor_analysis&batch=${esc(
          out.batch_id,
        )}" data-link>用这批数据做竞品分析</a>` +
        `<a class="btn btn-quiet btn-sm" href="/data" data-link>去数据资产查看</a></div>`
      : '')
  )
}

function profitBlock(out: Dict): string {
  const cur = out.currency || 'USD'
  const fmt = (v: unknown) => money(v, cur)
  const kpi = (label: string, value: string, hint?: string) =>
    `<div class="sk-kpi"><span class="sk-kpi-label">${esc(label)}</span>` +
    `<span class="sk-kpi-value">${value}</span>` +
    (hint ? `<span class="sk-kpi-hint">${esc(hint)}</span>` : '') +
    `</div>`

  const rows = (out.cost_breakdown || [])
    .map(
      (c: Dict) =>
        `<tr><td>${esc(c.label)}</td><td class="num">${fmt(c.amount)}</td>` +
        `<td class="num">${Math.round((c.ratio_to_price || 0) * 1000) / 10}%</td>` +
        `<td class="t-xs t-muted">${esc(c.formula || '')}</td></tr>`,
    )
    .join('')

  return (
    `<div class="card card-pad mb-3">` +
    `<div class="sk-kpis">` +
    kpi('单件售价', fmt(out.selling_price)) +
    kpi('单件总成本', fmt(out.total_cost)) +
    kpi('单件毛利', fmt(out.unit_profit)) +
    kpi('毛利率', `${Math.round((out.margin || 0) * 1000) / 10}%`) +
    `</div>` +
    `<div class="chart" data-chart="cost" style="margin-top:var(--sp-4)"></div>` +
    `</div>` +
    `<div class="card mb-3"><div class="table-wrap"><table class="table"><thead><tr>` +
    `<th>成本项</th><th class="num">金额</th><th class="num">占售价比</th><th>口径</th>` +
    `</tr></thead><tbody>${rows}</tbody></table></div></div>` +
    `<div class="card card-pad">` +
    `<div class="sk-kpis">` +
    kpi('保本价', out.break_even_price === null ? '—' : fmt(out.break_even_price)) +
    kpi('建议价', out.recommended_price === null ? '—' : fmt(out.recommended_price)) +
    kpi(
      '可接受区间',
      out.price_floor === null || out.price_ceiling === null
        ? '—'
        : `${fmt(out.price_floor)} – ${fmt(out.price_ceiling)}`,
    ) +
    `</div>` +
    ((out.warnings || []).length
      ? `<p class="t-xs t-muted mt-3">${esc((out.warnings || []).join('；'))}</p>`
      : '') +
    `</div>`
  )
}

/** 按技能 key 分派到对应的结果块 */
export function outputHtml(skillKey: string, payload: Dict): string {
  const out = payload.output || {}
  const demo = demoBanner(Boolean(payload.is_demo))

  if (skillKey === 'competitor_analysis') return demo + renderReport(out, {})
  if (skillKey === 'listing_generation') return demo + renderListing(out, {})
  if (skillKey === 'market_summary') return demo + summaryBlock(out)
  if (skillKey === 'review_mining') return demo + miningBlock(out)
  if (skillKey === 'listing_quality') return demo + qualityBlock(out)
  if (skillKey === 'data_validation') return validationBlock(out)
  if (skillKey === 'profit_calc') return profitBlock(out)
  return demo
}

/** 成本构成柱图：Recharts（宿主在字符串 HTML 里，走命令式挂载） */
export function paintChart(host: HTMLElement, skillKey: string, payload: Dict): void {
  if (skillKey !== 'profit_calc') return
  const target = host.querySelector('[data-chart="cost"]') as HTMLElement | null
  if (!target) return
  const out = payload.output || {}
  mountBars(target, {
    series: (out.cost_breakdown || []).map((c: Dict) => ({
      label: String(c.label || ''),
      value: Number(c.amount) || 0,
    })),
    label: '成本构成',
    format: 'number',
    height: 168,
    emptyText: '这次测算没有分项成本',
  })
}
