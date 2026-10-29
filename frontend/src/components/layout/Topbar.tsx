/**
 * 顶栏：抽屉开关 + 面包屑 + 生成方式标识 + AI 助手入口。
 *
 * 本轮（Phase 3）从 layout.css 的 `.topbar-*` / `.crumb*` / `.proto-flag`
 * / `.pill-action` 改写成 Tailwind，样式规则同步从 layout.css 删除，
 * 避免两套并存互相压。
 *
 * 保留的 id 是**对外契约**，别改：
 *   #nav-open        —— 移动端抽屉入口（ui_shots_auth 会点它）
 *   #provider-flag   —— 生成方式标识（ui_settings_models 比对文案变化）
 *   #crumb           —— 面包屑容器
 *
 * 断点用 tailwind.css 里定义的 shell/wide/narrow，取值与原 CSS 一致。
 */
import { Info, Menu, TriangleAlert } from 'lucide-react'
import { useHealthStore, providerFlagText } from '@/lib/health/health'
import { cn } from '@/lib/utils'

/** 生成方式标识的三种语气 → 语义色描边（与 Alert 的语气一致） */
const FLAG_TONE: Record<string, string> = {
  warn: 'border-warning-line bg-warning-soft text-warning',
  ok: 'border-success-line bg-success-soft text-success',
  neutral: 'border-border bg-card text-muted-foreground',
}

export function Topbar({
  activeKey,
  drawerOpen,
  onOpenDrawer,
}: {
  activeKey: string
  drawerOpen: boolean
  onOpenDrawer: () => void
}) {
  const health = useHealthStore((s) => s.data)
  const failed = useHealthStore((s) => s.failed)

  const nav = window.CPCatalog?.NAV ?? []
  const labels: Record<string, string> = {}
  nav.forEach((g) => g.items.forEach((i) => (labels[i.key] = i.label)))
  const current = labels[activeKey] || activeKey

  const flag = providerFlagText(health, failed)
  const FlagIcon = flag.tone === 'warn' ? TriangleAlert : Info

  return (
    <>
      <div className="flex min-w-0 items-center gap-1.5">
        {/* 桌面端图标栏常驻，这个入口是冗余的 —— 与原 CSS 的 @media (min-width:981px) 等价 */}
        <button
          type="button"
          id="nav-open"
          aria-label="打开全部导航"
          aria-expanded={drawerOpen ? 'true' : 'false'}
          onClick={onOpenDrawer}
          className="shell:hidden -ml-1 inline-flex size-7 items-center justify-center rounded-sm text-foreground transition-colors hover:bg-accent"
        >
          <Menu className="size-4" />
        </button>

        <nav
          id="crumb"
          aria-label="面包屑"
          className="max-narrow:hidden flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground"
        >
          <a href="/dashboard" data-link="" className="transition-colors hover:text-foreground">
            工作空间
          </a>
          <span aria-hidden="true" className="text-border-strong">
            /
          </span>
          <span className="truncate font-medium text-foreground">{current}</span>
        </nav>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <span
          id="provider-flag"
          title={flag.title}
          className={cn(
            'inline-flex h-6 max-w-64 items-center gap-1.5 truncate rounded-sm border px-2 text-[11px] font-medium whitespace-nowrap',
            'max-narrow:max-w-[132px]',
            FLAG_TONE[flag.tone] ?? FLAG_TONE.neutral,
          )}
        >
          <FlagIcon className="size-3 shrink-0" aria-hidden="true" />
          <span className="truncate">{flag.text}</span>
        </span>

        <a
          href="/workbench"
          data-link=""
          className="inline-flex h-7 items-center gap-1.5 rounded-sm bg-foreground px-2.5 text-xs font-medium text-background transition-colors hover:bg-[#262626]"
        >
          <span className="max-shell:hidden">AI 助手</span>
          <span className="hidden max-shell:inline">AI</span>
        </a>
      </div>
    </>
  )
}
