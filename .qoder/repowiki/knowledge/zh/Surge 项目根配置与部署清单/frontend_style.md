## 1. 采用的样式系统

前端使用 **React + TypeScript + Vite**，样式层由三层构成：

- **Tailwind CSS v4**（`tailwindcss@^4.3.3`），通过 `@tailwindcss/cli` 单独编译，不走 Vite 的 CSS 管线。
- **shadcn/ui**（基于 Radix UI primitives，风格为 `new-york`），组件位于 `frontend/src/components/ui/`，通过 `components.json` 注册别名 `@/components/ui`。
- **手写 CSS**（`src/styles/*.css`），与 Tailwind 共存，覆盖 layout / pages / store / components 等页面级样式。

依赖还包括 `clsx`、`tailwind-merge`（用于 shadcn 组件的 className 合并）、`tw-animate-css`（动画）、`lucide-react`（图标）、`sonner`（通知）。

## 2. 关键文件

- `frontend/src/styles/tailwind.css` — Tailwind 入口，声明 `@theme inline` 并将所有颜色/圆角/阴影/字体/断点映射到 CSS 变量。
- `frontend/src/styles/tokens.css` — **设计令牌唯一真源**，定义品牌色 `#1B6EF3`、撞色板（酸柠/洋红/朱橙/电青/印章红）、语义色、硬投影、零圆角、三语体字体等。
- `frontend/src/styles/base.css` / `layout.css` / `pages.css` / `store.css` / `components.css` — 手写样式层，与 Tailwind 并列加载。
- `frontend/components.json` — shadcn/ui 配置（style: new-york, tsx, cssVariables, iconLibrary: lucide）。
- `frontend/vite.config.ts` — 构建契约：把 `src/styles/*.css` 原样复制到 `dist/css/`，禁止从 JS/CSS import 图片/字体（强制走 `/media/` 前缀）。
- `frontend/package.json` scripts 中 `build:css` 调用 `tailwindcss -i src/styles/tailwind.css -o css/tailwind.css --minify`，再由 Vite 拷贝到 dist。
- `frontend/src/lib/utils.ts` 暴露 `cn()` 工具函数（`clsx` + `twMerge`），供 shadcn 基元安全合并 className。

## 3. 架构约定

### 设计令牌分层
`tokens.css` 是唯一的视觉真源，定义原生 CSS 变量（如 `--paper`、`--ink`、`--primary`、`--acid-lime`、`--radius-cut`、`--hard-ink`）。`tailwind.css` 的 `@theme inline` 仅做映射（例如 `--color-primary: var(--primary)`），不新增数值。这样换主题只需改 `tokens.css`。

### Tailwind 不使用 `important` 模式
入口注释明确记录原因：官方 `important` 会把工具类的 `!important` 压掉行内 `style=`，导致已有页面的像素不一致。因此采用「不加 important，也不动既有 CSS」的策略，新旧类名不混写同一属性；必要时用 Tailwind 单点 `!` 前缀（如 `!p-0`）局部覆盖。该策略由 `scripts/tailwind-ab.mjs` 做 A/B 像素比对守护。

### 响应式断点
Tailwind 断点沿用旧值而非默认值，与 `layout.css` 中的三个断点对齐：`--breakpoint-shell: 981px`、`--breakpoint-wide: 1180px`、`--breakpoint-narrow: 720px`。

### shadcn/ui 集成
- 组件生成在 `components/ui/`，全部基于 Radix 无样式 base。
- 通过 `components.json` 注册路径别名：`@/components/ui` → `src/components/ui`，`@/lib/utils` → `src/lib/utils`。
- 组件统一通过 `cn(...)` 合并 className，保证外部传入的类名能正确覆盖。

### Vite 构建约束
- 手写样式源码在 `src/styles/`，产物仍输出到 `dist/css/<name>.css`，文件名固定，查询参数统一为 `?v=0`，由后端 `meta.py` 替换为构建戳做缓存失效。
- 静态资源（图片/字体）**禁止从 JS/CSS import**，必须放入 `frontend/assets/` 并通过 `/media/...` 引用，Vite 插件 `forbidBundleAssets` 会在构建时报错拦截。
- 开发期 `/media/*` 和 `/css/<手写样式>.css` 被中间件重定向到源码目录，生产期由 FastAPI mount 接管。

### 视觉风格要点（来自 tokens.css 注释）
- 底色为暖新闻纸（`--paper: #EFE9DC`），边框即主角（`--border: var(--ink)`）。
- 圆角全部归零，只保留切角 `--radius-cut: 0 0 18px 0` 和胶囊筛选。
- 阴影只有硬投影（模糊恒为 0）。
- 字体采用「三语体对撞」：display/sans/serif 并用，mono 管标签与数字。
- 语义色使用「软底+深字」模式（success/warning/destructive/info 均有 soft 变体）。

## 4. 约定与约束

- **令牌唯一真源**：`src/styles/tokens.css`。`tailwind.css` 只做映射，页面不得自造颜色/尺寸数值。（来源：`tokens.css` 头部注释 + `tailwind.css` 注释）
- **Tailwind 禁用全局 `important`**：避免覆盖行内 style，保持与旧样式逐像素一致。（来源：`tailwind.css` 注释 + `package.json` 脚本 `ab:tailwind`）
- **显式 `@source`**：Tailwind 扫描范围限定为 `../../src` 与 `../../index.html`，不扫描 backend 模板。（来源：`tailwind.css`）
- **`@theme inline`**：因为深色主题变量在 `:root` 与 `.dark` 中分别定义，非 inline 会提前展开 `var()` 导致深色失效。（来源：`tailwind.css`）
- **CSS 加载顺序即级联优先级**：`tokens → base → components → layout → pages → store → skills → tailwind`，Tailwind 排最后才能稳定胜出。（来源：`vite.config.ts` 中 `CSS_FILES` 数组）
- **禁止打包静态资源**：Vite 构建时若检测到 JS/CSS 中 import 了 png/jpg/svg/woff2 等文件，直接报错，强制改用 `/media/` 绝对路径。（来源：`vite.config.ts` 的 `forbidBundleAssets` 插件）
- **shadcn 组件 className 合并**：统一通过 `src/lib/utils.ts` 的 `cn()` 导出，对外部传入的类名进行合并。（来源：`utils.ts` 注释 + `components.json` 的 aliases）
- **Node 版本要求**：`engines.node >= 22.12.0`。（来源：`package.json`）
