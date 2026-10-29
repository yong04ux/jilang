/**
 * 异步任务面板的展示部分 —— 从旧 `js/async-run.js` 迁移（状态机见 poller.ts）。
 *
 * 保留「不伪造进度」这条纪律：进度条只用于「未完成」这种不确定状态，
 * 百分比永远不出现。
 */
import { esc, fmtDuration, icon, statusBadge } from '@/lib/ui'

type Dict = Record<string, any>

const STEP_ICON: Record<string, string> = {
  succeeded: 'check',
  running: 'play',
  failed: 'x',
  cancelled: 'stop',
  skipped: 'clock',
  pending: 'clock',
}

/**
 * 计划骨架的步骤名 → 用户看得懂的说法。
 * 节点名以 task_steps.node 为准；这里漏一个就会在时间线上露出英文键名。
 */
const PLAN_LABELS: Record<string, string> = {
  // 主图三阶段
  validate: '校验任务输入',
  dispatch: '分派工作流',
  finalize: '收尾并落任务状态',
  // 竞品分析子图
  validate_input: '校验分析输入',
  resolve_data_provider: '确定数据来源',
  fetch_competitors: '获取竞品数据',
  normalize_data: '归一化与去重',
  check_data_sufficiency: '检查样本充分性',
  analyze_market: '计算价格与卖点结论',
  validate_analysis: '校验分析结果',
  summarize_opportunities: '归纳市场机会',
  persist_result: '保存报告',
  // 组合工作流
  validate_request: '校验组合请求',
  run_analysis: '竞品分析',
  prepare_confirmation: '整理待确认信息',
  confirm_partial: '等待用户确认',
  cancel_flow: '按用户要求取消',
  check_listing_facts: '检查商品事实',
  resolve_product_facts: '整理商品事实',
  load_brand_rules: '加载站点规则',
  load_market_insights: '读取竞品洞察',
  check_required_facts: '检查关键事实',
  generate_listing: '生成 Listing 草稿',
  validate_listing: '质检草稿',
  revise_listing: '按质检问题修订',
  persist_draft: '保存草稿',
  needs_review: '等待人工复核',
}

export function planLabel(name: string): string {
  return PLAN_LABELS[name] || name
}

export function stepList(steps: Dict[] | null | undefined, plan: string[] | null | undefined): string {
  if (steps && steps.length) {
    return (
      '<ul class="timeline">' +
      steps
        .map((s) => {
          /* 已经跑完的步骤默认收起细节，展开才看证据；进行中与失败的一直铺开 */
          const folded = s.status === 'succeeded' || s.status === 'skipped'
          const detail = s.detail
            ? folded
              ? `<details class="timeline-more"><summary>查看详情</summary>` +
                `<div class="timeline-detail">${esc(s.detail)}</div></details>`
              : `<div class="timeline-detail">${esc(s.detail)}</div>`
            : ''
          return (
            `<li class="timeline-item is-${esc(s.status)}">` +
            `<span class="timeline-dot">${icon(STEP_ICON[s.status] || 'clock')}</span>` +
            `<div class="timeline-body"><div class="timeline-head">` +
            `<span class="timeline-name">${s.seq}. ${esc(s.name)}</span>` +
            statusBadge(s.status) +
            (s.duration_ms !== null && s.duration_ms !== undefined
              ? `<span class="timeline-meta">${fmtDuration(s.duration_ms)}</span>`
              : '') +
            `</div>` +
            detail +
            `</div></li>`
          )
        })
        .join('') +
      '</ul>'
    )
  }
  // 尚未产生真实步骤：只展示计划名称，明确标注「等待」
  const names = plan || []
  if (!names.length) return '<p class="t-sm t-muted">等待执行器创建任务…</p>'
  return (
    '<ul class="timeline">' +
    names
      .map((name, index) => {
        const label = planLabel(name)
        return (
          `<li class="timeline-item is-pending">` +
          `<span class="timeline-dot">${icon('clock')}</span>` +
          `<div class="timeline-body"><div class="timeline-head">` +
          `<span class="timeline-name">${index + 1}. ${esc(label)}</span>` +
          statusBadge('pending') +
          `</div></div></li>`
        )
      })
      .join('') +
    '</ul>'
  )
}

/** 结果面板骨架：步骤 / 数据 两个 Tab（旧实现里只有这两个） */
export function resultTabs(opts: { active?: string }): string {
  const active = opts?.active || 'steps'
  const tabs = [
    { key: 'steps', label: '步骤' },
    { key: 'data', label: '数据' },
  ]
  return (
    '<div class="res-tabs" role="tablist">' +
    tabs
      .map(
        (t) =>
          `<button type="button" class="res-tab${t.key === active ? ' is-active' : ''}" ` +
          `data-res-tab="${t.key}" role="tab" aria-selected="${t.key === active}">${t.label}</button>`,
      )
      .join('') +
    '</div>'
  )
}

export const presentApi = { stepList, planLabel, resultTabs }
