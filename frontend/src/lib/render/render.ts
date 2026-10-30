/**
 * 结果渲染器 —— 报告与 Listing 的展示逻辑。逐条移植自旧 `js/render.js`。
 *
 * 为什么保留「返回 HTML 字符串」而不是改成 JSX：工作台与技能页都在旧代码里
 * 直接 `innerHTML` 消费它，两边共用同一份实现最稳；等  页面迁完，
 * 这层字符串渲染会被 `<ReportView>` 包成组件，但**内容契约不变**。
 *
 * 与 ui.ts 一样用相对路径 + `.ts` 扩展名，以便 Node 直接加载做语义对照。
 */
import { byteLen, esc, fmtTime, icon, mockFlag } from '../../lib/ui.ts'
import { field as labelField, language as labelLanguage, level as labelLevel } from '../../lib/labels.ts'
import { platform as labelPlatform, site as labelSite } from '../../lib/labels.ts'

type Dict = Record<string, any>

export function money(value: unknown, currency?: string): string {
  if (value === null || value === undefined) return '—'
  const symbol = currency === 'USD' || !currency ? '$' : currency + ' '
  return symbol + Number(value).toFixed(2)
}

function pct(value: unknown): string {
  if (value === null || value === undefined) return '—'
  return (Number(value) * 100).toFixed(0) + '%'
}

export const POSITION_LABEL: Record<string, string> = {
  below_range: '低于竞品区间',
  within_range: '落在竞品区间内',
  above_range: '高于竞品区间',
  unknown: '无法判断',
}

const KIND_LABEL: Record<string, string> = {
  fact: '事实',
  statistic: '统计',
  inference: '推断',
  assumption: '假设',
}

const KIND_CLASS: Record<string, string> = {
  fact: 'badge-ok',
  statistic: 'badge-info',
  inference: 'badge',
  assumption: 'badge-warn',
}

/* ---------------------------------------------------------- 证据分级 */

export function kindBadge(kind: string): string {
  return `<span class="badge ${KIND_CLASS[kind] || 'badge'}">${KIND_LABEL[kind] || kind}</span>`
}

function evidenceList(claim: Dict): string {
  const refs: Dict[] = (claim && claim.evidence) || []
  if (!refs.length) return ''
  return (
    `<ul class="evidence-list">` +
    refs
      .slice(0, 3)
      .map((ref) => {
        const where = [ref.competitor, ref.field ? labelField(ref.field) : '']
          .filter(Boolean)
          .join(' · ')
        const quote = ref.quote ? `「${esc(ref.quote)}」` : ''
        return `<li><span class="t-faint">${esc(where)}</span> ${quote}</li>`
      })
      .join('') +
    `</ul>`
  )
}

function claimBlock(claim: Dict | null | undefined): string {
  if (!claim) return ''
  return (
    `<div class="claim">` +
    `<div class="claim-head">${kindBadge(claim.evidence_kind)}<span>${esc(claim.statement)}</span></div>` +
    evidenceList(claim) +
    `</div>`
  )
}

/* ------------------------------------------------------ 竞品分析报告 */

function engineLabel(engine?: string): string {
  return engine === 'rule' ? '规则生成' : 'AI 模型生成'
}

function reportMeta(report: Dict): string {
  const prov = report.data_provenance || {}
  return (
    `<div class="row wrap gap-2">` +
    (prov.is_demo ? mockFlag() : `<span class="badge badge-ok">你提供的数据</span>`) +
    `<span class="badge">${esc(engineLabel(report.engine))}</span>` +
    `<span class="t-xs t-muted">竞品 ${prov.competitor_count || 0} · 评论样本 ${prov.review_sample_count || 0} · 关键词 ${prov.keyword_count || 0}</span>` +
    `</div>`
  )
}

