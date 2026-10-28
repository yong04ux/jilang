#!/usr/bin/env node
/**
 * 产物契约校验：证明 dist/ 能被 FastAPI 的三个挂载点（app.py:248-250）与
 * 外壳路由（meta.py:29/113-119）直接消费，不需要改任何后端代码。
 *
 * 用法：node scripts/verify-build.mjs
 * 退出码 0 = 全通过；1 = 有失败项（会在 stderr 汇总）。
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const dist = resolve(root, 'dist')
const indexPath = join(dist, 'index.html')

const CSS_FILES = [
  'tokens',
  'base',
  'components',
  'layout',
  'pages',
  'store',
  'skills',
]

const failures = []
const notes = []

function check(ok, label, detail = '') {
  if (ok) {
    console.log(`  PASS  ${label}${detail ? '  ' + detail : ''}`)
  } else {
    console.log(`  FAIL  ${label}${detail ? '  ' + detail : ''}`)
    failures.push(`${label}${detail ? ' — ' + detail : ''}`)
  }
}

console.log('\nCrossPilot 产物契约校验\n' + '─'.repeat(56))

// 1. 外壳存在
check(existsSync(indexPath), 'dist/index.html 存在')
if (!existsSync(indexPath)) {
  console.error('\n致命：外壳缺失，后续检查跳过。先跑 npm run build。\n')
  process.exit(1)
}

const html = readFileSync(indexPath, 'utf8')

// 2. dist 顶层形状：只允许 index.html + css + js + assets
const topLevel = readdirSync(dist, { withFileTypes: true })
  .map((d) => (d.isDirectory() ? d.name + '/' : d.name))
  .sort()
const expectedTop = ['assets/', 'css/', 'index.html', 'js/']
check(
  JSON.stringify(topLevel) === JSON.stringify(expectedTop),
  'dist 顶层只有 index.html / css / js / assets',
  topLevel.join(' '),
)

// 3. 7 个样式 link 必须都带 ?v=0（meta.py:119 靠它注入构建戳）
//    注意：外壳里旧脚本也带 ?v=0，且注释文本里含 "?v=0" 字样，所以只统计 CSS link。
const cssStampCount = (html.match(/href="\/css\/[\w.-]+\.css\?v=0"/g) ?? []).length
check(cssStampCount === 7, '7 个样式 link 都带 ?v=0', `实际 ${cssStampCount}`)

// 4. 7 个样式文件都被引用且真实存在
const cssRefs = [...html.matchAll(/href="\/css\/([\w.-]+\.css)/g)].map((m) => m[1])
const missingCss = CSS_FILES.filter((n) => !cssRefs.includes(`${n}.css`))
check(
  missingCss.length === 0,
  '7 个样式文件全部被引用',
  missingCss.length ? `缺少 ${missingCss.join(', ')}` : cssRefs.length + ' 条',
)
const missingCssFiles = cssRefs.filter((f) => !existsSync(join(dist, 'css', f)))
check(
  missingCssFiles.length === 0,
  '被引用的样式文件都在 dist/css 里',
  missingCssFiles.length ? `缺少 ${missingCssFiles.join(', ')}` : '',
)

// 5. 不得出现后端没挂载的 /assets/ 前缀，也不得残留 /src/
const badAssets = (html.match(/["']\/assets\//g) ?? []).length
check(badAssets === 0, '外壳不含 /assets/ 前缀（该前缀未挂载）', `出现 ${badAssets} 次`)
const badSrc = (html.match(/["']\/src\//g) ?? []).length
check(badSrc === 0, '外壳不含 /src/ 开发路径', `出现 ${badSrc} 次`)

// 6. 至少一个模块脚本，且文件真实存在
const scriptRefs = [...html.matchAll(/<script[^>]+src="(\/js\/[^"?]+)/g)].map((m) => m[1])
const moduleScript = /<script[^>]+type="module"[^>]+src="(\/js\/[^"?]+)"/.exec(html)
check(Boolean(moduleScript), '外壳含 type="module" 的 /js/*.js 入口')
if (moduleScript) {
  check(
    existsSync(join(dist, moduleScript[1].replace(/^\/js\//, 'js/'))),
    '模块入口文件存在',
    moduleScript[1],
  )
}
const missingJs = scriptRefs.filter(
  (ref) => !existsSync(join(dist, ref.replace(/^\/js\//, 'js/'))),
)
check(
  missingJs.length === 0,
  '所有 /js/*.js 引用都能在 dist/js 找到',
  missingJs.length ? `缺少 ${missingJs.join(', ')}` : `${scriptRefs.length} 个`,
)

// 7. /media/x 引用的每个文件名都要在 dist/assets 里（URL 前缀 /media ↔ 目录 assets）
const mediaRefs = [...html.matchAll(/\/media\/([\w.-]+\.(?:svg|png|jpg|jpeg|webp|gif|ico))/gi)]
  .map((m) => m[1])
const missingMedia = [...new Set(mediaRefs)].filter(
  (f) => !existsSync(join(dist, 'assets', f)),
)
check(
  mediaRefs.length > 0 && missingMedia.length === 0,
  '/media/* 引用都能在 dist/assets 找到',
  missingMedia.length ? `缺少 ${missingMedia.join(', ')}` : `${mediaRefs.length} 条`,
)

// 8. 体量观察（不做硬门限，便于发现异常膨胀）
const kb = (p) => Math.round(readFileSync(p).length / 1024)
const jsDir = join(dist, 'js')
const jsFiles = existsSync(jsDir) ? readdirSync(jsDir).filter((f) => f.endsWith('.js')) : []
notes.push(`dist 体积：index.html ${kb(indexPath)} KB，js 文件 ${jsFiles.length} 个`)

console.log('─'.repeat(56))
for (const n of notes) console.log('  提示  ' + n)

if (failures.length) {
  console.error(`\n产物契约不通过：${failures.length} 项失败\n`)
  for (const f of failures) console.error('  - ' + f)
  console.error('')
  process.exit(1)
}

console.log('\nBUILD CONTRACT OK — 产物可被后端直接托管\n')
