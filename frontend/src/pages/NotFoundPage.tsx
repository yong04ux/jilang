/**
 * 404 页：沿用旧 `CPPages.notFound`，只换挂载方式。
 */
import { LegacyPage } from '@/legacy/LegacyPage'
import { normalize } from '@/app/router'
import type { LegacyPageLoader } from '@/types/global'

const notFoundLoader: LegacyPageLoader = (root) => {
  const path = normalize(location.pathname)
  return window.CPPages?.notFound(root, path)
}

export function NotFoundPage() {
  return <LegacyPage loader={notFoundLoader} params={{}} query={{}} />
}