function priceSection(price: Dict | null | undefined): string {
  if (!price) return `<p class="t-sm t-muted">没有竞品价格，价格分析不可用。</p>`
  const cells = (
    [
      ['最低价', money(price.min_price, price.currency)],
      ['中位价', money(price.median_price, price.currency)],
      ['最高价', money(price.max_price, price.currency)],
      ['自有价格', price.own_price === null ? '未填写' : money(price.own_price, price.currency)],
    ] as Array<[string, string]>
  )
    .map((kv) => {
      return (
        `<div class="metric-cell"><div class="metric-label">${kv[0]}</div>` +
        `<div class="metric-value">${esc(kv[1])}</div></div>`
      )
    })
    .join('')
  return (
    `<div class="metric-grid">${cells}</div>` +
    `<p class="t-sm t-muted mt-2">定位：${esc(POSITION_LABEL[price.own_position] || price.own_position)}` +
    (price.compared_count ? `（对比 ${price.compared_count} 个竞品）` : '') +
    `</p>` +
    (price.claims || []).map(claimBlock).join('')
  )
}

function competitorTable(report: Dict): string {
  const rows = (report.competitor_snapshots || [])
    .map((c: Dict) => {
      return (
        `<tr>` +
        `<td><strong>${esc(c.name)}</strong>${c.is_demo ? ' ' + mockFlag() : ''}` +
        `<div class="t-xs t-faint">${esc(c.brand || '')}${c.brand && c.missing_fields ? ' · ' : ''}` +
        `${
          c.missing_fields && c.missing_fields.length
            ? '还缺 ' + esc(c.missing_fields.map((k: string) => labelField(k)).join('、'))
            : ''
        }</div></td>` +
        `<td class="num">${money(c.price, c.currency)}</td>` +
        `<td class="num">${c.rating === null || c.rating === undefined ? '—' : Number(c.rating).toFixed(1)}</td>` +
        `<td class="num">${c.review_count === null || c.review_count === undefined ? '—' : c.review_count}</td>` +
        `<td class="num">${c.review_samples}</td>` +
        `<td class="num">${pct(c.data_completeness)}</td>` +
        `</tr>`
      )
    })
    .join('')
  if (!rows) return `<p class="t-sm t-muted">没有竞品数据。</p>`
  return (
    `<div class="table-wrap"><table class="table"><thead><tr>` +
    `<th>竞品</th><th class="num">价格</th><th class="num">评分</th>` +
    `<th class="num">评论总数</th><th class="num">评论样本</th><th class="num">字段完整度</th>` +
    `</tr></thead><tbody>${rows}</tbody></table></div>`
  )
}

function painPoints(report: Dict): string {
  const insights = report.review_insights || {}
  const groups: Array<[string, Dict[] | undefined]> = [
    ['痛点', insights.pain_points],
    ['低星主题', insights.low_rating_themes],
    ['需求', insights.needs],
    ['购买顾虑', insights.purchase_concerns],
  ]
  const has = groups.some((g) => g[1] && g[1].length)
  if (!has) {
    const total = insights.total_samples || 0
    const head =
      total === 0
        ? '还没有评论样本，主题分析无法开始。'
        : `已收到 ${total} 条评论样本，还不足以归纳主题。`
    return (
      `<p class="t-sm t-muted">${head}` +
      (insights.limitations || []).map((l: string) => `<br>${esc(l)}`).join('') +
      `</p>`
    )
  }
  return groups
    .map((g) => {
      const items = g[1] || []
      if (!items.length) return ''
      return (
        `<div class="t-section mt-3">${g[0]}</div>` +
        items
          .slice(0, 6)
          .map((p: Dict) => {
            const quotes = (p.samples || [])
              .slice(0, 2)
              .map((s: Dict) => `<li>${esc(s.competitor || '')}「${esc(s.quote || '')}」</li>`)
              .join('')
            return (
              `<div class="pain-item">` +
              `<div class="row between"><strong class="t-sm">${esc(p.label)}</strong>` +
              `<span class="t-xs t-muted num">${p.frequency} 次 · 占样本 ${pct(p.share)}</span></div>` +
              `<div class="t-xs t-muted">${esc(p.description)}</div>` +
              (quotes ? `<ul class="evidence-list">${quotes}</ul>` : '') +
              `</div>`
            )
          })
          .join('')
      )
    })
    .join('')
}

