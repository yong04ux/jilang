/** 账号菜单：悬停展开、点击切换、Esc 收起并回焦、点击外部收起（含 160ms 悬停延迟关闭）。
 *
 * 展开态由 `expanded` prop 决定：
 *   - 图标栏：按钮只留头像，菜单弹在侧栏右侧，底边与按钮底对齐；
 *   - 文字栏：按钮显示姓名+角色，菜单弹在按钮上方。
 *
 * 保留的 id 是 App.tsx 的 document 点击委托依赖的锚点，别改：
 *   #account-wrap #user-chip #account-avatar #account-name #account-role
 *   #account-menu #menu-avatar #menu-name #menu-sub #menu-model #menu-worker #user-logout
 */
import { useEffect, useRef, useState } from 'react'
import { Database, LogOut, Settings2, Store } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { useHealthStore, providerFlagText } from '@/lib/health/health'
import { cn } from '@/lib/utils'

export function AccountMenu({ expanded }: { expanded: boolean }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const chipRef = useRef<HTMLButtonElement>(null)
  const timerRef = useRef<number | null>(null)

  const user = useAuthStore((s) => s.user)
  const me = useAuthStore((s) => s.me)
  const health = useHealthStore((s) => s.data)
  const failed = useHealthStore((s) => s.failed)

  const signedIn = Boolean(user)
  const display = signedIn
    ? me?.display_name || me?.username || user?.username || '—'
    : '未登录'
  const role = !signedIn
    ? '—'
    : me?.is_admin
      ? '管理员'
      : me?.is_guest
        ? '临时账号'
        : '成员'
  const initial = signedIn ? String(display).slice(0, 1).toUpperCase() : '·'
  const username = me?.username || user?.username || '—'

  const flag = providerFlagText(health, failed)
  const providerText = failed
    ? '未知'
    : health
      ? health.provider?.available
        ? flag.text
        : '未配置'
      : '检查中…'
  const workerText = failed
    ? '未知'
    : health
      ? health.worker?.alive === false
        ? '暂不可用'
        : '正常'
      : '检查中…'

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const openMenu = () => {
    clearTimer()
    setOpen((prev) => (prev ? prev : true))
  }

  const closeMenu = (restoreFocus: boolean) => {
    setOpen(false)
    if (restoreFocus) chipRef.current?.focus()
  }

  const scheduleClose = () => {
    clearTimer()
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      setOpen(false)
    }, 160)
  }

  /* 打开时淡入（现有实现是 CPMotion.fadeIn(menu, {y:4, duration:140})） */
  useEffect(() => {
    if (!open) return
    const menu = menuRef.current
    if (menu && window.CPMotion) window.CPMotion.fadeIn(menu, { y: 4, duration: 140 })
  }, [open])

  useEffect(() => {
    const onDocClick = (event: MouseEvent) => {
      const target = event.target as Element | null
      const box = wrapRef.current
      if (!box) return
      const hitItem = target?.closest?.('#account-menu a, #account-menu #user-logout')
      if (hitItem || !box.contains(target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeMenu(true)
    }
    document.addEventListener('click', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', onDocClick)
      document.removeEventListener('keydown', onKey)
      clearTimer()
    }
  }, [])

  const itemClass =
    'flex h-[34px] w-full items-center gap-2.5 rounded-sm px-2 text-left text-[13px] text-[var(--ink-soft)] transition-colors hover:bg-accent hover:text-foreground [&_svg]:size-[15px] [&_svg]:shrink-0 [&_svg]:text-muted-foreground hover:[&_svg]:text-foreground'

  return (
    <div
      className="relative w-full"
      id="account-wrap"
      ref={wrapRef}
      onMouseEnter={openMenu}
      onMouseLeave={scheduleClose}
      onFocus={openMenu}
    >
      <button
        type="button"
        className={cn(
          'flex h-9 w-full items-center rounded-md transition-colors hover:bg-accent',
          expanded ? 'justify-start gap-2 px-2' : 'justify-center px-1.5',
        )}
        id="user-chip"
        title="当前账号"
        aria-haspopup="menu"
        aria-expanded={open ? 'true' : 'false'}
        aria-controls="account-menu"
        aria-label={signedIn ? `账号 ${username}，打开账号菜单` : '当前账号'}
        ref={chipRef}
        onClick={(event) => {
          event.preventDefault()
          if (open) closeMenu(false)
          else openMenu()
        }}
      >
        <span
          className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground"
          id="account-avatar"
        >
          {initial}
        </span>
        {expanded ? (
          <span className="flex min-w-0 flex-col text-left">
            <span
              className="truncate text-xs font-medium leading-tight text-foreground"
              id="account-name"
            >
              {display}
            </span>
            <span className="truncate text-[10px] leading-tight text-muted-foreground" id="account-role">
              {role}
            </span>
          </span>
        ) : null}
      </button>

      <div
        className={cn(
          'absolute z-200 w-[292px] rounded-xl border border-border bg-card p-1.5 shadow-lg',
          // 图标栏：弹在侧栏右侧；文字栏：弹在按钮上方（避免超出视口右缘）
          expanded ? 'bottom-[calc(100%+8px)] left-0' : 'bottom-[-4px] left-[calc(100%+10px)]',
        )}
        id="account-menu"
        role="menu"
        aria-label="账号"
        hidden={!open}
        ref={menuRef}
      >
        <div className="flex items-center gap-2.5 px-2 pb-2.5 pt-2">
          <span
            className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary text-[15px] font-semibold text-primary-foreground"
            id="menu-avatar"
          >
            {initial}
          </span>
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate text-sm font-semibold text-foreground" id="menu-name">
              {display}
            </span>
            <span className="truncate text-xs text-muted-foreground" id="menu-sub">
              {signedIn ? `${role} · ${username}` : '—'}
            </span>
          </span>
        </div>

        <div className="mx-1 mb-1.5 flex gap-3 rounded-lg bg-muted px-3 py-2.5">
          <div className="flex min-w-0 flex-1 flex-col gap-[3px]">
            <span className="text-xs text-muted-foreground">智能助手</span>
            <span className="truncate text-[13px] font-medium text-foreground" id="menu-model">
              {providerText}
            </span>
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-[3px] border-l border-border pl-3">
            <span className="text-xs text-muted-foreground">任务执行</span>
            <span className="truncate text-[13px] font-medium text-foreground" id="menu-worker">
              {workerText}
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-px px-0.5">
          <a className={itemClass} role="menuitem" href="/settings" data-link="">
            <Settings2 />
            <span>个人设置</span>
          </a>
          <a className={itemClass} role="menuitem" href="/stores" data-link="">
            <Store />
            <span>店铺与渠道</span>
          </a>
          <a className={itemClass} role="menuitem" href="/data" data-link="">
            <Database />
            <span>数据资产</span>
          </a>
        </div>

        <div className="mx-2 my-1.5 h-px bg-border" />

        <div className="flex flex-col gap-px px-0.5">
          <button type="button" className={itemClass} role="menuitem" id="user-logout">
            <LogOut />
            <span>退出登录</span>
          </button>
        </div>
      </div>
    </div>
  )
}
