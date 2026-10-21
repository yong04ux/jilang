// Vercel 构建：把单一前端（frontend/）拷贝到 frontend/dist/。
// 只做静态资源搬运，不做打包 —— 前端是原生 ES5 + 静态 CSS，无需 bundler，
// 这样部署产物与本地开发看到的文件完全一致。
//
// monorepo 布局：本脚本位于 frontend/scripts/，站点根即 frontend/ 本身；
// scripts/ 是开发诊断工具，不进部署产物，故按条目白名单拷贝。
import { cpSync, rmSync, mkdirSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const projectRoot = join(root, '..')
const dist = join(projectRoot, 'dist')

// 站点内容白名单：index.html + css/js/assets（favicon 等在 assets/ 内，经 /media 暴露）
const ENTRIES = ['index.html', 'css', 'js', 'assets']

rmSync(dist, { recursive: true, force: true })
mkdirSync(dist, { recursive: true })

for (const name of ENTRIES) {
  const src = join(projectRoot, name)
  if (!existsSync(src)) {
    console.error(`找不到前端条目：${src}`)
    process.exit(1)
  }
  cpSync(src, join(dist, name), { recursive: true })
}

// assets 目录对外暴露为 /media（与本地 FastAPI 的 mount 路径一致）
cpSync(join(dist, 'assets'), join(dist, 'media'), { recursive: true })

console.log('Vercel 构建完成：frontend/dist/ 已包含 index.html / css / js / media')