function keywordSection(report: Dict): string {
  const kw = report.keyword_analysis || {}
  if (!kw.available) return `<p class="t-sm t-muted">未提供关键词数据。</p>`
  const rows = (kw.opportunities || [])
    .map((o: Dict) => {
      return (
        `<tr><td>${esc(o.keyword)}</td>` +
        `<td class="num">${o.search_volume === null ? '无数据' : o.search_volume}</td>` +
        `<td class="num">${o.rank === null ? '无数据' : o.rank}</td>` +
        `<td class="num">${o.opportunity_score === null ? '不计算' : Number(o.opportunity_score).toFixed(1)}</td>` +
        `<td class="t-xs t-muted">${esc(o.basis || '')}</td></tr>`
      )
    })
    .join('')
  return (
    `<p class="t-sm t-muted">共 ${kw.total_keywords} 个关键词，其中 ${kw.with_metrics} 个带指标。` +
    `无指标的关键词不计算机会分，也不推断流量。</p>` +
    (rows
      ? `<div class="table-wrap mt-2"><table class="table"><thead><tr>` +
        `<th>关键词</th><th class="num">搜索量</th><th class="num">排名</th><th class="num">机会分</th><th>依据</th>` +
        `</tr></thead><tbody>${rows}</tbody></table></div>`
      : '')
  )
}

function differentiation(report: Dict): string {
  const items: Dict[] = report.differentiation_opportunities || []
  if (!items.length) return `<p class="t-sm t-muted">没有可用的差异化机会。</p>`
  return items
    .map((d) => {
      return (
        `<div class="pain-item">` +
        `<div class="row between"><strong class="t-sm">${esc(d.angle)}</strong>` +
        `<span class="row gap-1"><span class="badge">机会 ${esc(labelLevel(d.priority))}</span>` +
        `<span class="badge">置信 ${esc(labelLevel(d.confidence))}</span></span></div>` +
        `<div class="t-xs t-muted">${esc(d.rationale)}</div>` +
        (d.requires_confirmation
          ? `<div class="t-xs t-danger mt-1">需要人工确认后才可使用</div>`
          : '') +
        `</div>`
      )
    })
    .join('')
}

function recommendations(report: Dict): string {
  const items: Dict[] = report.content_recommendations || []
  if (!items.length) return ''
  return items
    .map((r) => {
      return (
        `<div class="pain-item">` +
        `<div class="row gap-2">${kindBadge(r.evidence_kind)}<strong class="t-sm">${esc(labelField(r.area))}</strong></div>` +
        `<div class="t-sm">${esc(r.recommendation)}</div>` +
        `<div class="t-xs t-muted">${esc(r.rationale)}</div>` +
        `</div>`
      )
    })
    .join('')
}

function limitations(report: Dict): string {
  const warnings: string[] = report.warnings || []
  const limits: string[] = report.limitations || []
  return (
    (warnings.length
      ? `<div class="callout callout-warn mb-2">${icon('alert')}<div>` +
        warnings.map((w) => esc(w)).join('<br>') +
        `</div></div>`
      : '') +
    (limits.length
      ? `<details class="provenance"><summary>使用限制（${limits.length}）</summary>` +
        `<ul class="limit-list">` +
        limits.map((l) => `<li>${esc(l)}</li>`).join('') +
        `</ul></details>`
      : '')
  )
}

