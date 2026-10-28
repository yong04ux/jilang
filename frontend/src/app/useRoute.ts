import { useSyncExternalStore } from 'react'
import { getRouterSnapshot, subscribeRouter } from './router'

/** 订阅路由快照；服务端快照与客户端一致（本项目不做 SSR） */
export function useRouteSnapshot() {
  return useSyncExternalStore(subscribeRouter, getRouterSnapshot, getRouterSnapshot)
}
