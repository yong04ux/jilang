/**
 * 外壳 UI 状态：数据来源提示条关闭 + 全量导航抽屉。
 *
 * localStorage 键与值格式必须保持 `"1"` / `"0"` —— 换格式会让老用户的偏好失效。
 * 侧栏折叠位已随竖排书脊一起退场：书脊只有一种宽度，没有可折叠的展开态。
 */
import { create } from 'zustand'

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
  bannerDismissed: boolean
  /** 窄屏全量导航抽屉是否展开（旧 shell.js 用局部变量 scrim 管理） */
  drawerOpen: boolean
  dismissBanner(): void
  setDrawerOpen(open: boolean): void
}

export const useUiStore = create<UiState>((set) => ({
  bannerDismissed: readFlag(BANNER_KEY),
  drawerOpen: false,
  dismissBanner() {
    writeFlag(BANNER_KEY, true)
    set({ bannerDismissed: true })
  },
  setDrawerOpen(open) {
    set({ drawerOpen: Boolean(open) })
  },
}))
