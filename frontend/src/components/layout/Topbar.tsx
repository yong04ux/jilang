/**
 * 顶栏 = 跑马灯状态条 + 编号条。
 *
 * 条上只放服务端真实回传的信号：分组、生成方式、任务执行服务、版本号。
 * 跑马灯不做装饰性滚动——它滚的是「你现在用的是什么」。
 *
 * 保留的 id 是对外契约，别改：
 *   #nav-open        —— 窄屏抽屉入口
 *   #provider-flag   —— 生成方式标识
 *   #crumb           —— 面包屑容器
 */
import { useAuthStore } from '@/stores/authStore'
import { useHealthStore, providerFlagText } from '@/lib/health/health'

/** 生成方式标识的语气 → 跑马灯条上的撞色 */
const FLAG_TONE: Record<'ok' | 'warn' | 'plain', 'alert' | 'live' | 'muted'> = {
  warn: 'alert',
  ok: 'live',
  plain: 'muted',
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
  const me = useAuthStore((s) => s.me)
  const user = useAuthStore((s) => s.user)

  const nav = window.CPCatalog?.NAV ?? []
  let current = ''
  let group = ''
  for (const g of nav) {
    for (const item of g.items) {
      if (item.key === activeKey) {
        current = item.label
        group = g.group
      }
    }
  }

  const flag = providerFlagText(health, failed)
  const worker = health?.worker ?? {}
  const tickerFacts = [
    group || '工作空间',
    `生成方式 ${flag.text}`,
    `任务执行 ${worker.alive === false ? '暂不可用' : '正常'}`,
    health?.version ? `版本 ${health.version}` : '',
  ].filter(Boolean).join('　·　')

  const account = me?.display_name || me?.username || user?.username || ''

  return (
    <>
      <div className="ticker">
        <button
          type="button"
          id="nav-open"
          className="nav-open-btn"
          aria-label="打开全部导航"
          aria-expanded={drawerOpen ? 'true' : 'false'}
          aria-haspopup="dialog"
          onClick={onOpenDrawer}
        >
          ☰
        </button>

        <span
          id="provider-flag"
          className="ticker-seg"
          data-tone={FLAG_TONE[flag.tone]}
          title={flag.title}
        >
          {flag.text}
        </span>

        <div className="ticker-marq" aria-hidden="true">
          <span>{`${tickerFacts}　·　`.repeat(4)}</span>
        </div>

        <div className="ticker-right">
          {account ? (
            <span className="ticker-seg" data-tone="muted">{account}</span>
          ) : null}
          <a className="ticker-cta" href="/workbench" data-link="">
            AI 助手
          </a>
        </div>
      </div>

      <div className="crumb-bar">
        <nav id="crumb" aria-label="面包屑">
          <a className="crumb-root" href="/dashboard" data-link="">
            {group || '工作空间'}
          </a>
          <span className="crumb-sep" aria-hidden="true">/</span>
          <span className="crumb-current">{current}</span>
        </nav>
      </div>
    </>
  )
}
