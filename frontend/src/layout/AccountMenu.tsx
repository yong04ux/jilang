/**
 * 账号菜单：悬停展开、点击切换、Esc 收起并回焦、点击外部收起。
 * 行为逐条对齐旧 shell.js:349-406（含 160ms 悬停延迟关闭）。
 */
import { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/Icon'
import { useAuthStore } from '@/stores/authStore'
import { useHealthStore, providerFlagText } from '@/features/health/health'

export function AccountMenu() {
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

  /* 打开时淡入（旧实现是 CPMotion.fadeIn(menu, {y:4, duration:140})） */
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

  return (
    <div
      className="account-wrap"
      id="account-wrap"
      ref={wrapRef}
      onMouseEnter={openMenu}
      onMouseLeave={scheduleClose}
      onFocus={openMenu}
    >
      <button
        type="button"
        className="account-btn"
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
        <span className="account-avatar" id="account-avatar">
          {initial}
        </span>
        <span className="account-meta">
          <span className="account-name" id="account-name">
            {display}
          </span>
          <span className="account-role" id="account-role">
            {role}
          </span>
        </span>
      </button>

      <div
        className="account-menu"
        id="account-menu"
        role="menu"
        aria-label="账号"
        hidden={!open}
        ref={menuRef}
      >
        <div className="account-menu-head">
          <span className="account-menu-avatar" id="menu-avatar">
            {initial}
          </span>
          <span className="account-menu-id">
            <span className="account-menu-name" id="menu-name">
              {display}
            </span>
            <span className="account-menu-sub" id="menu-sub">
              {signedIn ? `${role} · ${username}` : '—'}
            </span>
          </span>
        </div>

        <div className="account-menu-card">
          <div className="account-menu-card-row">
            <span className="account-menu-card-label">智能助手</span>
            <span className="account-menu-card-value" id="menu-model">
              {providerText}
            </span>
          </div>
          <div className="account-menu-card-row">
            <span className="account-menu-card-label">任务执行</span>
            <span className="account-menu-card-value" id="menu-worker">
              {workerText}
            </span>
          </div>
        </div>

        <div className="account-menu-list">
          <a className="account-menu-item" role="menuitem" href="/settings" data-link="">
            <Icon name="settings" />
            <span>个人设置</span>
          </a>
          <a className="account-menu-item" role="menuitem" href="/stores" data-link="">
            <Icon name="stores" />
            <span>店铺与渠道</span>
          </a>
          <a className="account-menu-item" role="menuitem" href="/data" data-link="">
            <Icon name="data" />
            <span>数据资产</span>
          </a>
        </div>

        <div className="account-menu-sep" />

        <div className="account-menu-list">
          <button type="button" className="account-menu-item" role="menuitem" id="user-logout">
            <Icon name="logout" />
            <span>退出登录</span>
          </button>
        </div>
      </div>
    </div>
  )
}
