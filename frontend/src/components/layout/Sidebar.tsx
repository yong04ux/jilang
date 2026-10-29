/**
 * 侧栏：68px 图标栏，可展开成 224px 文字导航。
 *
 * 展开态由 `expanded` 状态经条件类名表达，不依赖父级选择器。
 */

import { cn } from '@/lib/utils'
import { useShellNarrow } from '@/hooks/useMediaQuery'
import { useUiStore } from '@/stores/uiStore'
import { Icon } from '@/components/shared/Icon'
import { AccountMenu } from './AccountMenu'

export function Sidebar({ activeKey }: { activeKey: string }) {
  const stored = useUiStore((s) => s.expanded)
  const setExpanded = useUiStore((s) => s.setExpanded)
  /* 窄屏强制退回图标栏（替代原 CSS 的 display:none !important）。
     注意用的不是 stored：抽屉打开时也不该把侧栏撑成 208px。 */
  const narrow = useShellNarrow()
  const expanded = stored && !narrow

  const nav = window.CPCatalog?.NAV ?? []
  const rail = window.CPCatalog?.RAIL_LABEL ?? {}
  const brandLabel = expanded ? '收起导航' : '展开导航'

  const toggle = () => {
    setExpanded(!stored)
    const brand = document.getElementById('sidebar-brand')
    if (brand && window.CPMotion) window.CPMotion.tap(brand)
  }

  return (
    <>
      <div
        className={cn(
          'flex shrink-0',
          expanded ? 'mb-2 h-9 flex-row items-center gap-2 px-1' : 'flex-col items-center pb-2',
        )}
      >
        <button
          type="button"
          className={cn(
            'flex items-center gap-2 rounded-md transition-colors hover:bg-accent',
            expanded ? 'h-9 flex-1 justify-start px-2' : 'size-11 justify-center',
          )}
          id="sidebar-brand"
          aria-expanded={expanded ? 'true' : 'false'}
          aria-label={brandLabel}
          title={brandLabel}
          onClick={toggle}
        >
          <img
            src="/media/logo-mark.svg?v=2"
            alt=""
            width={36}
            height={36}
            className={expanded ? 'h-[30px] w-auto' : 'size-9'}
          />
          {expanded ? (
            <span className="truncate text-sm font-semibold text-foreground">激浪</span>
          ) : null}
        </button>
      </div>

      <nav
        className={cn(
          'sidebar-nav flex w-full flex-1 flex-col overflow-y-auto overflow-x-hidden',
          '[scrollbar-width:none] [&::-webkit-scrollbar]:hidden',
          expanded ? 'items-stretch gap-px' : 'items-center gap-0.5',
        )}
        aria-label="主导航"
      >
        {nav.map((group, groupIndex) => (
          <div
            className={cn(
              'block w-full',
              // 图标栏里用细分隔线代替分组标题；展开态靠标题本身分隔
              !expanded && groupIndex > 0 && 'mt-1.5 border-t border-border pt-1.5',
            )}
            key={group.group}
          >
            {expanded ? (
              <div className="px-2 pb-1 pt-3.5 text-[11px] font-medium tracking-[.02em] text-faint whitespace-nowrap">
                {group.group}
              </div>
            ) : null}
            {group.items.map((item) => {
              const active = item.key === activeKey
              return (
                <a
                  className={cn(
                    'nav-item flex w-full items-center rounded-md transition-colors',
                    expanded
                      ? 'h-8 flex-row justify-start gap-2 px-2 text-[13px]'
                      : 'h-13 flex-col justify-center gap-[3px] px-0.5 text-[10px] leading-[1.2]',
                    active
                      ? 'bg-primary-soft font-semibold text-primary'
                      : 'font-medium text-muted-foreground hover:bg-accent hover:text-foreground',
                  )}
                  href={item.path}
                  data-link=""
                  data-nav={item.key}
                  title={item.label}
                  aria-current={active ? 'page' : undefined}
                  key={item.key}
                >
                  <span
                    className={cn(
                      'shrink-0',
                      expanded ? '[&_svg]:size-4' : '[&_svg]:size-[18px]',
                    )}
                  >
                    <Icon name={item.icon} />
                  </span>
                  <span
                    className={cn(
                      'max-w-full overflow-hidden text-ellipsis whitespace-nowrap',
                      expanded && 'min-w-0 flex-1',
                    )}
                  >
                    {expanded ? item.label : rail[item.key] || item.label}
                  </span>
                </a>
              )
            })}
          </div>
        ))}
      </nav>

      <div
        className={cn(
          'sidebar-foot flex w-full shrink-0 flex-col gap-0.5 border-t border-border pt-2',
          expanded ? 'items-stretch' : 'items-center',
        )}
      >
        <AccountMenu expanded={expanded} />
      </div>
    </>
  )
}