export function renderReport(report: Dict, options?: { actions?: string }): string {
  const opts = options || {}
  return (
    `<div class="report-block">` +
    `<div class="report-head">` +
    `<div><div class="t-section">${esc(report.product_name)}</div>` +
    `<div class="t-xs t-muted">${esc(labelPlatform(report.platform))} · ` +
    `${esc(labelSite(report.marketplace))} · ` +
    `${esc(fmtTime(report.created_at))}</div></div>` +
    (opts.actions || '') +
    `</div>` +
    `<div class="mt-2">${reportMeta(report)}</div>` +
    `<div class="t-section mt-4">价格定位</div>` +
    priceSection(report.price_analysis) +
    `<div class="t-section mt-4">竞品对比</div>` +
    competitorTable(report) +
    `<div class="t-section mt-4">评论洞察</div>` +
    painPoints(report) +
    `<div class="t-section mt-4">关键词</div>` +
    keywordSection(report) +
    `<div class="t-section mt-4">差异化机会</div>` +
    differentiation(report) +
    `<div class="t-section mt-4">内容建议</div>` +
    recommendations(report) +
    `<div class="mt-4">${limitations(report)}</div>` +
    `</div>`
  )
}

/** 报告按区块单独取用：结果面板把它拆成「竞品对比 / 评论洞察」两个视图 */
export function renderReportPart(report: Dict, part: 'competitors' | 'reviews' | 'insights'): string {
  if (part === 'competitors') {
    return (
      `<div class="t-section">价格定位</div>` +
      priceSection(report.price_analysis) +
      `<div class="t-section mt-4">竞品对比</div>` +
      competitorTable(report)
    )
  }
  if (part === 'reviews') {
    return `<div class="t-section">评论洞察</div>` + painPoints(report)
  }
  return (
    `<div class="t-section">关键词</div>` +
    keywordSection(report) +
    `<div class="t-section mt-4">差异化机会</div>` +
    differentiation(report) +
    `<div class="t-section mt-4">内容建议</div>` +
    recommendations(report) +
    `<div class="mt-4">${limitations(report)}</div>`
  )
}

/* ------------------------------------------------------ Listing 草稿 */

/* 质检问题：说清「哪里」「什么问题」「怎么改」，不暴露内部问题编号 */
const SEVERITY_LABEL: Record<string, string> = {
  error: '必须改',
  warning: '建议改',
  info: '提示',
}

function issueBlock(issue: Dict): string {
  const isError = issue.severity === 'error'
  const tone = isError
    ? 'callout-danger'
    : issue.severity === 'warning'
      ? 'callout-warn'
      : 'callout-info'
  const level = SEVERITY_LABEL[issue.severity] || '提示'
  const where = issue.location ? labelField(issue.location) : ''
  return (
    `<div class="callout ${tone} mb-2">${icon(isError ? 'alert' : 'info')}` +
    `<div><strong>${esc(level)}</strong>` +
    (where ? ` · <span class="t-xs">${esc(where)}</span>` : '') +
    `<br>${esc(issue.message)}` +
    (issue.suggestion
      ? `<div class="t-xs mt-1" style="opacity:.85">建议：${esc(issue.suggestion)}</div>`
      : '') +
    `</div></div>`
  )
}

