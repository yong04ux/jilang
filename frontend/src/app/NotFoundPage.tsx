/**
 * 404 页 —— 从旧 `js/pages/misc.js:89-98` 迁移。
 *
 * 文案纪律：不解释「为什么还没做」，只给出现在能去哪。
 */
import { Icon } from '@/components/shared/Icon'
import { PageFrame, PageShell } from '@/components/shared/PageShell'

export function NotFoundPage() {
  return (
    <PageFrame>
      <PageShell
        title="页面不存在"
        desc="这个地址没有对应的页面，可能是链接过期，或者地址输错了。"
        actions={
          <a className="btn btn-secondary btn-sm" href="/dashboard" data-link="">
            回到工作台
          </a>
        }
      >
        <div className="card">
          <div className="empty">
            <span className="empty-icon">
              <Icon name="search" />
            </span>
            <p className="empty-title">没有找到这个页面</p>
            <p className="empty-desc">可以从左侧导航重新进入，或者回到工作台继续。</p>
          </div>
        </div>
      </PageShell>
    </PageFrame>
  )
}
