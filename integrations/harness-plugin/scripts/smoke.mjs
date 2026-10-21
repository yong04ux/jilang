/**
 * 插件运行期冒烟测试（不依赖真实 Harness 宿主）。
 *
 * 用 mock 的 Cordis Context 捕获 tools.register() 的调用，
 * 再用真实的 defineTool 运行参数校验与 execute，直连本地 CrossPilot 服务。
 *
 * 运行：node scripts/smoke.mjs（需先构建 plugins 并在 8123 端口启动服务）
 */

import { apply } from '../lib/index.js'
import { createServer } from 'node:http'

const PORT = Number(process.env.CROSSPILOT_PORT || 8123)
const BASE = `http://127.0.0.1:${PORT}`

const registered = []
const ctx = {
  tools: {
    register(definition) {
      registered.push(definition)
      return () => {}
    },
  },
}

apply(ctx, { baseUrl: BASE, timeoutMs: 30_000 })

if (registered.length !== 2) {
  console.error(`FAIL: 期望注册 2 个工具，实际 ${registered.length}`)
  process.exit(1)
}

const byName = Object.fromEntries(registered.map((tool) => [tool.name, tool]))
console.log('registered tools:', Object.keys(byName).join(', '))

// 1) schema 可投影为模型可见形式
for (const tool of registered) {
  if (!tool.name || !tool.description) throw new Error('tool 缺少 name/description')
  if (!tool.parameters || tool.parameters.type !== 'object') {
    throw new Error(`${tool.name} 的 parameters 未编译为 object schema`)
  }
  if (typeof tool.execute !== 'function') throw new Error(`${tool.name} 缺少 execute`)
  console.log(`  ${tool.name}: params=${Object.keys(tool.parameters.properties || {}).join(',')}`)
}

// 2) 真实调用分析接口
const analyze = byName.crosspilot_analyze
const analysisResult = await analyze.execute(
  {
    product_name: 'Smoke Bottle',
    platform: 'amazon',
    competitors: [
      {
        name: 'Comp A',
        price: 20,
        key_features: ['leak proof'],
        reviews: [{ rating: 1, text: 'The lid leaked after one week.' }],
        is_demo: true,
      },
    ],
    keywords: [{ keyword: 'bottle' }],
    data_source: 'demo',
  },
  { signal: new AbortController().signal },
)
const report = analysisResult.report
if (!report?.report_id) throw new Error('分析接口未返回 report_id')
console.log('analyze -> report_id:', report.report_id, 'pain_points:', report.review_insights.pain_points.length)

const rendered = analyze.output.render({}, analysisResult)
console.log('render(analyze):', rendered[0].text.split('\n')[0])

// 3) 真实调用 Listing 接口
const generate = byName.crosspilot_generate_listing
const listingResult = await generate.execute(
  {
    product: {
      name: 'Smoke Bottle',
      brand: 'SmokeBrand',
      specifications: {},
      key_features: ['double wall insulation'],
      certifications: [],
    },
    language: 'en-US',
    marketplace: 'US',
    analysis_report_id: report.report_id,
  },
  { signal: new AbortController().signal },
)
const listing = listingResult.listing
if (!listing?.listing_id) throw new Error('Listing 接口未返回 listing_id')
if (!listing.pending_confirmations.length) throw new Error('缺少待确认项，可能发生了事实补全')
console.log('listing -> id:', listing.listing_id, 'pending:', listing.pending_confirmations.length)
console.log('render(listing):', generate.output.render({}, listingResult)[0].text.split('\n')[0])

// 4) 错误路径：不存在的报告应抛错
let threw = false
try {
  await generate.execute(
    { product: { name: 'X' }, analysis_report_id: 'no-such-report' },
    { signal: new AbortController().signal },
  )
} catch (error) {
  threw = true
  console.log('error path ok:', String(error.message).slice(0, 80))
}
if (!threw) throw new Error('不存在的报告没有报错')

console.log('SMOKE PASS')