export function renderListing(listing: Dict, options?: { actions?: string }): string {
  const opts = options || {}
  const qc = listing.quality_check || {}
  const prov = listing.data_provenance || {}
  const bullets = (listing.bullets || [])
    .map((b: Dict, i: number) => {
      return (
        `<div class="bullet-item">` +
        `<div class="row between"><strong class="t-sm">${i + 1}. ${esc(b.headline)}</strong>` +
        `<span class="t-xs t-muted num">${b.character_count} 字符</span></div>` +
        `<div class="t-sm">${esc(b.body)}</div>` +
        `</div>`
      )
    })
    .join('')

  const lengths = (qc.section_lengths || [])
    .map((s: Dict) => {
      return (
        `<tr><td>${esc(labelField(s.section))}</td><td class="num">${s.length}</td>` +
        `<td class="num">${s.limit === null ? '—' : s.limit}</td>` +
        `<td>${s.within_limit ? '<span class="badge badge-ok">通过</span>' : '<span class="badge badge-danger">超限</span>'}</td></tr>`
      )
    })
    .join('')

  const ledger = (listing.fact_ledger || [])
    .map((f: Dict) => {
      return `<tr><td>${esc(f.statement)}</td><td>${esc(labelField(f.source))}</td></tr>`
    })
    .join('')

  return (
    `<div class="report-block">` +
    `<div class="report-head">` +
    `<div><div class="t-section">${esc(listing.product_name)}</div>` +
    `<div class="t-xs t-muted">${esc(labelPlatform(listing.platform))} · ` +
    `${esc(labelSite(listing.marketplace))} · ` +
    `${esc(labelLanguage(listing.language))} · ` +
    `${esc(fmtTime(listing.created_at))}</div></div>` +
    `<div class="row gap-2">` +
    (prov.is_demo ? mockFlag() : '') +
    `<span class="badge ${qc.passed ? 'badge-ok' : 'badge-warn'}">质检：${qc.passed ? '通过' : '存在问题'}</span>` +
    (opts.actions || '') +
    `</div></div>` +

    `<div class="t-section mt-4">标题（${(listing.title || '').length} 字符）</div>` +
    `<div class="copy-row"><div class="copy-body">${esc(listing.title)}</div>` +
    `<button type="button" class="copy-btn" data-copy="${esc(listing.title)}">${icon('copy')}复制</button></div>` +

    `<div class="t-section mt-4">五点描述</div>${bullets || '<p class="t-sm t-muted">无</p>'}` +

    `<div class="t-section mt-4">产品描述</div>` +
    `<div class="copy-row"><div class="copy-body" style="white-space:pre-wrap">${esc(listing.description)}</div>` +
    `<button type="button" class="copy-btn" data-copy="${esc(listing.description)}">${icon('copy')}复制</button></div>` +

    `<div class="t-section mt-4">Search Terms（${byteLen(listing.search_terms || '')} / 250 字节）</div>` +
    `<div class="copy-row"><div class="copy-body">${esc(listing.search_terms) || '<span class="t-muted">无</span>'}</div>` +
    (listing.search_terms
      ? `<button type="button" class="copy-btn" data-copy="${esc(listing.search_terms)}">${icon('copy')}复制</button>`
      : '') +
    `</div>` +

    `<div class="t-section mt-4">质量检查</div>` +
    ((qc.issues || []).length
      ? qc.issues.map(issueBlock).join('')
      : '<p class="t-sm t-muted">未发现问题。</p>') +
    (lengths
      ? `<div class="table-wrap mt-2"><table class="table"><thead><tr>` +
        `<th>区块</th><th class="num">长度</th><th class="num">上限</th><th>结果</th>` +
        `</tr></thead><tbody>${lengths}</tbody></table></div>`
      : '') +
    (qc.policy_disclaimer ? `<p class="t-xs t-muted mt-2">${esc(qc.policy_disclaimer)}</p>` : '') +

    ((listing.pending_confirmations || []).length
      ? `<div class="t-section mt-4">待人工确认（${listing.pending_confirmations.length}）</div>` +
        `<ul class="limit-list">` +
        listing.pending_confirmations.map((p: string) => `<li>${esc(p)}</li>`).join('') +
        `</ul>`
      : '') +

    (ledger
      ? `<details class="provenance mt-4"><summary>事实来源台账（${(listing.fact_ledger || []).length} 条）</summary>` +
        `<div class="table-wrap"><table class="table"><thead><tr><th>事实</th><th>来源字段</th></tr></thead>` +
        `<tbody>${ledger}</tbody></table></div></details>`
      : '') +

    ((listing.limitations || []).length
      ? `<details class="provenance mt-2"><summary>使用限制</summary><ul class="limit-list">` +
        listing.limitations.map((l: string) => `<li>${esc(l)}</li>`).join('') +
        `</ul></details>`
      : '') +
    `</div>`
  )
}

export const renderApi = { renderReport, renderReportPart, renderListing, kindBadge, money, POSITION_LABEL }
