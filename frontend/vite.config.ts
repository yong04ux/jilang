/**
 * Vite 配置 —— 产物契约的唯一真源。
 *
 * 后端只认三个挂载点（backend/crosspilot/app.py:248-250）：
 *   /css   -> web_dir/css
 *   /js    -> web_dir/js
 *   /media -> web_dir/assets      ← 注意：URL 前缀是 /media，磁盘目录名是 assets
 * 以及 web_dir/index.html（backend/crosspilot/api/meta.py:29）。
 *
 * 因此构建产物必须是：dist/index.html + dist/css/* + dist/js/* + dist/assets/*
 * 而不是 Vite 默认的 dist/assets/*。以下四个插件就是为了守住这条契约。
 */
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { cpSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const dist = resolve(root, 'dist')

/** 7 个样式文件的固定顺序（与 index.html 里的加载顺序一致，顺序即级联优先级） */
const CSS_FILES = [
  'tokens',
  'base',
  'components',
  'layout',
  'pages',
  'store',
  'skills',
] as const

/**
 * index.html 里的样式与旧脚本必须「原样进、原样出」：
 *   - 样式要保留 ?v=0，好让 backend/crosspilot/api/meta.py:119 把占位符换成构建戳；
 *   - 旧脚本不能被 Vite 当模块处理。
 * 做法：transformIndexHtml 的 pre 阶段摘出来，post 阶段放回去。
 */
const slots = { css: '', legacy: '' }

const CSS_LINK_RE = /[ \t]*<link[^>]+?href="\/css\/[\w.-]+\.css[^"]*"[^>]*>\r?\n?/g
const LEGACY_SCRIPT_RE = /[ \t]*<script\s+src="\/js\/[^"]+"\s*><\/script>\r?\n?/g

function defaultCssLinks(): string {
  return CSS_FILES.map(
    (name) => `  <link rel="stylesheet" href="/css/${name}.css?v=0" />`,
  ).join('\n')
}

function htmlStrip(): Plugin {
  return {
    name: 'cp-html-strip',
    transformIndexHtml: {
      order: 'pre',
      handler(html) {
        slots.css = (html.match(CSS_LINK_RE) ?? []).join('').trim()
        slots.legacy = (html.match(LEGACY_SCRIPT_RE) ?? []).join('').trim()
        return html
          .replace(CSS_LINK_RE, '')
          .replace(LEGACY_SCRIPT_RE, '')
          .replace('</head>', '  <!--CP_CSS_SLOT-->\n</head>')
          .replace('</body>', '  <!--CP_LEGACY_SLOT-->\n</body>')
      },
    },
  }
}

function htmlRestore(): Plugin {
  return {
    name: 'cp-html-restore',
    transformIndexHtml: {
      order: 'post',
      handler(html) {
        // 一切 /css/*.css 的 query 归一成 ?v=0（契约：服务端做时间戳替换）
        const css = (slots.css || defaultCssLinks()).replace(
          /(href="\/css\/[\w.-]+\.css)\?[^"]*/g,
          '$1?v=0',
        )
        return html
          .replace('<!--CP_CSS_SLOT-->', indent(css))
          .replace(/[ \t]*<!--CP_LEGACY_SLOT-->/, indent(slots.legacy))
      },
    },
  }
}

/** 统一缩进：摘出来时被 trim 过，放回去时按两空格缩进，保持源码可读 */
function indent(block: string): string {
  if (!block) return ''
  return block
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .join('\n  ')
}

/**
 * 静态目录搬运：css/ -> dist/css，assets/ -> dist/assets。
 * 旧 js/ 目录已在 S8 删除，不再搬运。
 */
function copyStatic(): Plugin {
  return {
    name: 'cp-copy-static',
    apply: 'build',
    closeBundle() {
      cpSync(resolve(root, 'css'), resolve(dist, 'css'), { recursive: true })
      cpSync(resolve(root, 'assets'), resolve(dist, 'assets'), { recursive: true })
    },
  }
}

/** 开发期把 /media/x 映射到 /assets/x（生产由 FastAPI 的 mount 负责） */
function mediaAlias(): Plugin {
  return {
    name: 'cp-media-alias',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (req.url && req.url.startsWith('/media/')) {
          req.url = '/assets/' + req.url.slice('/media/'.length)
        }
        next()
      })
    },
  }
}

/**
 * 禁止从 TS/CSS import 图片与字体：Vite 会把它们输出成 /assets/xxx-hash.png，
 * 而 /assets 这个前缀后端没有挂载 → 404。图片一律放 frontend/assets 并用 /media/... 引用。
 */
function forbidBundleAssets(): Plugin {
  const FORBIDDEN = /\.(png|jpe?g|gif|svg|webp|avif|ico|woff2?|ttf|otf|eot)$/i
  return {
    name: 'cp-forbid-assets',
    apply: 'build',
    generateBundle(_opts, bundle) {
      for (const file of Object.values(bundle)) {
        if (file.type === 'asset' && FORBIDDEN.test(file.fileName)) {
          this.error(
            `禁止从 JS/CSS 引入静态资源（会产出 /assets/${file.fileName}，该前缀后端未挂载）。` +
              `请把文件放到 frontend/assets/ 并用 /media/... 绝对路径引用。`,
          )
        }
      }
    },
  }
}

export default defineConfig({
  root,
  base: '/',
  publicDir: false, // 资源全部由 copyStatic 搬运，避免与 dist/assets 语义混淆
  plugins: [
    react(),
    mediaAlias(),
    htmlStrip(),
    htmlRestore(),
    copyStatic(),
    forbidBundleAssets(),
  ],
  resolve: {
    alias: { '@': resolve(root, 'src') },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // 前后端同源的前提：Cookie 是 host-only（后端没设 domain），
      // 所以必须前后端都用同一个 host（统一 127.0.0.1）。
      '/api': {
        target: process.env.CP_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2020',
    sourcemap: false,
    manifest: false,
    rollupOptions: {
      input: resolve(root, 'index.html'),
      output: {
        entryFileNames: 'js/[name]-[hash].js',
        chunkFileNames: 'js/[name]-[hash].js',
        assetFileNames: (info) =>
          info.names?.[0]?.endsWith('.css') || info.name?.endsWith('.css')
            ? 'css/[name]-[hash][extname]'
            : 'assets/[name]-[hash][extname]',
      },
    },
  },
})
