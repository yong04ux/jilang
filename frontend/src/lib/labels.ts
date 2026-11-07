/**
 * 展示用标签 —— 把接口里的内部标识翻成人话。
 *
 * 红线（见 design.md 文案规范）：站点码、语言码、任务类型、字段名、枚举值
 * 不得原样出现在界面上。页面模块与 React 页面都走这一份，避免各写一份字典。
 *
 * 用法：site('US') → 美国站；language('en-US') → 英文（美国）；
 *       taskType('listing_generation') → Listing 生成
 */

export const SITE: Record<string, string> = {
  US: '美国站',
  CA: '加拿大站',
  UK: '英国站',
  GB: '英国站',
  DE: '德国站',
  FR: '法国站',
  IT: '意大利站',
  ES: '西班牙站',
  JP: '日本站',
  MX: '墨西哥站',
  AU: '澳洲站',
  AE: '阿联酋站',
  SG: '新加坡站',
  IN: '印度站',
  BR: '巴西站',
}

export const LANGUAGE: Record<string, string> = {
  'en-US': '英文（美国）',
  'en-CA': '英文（加拿大）',
  'en-GB': '英文（英国）',
  'de-DE': '德文',
  'fr-FR': '法文',
  'it-IT': '意大利文',
  'es-ES': '西班牙文',
  'es-MX': '西班牙文（墨西哥）',
  'ja-JP': '日文',
  'zh-CN': '中文',
}

const LANGUAGE_BASE: Record<string, string> = {
  en: '英文',
  de: '德文',
  fr: '法文',
  it: '意大利文',
  es: '西班牙文',
  ja: '日文',
  zh: '中文',
}

export const TASK_TYPE: Record<string, string> = {
  competitor_analysis: '竞品分析',
  listing_generation: 'Listing 生成',
  data_import: '数据导入',
  agent_workflow: 'Agent 工作流',
  skill_run: '技能运行',
  publish_listing: '发布审批',
  report_export: '报告导出',
  store_sync: '店铺同步',
}

const TASK_RESULT: Record<string, string> = {
  competitor_analysis: '报告',
  listing_generation: '草稿',
  agent_workflow: '报告',
  skill_run: '产出',
  publish_listing: '草稿',
  data_import: '批次',
  store_sync: '同步批次',
}

const PLATFORM: Record<string, string> = {
  amazon: 'Amazon',
  ebay: 'eBay',
  walmart: 'Walmart',
  shopee: 'Shopee',
  mercadolibre: 'Mercado Libre',
}

export const FIELD: Record<string, string> = {
  name: '商品名称',
  title: '标题',
  brand: '品牌',
  asin: 'ASIN',
  price: '价格',
  currency: '币种',
  rating: '评分',
  review_count: '评论数',
  category: '类目',
  key_features: '核心卖点',
  specifications: '规格',
  materials: '材质',
  certifications: '认证',
  source_ref: '外部商品编号',
  is_demo: '示例数据',
  reviews: '评论样本',
  review_list: '评论样本',
  review_text: '评论内容',
  target_audience: '目标人群',
  brand_voice: '品牌语气',
  banned_terms: '禁用词',
  differentiators: '差异化卖点',
  bullets: '五点描述',
  bullet: '五点描述',
  description: '描述',
  search_terms: 'Search Terms',
  a_plus_outline: 'A+ 内容',
  a_plus: 'A+ 内容',
  image: '主图',
  video: '视频',
  copy: '文案',
  keywords: '关键词',
  keyword: '关键词',
  language: '语言',
  marketplace: '站点',
  listing: '整篇文案',
  platform: '平台',
  user_input: '你填写的内容',
  manual: '你填写的内容',
  import: '导入文件',
  report_id: '分析报告',
  listing_id: 'Listing 草稿',
  target_platform: '平台',
  own_specs: '你的规格',
  own_key_features: '你的卖点',
  own_price: '你的价格',
  filename: '文件名',
  content_base64: '文件',
  allow_partial_rows: '允许部分行出错',
  selling_price: '单件售价',
  purchase_cost: '采购成本',
  shipping_cost: '头程运费',
  packaging_cost: '包装耗材',
  fulfillment_fee: '履约配送费',
  other_cost: '其他成本',
  ad_cost_per_order: '广告摊销（每单）',
  commission_rate: '平台佣金率',
  return_rate: '退货率',
  return_handling_cost: '退货处理成本',
  fixed_cost: '一次性投入',
  target_margin: '目标毛利率',
  fulfillment: '履约方式',
  tone: '语气',
  locale: '站点语言',
  target_length_hint: '篇幅要求',
  data_source: '数据来源',
}

