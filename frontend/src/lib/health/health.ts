/**
 * /api/health 的共享缓存。
 *
 * 语义逐字保留旧 `CPShell.getHealth`（shell.js:48-69）：
 *  - 模块级单个 Promise，15s TTL 内复用同一个 Promise（顶栏 / 工作台 / 设置页共用，
 *    首屏只发一次请求）；
 *  - `force` 跳过 TTL；
 *  - 请求失败时清空缓存，让下一次调用重新发起；
 *  - `invalidateHealth()` 主动失效（设置页保存密钥后要用）。
 *
 * 这里刻意**不用** TanStack Query：它的 staleTime/refetch 语义与「同一个 Promise」
 * 不等价，会让首屏多打一次请求。
 */
import { create } from 'zustand'
import { api } from '@/lib/api'

export interface ProviderInfo {
  name?: string
  model?: string
  available?: boolean
  verified?: boolean
  detail?: string
  fallback_reason?: string
}

export interface HealthInfo {
  status?: string
  version?: string
  brand?: string
  provider?: ProviderInfo
  requires_api_key?: boolean
  worker?: { backend?: string; alive?: boolean; redis?: boolean | null }
  marketplace_mode?: string
}

const HEALTH_TTL_MS = 15000

let healthPromise: Promise<HealthInfo> | null = null
let healthFetchedAt = 0

export function getHealth(force = false): Promise<HealthInfo> {
  const now = Date.now()
  if (!force && healthPromise && now - healthFetchedAt < HEALTH_TTL_MS) {
    return healthPromise
  }
  healthFetchedAt = now
  healthPromise = api.get<HealthInfo>('/api/health').catch((err: unknown) => {
    healthPromise = null
    healthFetchedAt = 0
    throw err
  })
  return healthPromise
}

export function invalidateHealth(): void {
  healthPromise = null
  healthFetchedAt = 0
}

interface HealthState {
  data: HealthInfo | null
  failed: boolean
  refresh(force?: boolean): Promise<void>
}

/** 顶栏与账号菜单订阅这一份，避免各自再发请求 */
export const useHealthStore = create<HealthState>((set) => ({
  data: null,
  failed: false,
  async refresh(force = false) {
    try {
      const data = await getHealth(force)
      set({ data, failed: false })
    } catch {
      set({ failed: true })
    }
  },
}))

/** 顶栏标识文案（与 shell.js:212-217 完全一致） */
export function providerFlagText(health: HealthInfo | null, failed: boolean): {
  text: string
  title: string
  tone: 'ok' | 'warn' | 'plain'
} {
  if (failed || !health) {
    return { text: '服务状态未知', title: '', tone: 'warn' }
  }
  const p = health.provider ?? {}
  const worker = health.worker ?? {}
  let name: string
  if (p.name === 'rule') name = '规则引擎'
  else name = (p.name || '未知') + (p.model ? ' · ' + p.model : '')
  if (!p.available) name += '（不可用）'
  else if (!p.verified) name += '（未验证）'

  let tone: 'ok' | 'warn' | 'plain' = 'plain'
  if (!p.available || p.fallback_reason) tone = 'warn'
  else if (p.available && p.verified) tone = 'ok'

  let title = p.detail || ''
  if (worker.alive === false) {
    tone = 'warn'
    title = ((p.detail || '') + ' · 任务执行服务暂时不可用').trim()
  }
  return { text: name, title, tone }
}
