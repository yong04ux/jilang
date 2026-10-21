/**
 * CrossPilot → DeepSeek Harness 工具插件（骨架）
 *
 * 状态：已用真实的 `@deepseek-ai/dsh-tools@0.0.1-rc.1` 与
 * `@deepseek-ai/cordis@4.x` 类型定义**通过 TypeScript 编译**；
 * 但**尚未在真实 Harness 宿主进程中加载运行**（见 README 的未验证事项）。
 *
 * 真实接口依据（已在本机 node_modules 的 .d.ts 中核对）：
 * - `@deepseek-ai/dsh-tools` 通过 `declare module '@deepseek-ai/cordis'` 增强 Context，
 *   因此必须导入该模块（下面的 import 不是多余的）；
 * - `defineTool({ name, description, parameters, output: { schema, render }, execute })`
 *   是官方推荐的写法，参数与输出均有类型推导与运行时校验；
 * - 参数用 `{ type: 'string', required: true }` 这样的 per-property 形式；
 * - 输出根用 `{ type: 'json' }` 表示不约束的 JSON 值。
 */

import type { Context } from '@deepseek-ai/cordis'
// 该导入同时引入 Context 的 `tools` 模块增强，不能删除。
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { JsonValue } from '@deepseek-ai/dsh-session'

export const name = 'crosspilot-tools'

/** 由 Cordis 配置系统校验的插件配置。 */
export interface Config {
  /** CrossPilot 服务地址，默认本地 8123 端口。 */
  baseUrl: string
  /** 单次请求超时毫秒数。 */
  timeoutMs: number
}

export const DEFAULT_CONFIG: Config = {
  baseUrl: 'http://127.0.0.1:8123',
  timeoutMs: 120_000,
}

const text = (value: string) => [{ type: 'text' as const, text: value }]

async function postJson(
  baseUrl: string,
  timeoutMs: number,
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<JsonValue> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const forwardAbort = () => controller.abort()
  signal?.addEventListener('abort', forwardAbort)
  try {
    const response = await fetch(`${baseUrl.replace(/\/+$/, '')}${path}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>
    if (!response.ok) {
      const detail = payload.detail
      throw new Error(
        `CrossPilot ${path} 返回 ${response.status}: ${
          typeof detail === 'string' ? detail : JSON.stringify(detail)
        }`,
      )
    }
    return payload as JsonValue
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', forwardAbort)
  }
}

export function apply(ctx: Context, config: Partial<Config> = {}) {
  const resolved: Config = { ...DEFAULT_CONFIG, ...config }

  ctx.tools.register(
    defineTool({
      name: 'crosspilot_analyze',
      description:
        '调用本地 CrossPilot 服务做竞品分析。输入商品信息与竞品评论，返回带证据分级' +
        '（fact/statistic/inference/assumption）的结构化报告。不会补全缺失字段；' +
        '缺少关键词指标时不会生成搜索量或排名。',
      parameters: {
        product_name: { type: 'string', required: true, description: '商品名称' },
        platform: {
          type: 'string',
          enum: ['amazon', 'ebay', 'walmart', 'shopee', 'mercadolibre'],
          description: '销售平台，默认 amazon',
        },
        marketplace: { type: 'string', description: '站点，例如 US / DE / JP' },
        category: { type: 'string' },
        own_specs: { type: 'json', description: '自有商品规格键值对象' },
        own_key_features: { type: 'array', items: { type: 'string' } },
        own_price: { type: 'number' },
        competitors: {
          type: 'array',
          items: { type: 'json' },
          required: true,
          description: '竞品数组，字段见 CrossPilot README',
        },
        keywords: { type: 'array', items: { type: 'json' } },
        data_source: { type: 'string', description: 'user_input / csv / demo' },
      },
      // `json` 根：不约束具体形状，但仍要求是合法 JSON 值
      output: {
        schema: { type: 'json' },
        render: (_args, value) => {
          const record = value as Record<string, unknown>
          const report = (record.report ?? {}) as Record<string, any>
          const provenance = (report.data_provenance ?? {}) as Record<string, any>
          const lines = [
            `竞品分析完成：${provenance.competitor_count ?? '?'} 个竞品 / ${provenance.review_sample_count ?? 0} 条评论样本`,
            `报告 ID：${report.report_id ?? '(未返回)'}`,
          ]
          if (provenance.is_demo) {
            lines.push('⚠️ 数据标记为 demo（模拟数据），不代表真实商品、销量或排名')
          }
          const warnings = (report.warnings ?? []) as string[]
          if (warnings.length) lines.push(`提示：${warnings.join('；')}`)
          return text(lines.join('\n'))
        },
      },
      timeoutMs: resolved.timeoutMs + 5_000,
      execute: async (args, exec) =>
        postJson(resolved.baseUrl, resolved.timeoutMs, '/api/analyze', args, exec.signal),
    }),
  )

  ctx.tools.register(
    defineTool({
      name: 'crosspilot_generate_listing',
      description:
        '调用本地 CrossPilot 服务生成商品 Listing（标题/五点/描述/A+ 大纲/Search Terms）。' +
        '所有商品事实必须来自 product 字段；缺失属性会进入 pending_confirmations。' +
        '返回包含质检问题、长度检查与合规免责声明，不能视为已完全合规。',
      parameters: {
        product: {
          type: 'object',
          additionalProperties: true,
          required: true,
          properties: {
            name: { type: 'string', required: true },
            brand: { type: 'string' },
            specifications: { type: 'json' },
            key_features: { type: 'array', items: { type: 'string' } },
            certifications: { type: 'array', items: { type: 'string' } },
            target_platform: { type: 'string' },
            marketplace: { type: 'string' },
            price: { type: 'number' },
            target_audience: { type: 'string' },
            banned_terms: { type: 'array', items: { type: 'string' } },
          },
        },
        language: { type: 'string' },
        marketplace: { type: 'string' },
        analysis_report_id: { type: 'string' },
        keywords: { type: 'array', items: { type: 'json' } },
        data_source: { type: 'string' },
      },
      output: {
        schema: { type: 'json' },
        render: (_args, value) => {
          const record = value as Record<string, unknown>
          const listing = (record.listing ?? {}) as Record<string, any>
          const quality = (listing.quality_check ?? {}) as Record<string, any>
          const pending = (listing.pending_confirmations ?? []) as string[]
          const issues = (quality.issues ?? []) as Array<Record<string, any>>
          const errors = issues.filter((issue) => issue.severity === 'error')
          const lines = [
            `Listing 已生成：${listing.title ?? '(无标题)'}`,
            `质检：${quality.passed ? '通过' : '存在 error 级问题'}`,
            `待确认项：${pending.length} 条`,
          ]
          if (errors.length) {
            lines.push('错误：' + errors.map((issue) => issue.message).join('；'))
          }
          if (quality.policy_disclaimer) lines.push(`合规提示：${quality.policy_disclaimer}`)
          return text(lines.join('\n'))
        },
      },
      timeoutMs: resolved.timeoutMs + 5_000,
      execute: async (args, exec) =>
        postJson(resolved.baseUrl, resolved.timeoutMs, '/api/listings/generate', args, exec.signal),
    }),
  )
}