const VALUE: Record<string, string> = {
  'zh-CN': '中文',
  'en-US': '英文（美国）',
  short: '短',
  medium: '中',
  long: '长',
  fba: '平台仓配',
  fbm: '自发货',
  self: '国内直发',
  manual: '手动填写',
  demo: '示例数据',
  import: '导入文件',
}

const LEVEL: Record<string, string> = { high: '高', medium: '中', low: '低' }

const ORDER_STATUS: Record<string, string> = {
  pending: '待发货',
  unshipped: '待发货',
  partially_shipped: '部分发货',
  shipped: '已发货',
  delivered: '已送达',
  cancelled: '已取消',
  refunded: '已退款',
}

const RETURN_STATUS: Record<string, string> = {
  pending: '待审核',
  processing: '处理中',
  refunded: '已退款',
  rejected: '已拒绝',
}

export function value(raw: unknown): string {
  if (raw === null || raw === undefined || raw === '') return '—'
  const key = String(raw)
  // 枚举里既有 zh-CN 这类码，也有 amazon / fba 这类平台与履约方式的码，
  // 都走一遍才能保证下拉里不出现原始英文小写值。
  return (
    VALUE[key] ||
    LANGUAGE[key] ||
    SITE[key.toUpperCase()] ||
    PLATFORM[key.toLowerCase()] ||
    key
  )
}

export function level(raw: unknown): string {
  if (!raw) return '—'
  return LEVEL[String(raw).toLowerCase()] || String(raw)
}

export function platform(code: unknown): string {
  if (!code) return '—'
  return PLATFORM[String(code).toLowerCase()] || String(code)
}

/** 支持 "specifications.材质"、"bullet[1]" 这类写法：逐段翻译，翻不出的保留原样 */
export function field(key: unknown): string {
  if (!key) return ''
  return String(key)
    .split('.')
    .map((part) => {
      const m = part.match(/^(.*)\[(\d+)\]$/)
      if (m) {
        const base = FIELD[m[1]] || m[1]
        return `${base} · 第 ${Number(m[2])} 条`
      }
      return FIELD[part] || part
    })
    .join(' · ')
}

export function site(code: unknown): string {
  if (!code) return '—'
  const key = String(code).toUpperCase()
  return SITE[key] || String(code)
}

export function language(code: unknown): string {
  if (!code) return '—'
  if (LANGUAGE[code as string]) return LANGUAGE[code as string]
  const base = String(code).replace('_', '-').split('-')[0].toLowerCase()
  return LANGUAGE_BASE[base] || String(code)
}

export function taskType(kind: string): string {
  return TASK_TYPE[kind] || '任务'
}

export function taskResult(kind: string): string {
  return TASK_RESULT[kind] || '产出'
}

export function orderStatus(code: unknown): string {
  return ORDER_STATUS[String(code || '').toLowerCase()] || '处理中'
}

export function returnStatus(code: unknown): string {
  return RETURN_STATUS[String(code || '').toLowerCase()] || '处理中'
}

/** 状态 → 徽标色调，页面不必各自维护一份映射 */
export function orderTone(code: unknown): string {
  const key = String(code || '').toLowerCase()
  if (key === 'delivered') return 'ok'
  if (key === 'shipped' || key === 'partially_shipped') return 'brand'
  if (key === 'cancelled' || key === 'refunded') return 'muted'
  return 'warning'
}

export function returnTone(code: unknown): string {
  const key = String(code || '').toLowerCase()
  if (key === 'refunded') return 'ok'
  if (key === 'rejected') return 'muted'
  return 'warning'
}

export const labelApi = {
  SITE,
  LANGUAGE,
  TASK_TYPE,
  FIELD,
  site,
  language,
  platform,
  level,
  field,
  value,
  taskType,
  taskResult,
  orderStatus,
  returnStatus,
  orderTone,
  returnTone,
}
