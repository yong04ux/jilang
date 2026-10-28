/**
 * 数据来源提示条（可关闭，关闭状态记在 localStorage）。
 * 对应旧 shell.js:181-204。
 */
import { Icon } from '@/components/Icon'
import { useUiStore } from '@/stores/uiStore'

export function SourceBanner() {
  const dismissed = useUiStore((s) => s.bannerDismissed)
  const dismissBanner = useUiStore((s) => s.dismissBanner)

  return (
    <div
      className="source-banner"
      id="source-banner"
      role="status"
      hidden={dismissed}
    >
      <Icon name="info" />
      <span className="source-banner-text">
        <strong>示例数据</strong>
        　当前显示的商品、报告与任务里有示例内容，用来让你走通完整流程。导入你自己的文件或添加店铺后，这里就会换成你的数据。
      </span>
      <button
        type="button"
        className="source-banner-close"
        id="banner-close"
        aria-label="关闭提示"
        onClick={dismissBanner}
      >
        <Icon name="close" />
      </button>
    </div>
  )
}
