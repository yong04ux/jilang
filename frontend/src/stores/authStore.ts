/**
 * 会话状态与登录动作。
 *
 * 对应旧 `js/auth.js` 的状态部分：currentUser / allowRegister / demoAccount / guestTtl。
 * 渲染由 `layout/AuthGate.tsx` 负责，这里只管状态与接口调用，两边不混。
 *
 * `gateOpen` 独立于 `user`：现有实现在 401 时只把登录门亮出来、并不清 user
 * （app.js:108-114 先读 wasSignedIn 再 show），行为上必须一致。
 */
import { create } from 'zustand'
import { api } from '@/lib/api'

export interface AuthUser {
  username: string
  display_name?: string
  is_admin?: boolean
  is_guest?: boolean
}

interface AuthStatus {
  authenticated?: boolean
  user?: AuthUser | null
  allow_registration?: boolean
  demo_account?: boolean
  guest_ttl_hours?: number
  needs_setup?: boolean
}

interface AuthState {
  user: AuthUser | null
  /** 账号菜单里的显示名/角色，来自 /api/auth/me */
  me: AuthUser | null
  gateOpen: boolean
  gateError: string | null
  allowRegister: boolean
  demoAccount: boolean
  guestTtl: number
  needsSetup: boolean
}

export const useAuthStore = create<AuthState>(() => ({
  user: null,
  me: null,
  gateOpen: false,
  gateError: null,
  allowRegister: false,
  demoAccount: false,
  guestTtl: 24,
  needsSetup: false,
}))

/** 把底层错误翻成用户能照着做的下一步；服务端已经是中文就不动它（auth.js:50） */
export function friendly(err: unknown): string {
  const raw = (err as { message?: string } | null)?.message || ''
  if (!raw) return '操作没有完成，请重试一次。'
  if (/Failed to fetch|NetworkError|Load failed|网络/i.test(raw)) {
    return '连不上服务，请检查网络后重试。'
  }
  return raw
}

export async function loadAuth(silent = false): Promise<AuthUser | null> {
  let status: AuthStatus
  try {
    status = await api.get<AuthStatus>('/api/auth/status')
  } catch {
    // 不把底层错误原文抛给用户
    if (!silent) {
      useAuthStore.setState({
        gateOpen: true,
        gateError: '暂时连不上服务，请稍后刷新页面重试。',
      })
    }
    return null
  }

  const user = status.authenticated ? status.user ?? null : null
  useAuthStore.setState({
    allowRegister: Boolean(status.allow_registration),
    demoAccount: Boolean(status.demo_account),
    guestTtl: Number(status.guest_ttl_hours) || 24,
    needsSetup: Boolean(status.needs_setup),
    user,
    gateOpen: !user,
    gateError: null,
  })
  return user
}

/** 只亮登录门并显示错误，不动 user（401 场景要保留 wasSignedIn 的判断依据） */
export function showGate(errorText?: string | null): void {
  useAuthStore.setState({ gateOpen: true, gateError: errorText ?? null })
}

export async function logout(): Promise<void> {
  try {
    await api.post('/api/auth/logout', {})
  } catch {
    /* 退出失败也要把界面切回登录门，否则用户卡在页面模块上 */
  }
  useAuthStore.setState({ user: null, me: null, gateOpen: true, gateError: null })
  window.dispatchEvent(new CustomEvent('cp:logout'))
}

/** 账号菜单显示名 / 角色 / 头像首字母（shell.js:244-272） */
export async function loadMe(): Promise<void> {
  if (!useAuthStore.getState().user) return
  try {
    const data = await api.get<{ user?: AuthUser }>('/api/auth/me')
    useAuthStore.setState({ me: data.user ?? null })
  } catch {
    /* 会话失效由全局 401 处理器接管 */
  }
}
