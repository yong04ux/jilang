/**
 * 外壳 UI 状态：侧栏折叠 + 数据来源提示条关闭。
 *
 * 只承接旧 `CPStore` 的那一个实例（shell.js:17）。两个 localStorage 键与值格式
 * 必须保持 `"1"` / `"0"` —— 换格式会让老用户的折叠状态失效。
 */
import { create } from 'zustand'

const EXPAND_KEY = 'cp.sidebar.expanded'
const BANNER_KEY = 'cp.banner.dismissed'

function readFlag(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function writeFlag(key: string, on: boolean): void {
  try {
    localStorage.setItem(key, on ? '1' : '0')
  } catch {
    /* 隐私模式下写不了，忽略 */
  }
}

interface UiState {
  expanded: boolean
  bannerDismissed: boolean
  /** 窄屏全量导航抽屉是否展开（旧 shell.js 用局部变量 scrim 管理） */
  drawerOpen: boolean
  setExpanded(value: boolean): void
  dismissBanner(): void
  setDrawerOpen(open: boolean): void
}

export const useUiStore = create<UiState>((set, get) => ({
  expanded: readFlag(EXPAND_KEY),
  bannerDismissed: readFlag(BANNER_KEY),
  drawerOpen: false,
  setExpanded(value) {
    const next = Boolean(value)
    if (get().expanded === next) return
    writeFlag(EXPAND_KEY, next)
    set({ expanded: next })
  },
  dismissBanner() {
    writeFlag(BANNER_KEY, true)
    set({ bannerDismissed: true })
  },
  setDrawerOpen(open) {
    set({ drawerOpen: Boolean(open) })
  },
}))
