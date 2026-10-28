/**
 * 轻量 UI 工具 —— 转义、Toast、格式化、状态徽章。
 *
 * 旧页面（HTML 字符串渲染）与新组件（React）共用这一份：前者拿字符串，
 * 后者用 Icon 组件，底层都是同一套实现。
 *
 * Toast 仍是命令式的（往 body 里插节点）：它不属于任何页面子树，
 * 做成 React 组件反而要处理跨路由存活的宿主问题。
 *
 * 注意下面两个 import 带了 `.ts` 扩展名：scripts/primitives-parity.mjs 要用
 * Node 直接 import 本文件做语义对照，而 Node 的 ESM 解析要求显式扩展名。
 */
import { fadeIn, fadeOut } from './motion.ts'
import { svg } from './icons.ts'

export function esc(value: unknown): string {
  if (value === null || value === undefined) return ''
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function el(html: string): Element | null {
  const tpl = document.createElement('template')
  tpl.innerHTML = html.trim()
  return tpl.content.firstElementChild
}

export function $(sel: string, root?: ParentNode): Element | null {
  return (root ?? document).querySelector(sel)
}

export function $$(sel: string, root?: ParentNode): Element[] {
  return Array.from((root ?? document).querySelectorAll(sel))
}

/* ------------------------------------------------------------------ Toast */

let toastHost: HTMLElement | null = null

export function toast(message: string, tone?: 'ok' | 'danger'): void {
  if (!toastHost) {
    toastHost = document.createElement('div')
    toastHost.className = 'toast-host'
    toastHost.setAttribute('aria-live', 'polite')
    document.body.appendChild(toastHost)
  }
  const iconName = tone === 'danger' ? 'alert' : tone === 'ok' ? 'check' : 'info'
  const node = el(
    `<div class="toast ${tone === 'danger' ? 'toast-danger' : tone === 'ok' ? 'toast-ok' : ''}" role="status">` +
      `<span data-icon="${iconName}"></span><span>${esc(message)}</span></div>`,
  )
  if (!node) return
  const holder = node.querySelector('[data-icon]')
  if (holder) holder.innerHTML = svg(iconName, null)
  toastHost?.appendChild(node)
  void fadeIn(node, { y: 8 })
  window.setTimeout(() => {
    void fadeOut(node, { y: 4 })
  }, 3200)
}

export async function copy(text: string, label?: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    toast((label || '内容') + '已复制', 'ok')
  } catch {
    toast('复制失败，请手动选择文本', 'danger')
  }
}

/* --------------------------------------------------------------- 格式化 */

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return ms + ' ms'
  const s = ms / 1000
  return (s >= 10 ? s.toFixed(0) : s.toFixed(1)) + ' s'
}

export function fmtBytes(bytes: number): string {
  return bytes + ' / 250'
}

export function byteLen(text: unknown): number {
  try {
    return new TextEncoder().encode(String(text || '')).length
  } catch {
    return String(text || '').length
  }
}

export function fmtTime(value: unknown): string {
  if (!value) return '—'
  const date = new Date(value as string)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  return ms < 1000 ? ms + ' ms' : (ms / 1000).toFixed(1) + ' s'
}

/* ------------------------------------------------------------ 状态徽章 */

export interface StatusMeta {
  label: string
  cls: string
}

/** 12 个任务/步骤状态 → 文案与色调。后端状态全集见 services/tasks.py:24-41 */
export const STATUS: Record<string, StatusMeta> = {
  queued: { label: '排队中', cls: 'badge' },
  running: { label: '运行中', cls: 'badge badge-running' },
  awaiting_approval: { label: '等待审批', cls: 'badge badge-warn' },
  waiting_for_input: { label: '等待补充资料', cls: 'badge badge-warn' },
  waiting_for_review: { label: '等待确认', cls: 'badge badge-warn' },
  partial: { label: '待复核', cls: 'badge badge-warn' },
  succeeded: { label: '已完成', cls: 'badge badge-ok' },
  failed: { label: '失败', cls: 'badge badge-danger' },
  cancelling: { label: '正在取消', cls: 'badge badge-warn' },
  cancelled: { label: '已取消', cls: 'badge' },
  pending: { label: '等待中', cls: 'badge' },
  skipped: { label: '已跳过', cls: 'badge' },
}

export function statusBadge(status: string): string {
  const meta = STATUS[status] || STATUS.queued
  return `<span class="${meta.cls}">${esc(meta.label)}</span>`
}

export function statusLabel(status: string): string {
  return (STATUS[status] || STATUS.queued).label
}

/* ----------------------------------------------------------------- 杂项 */

export function icon(name: string, cls?: string): string {
  return svg(name, null, cls)
}

export function mockFlag(): string {
  return '<span class="mock-flag" title="示例数据，不是你店铺的真实经营数据">示例</span>'
}

export const uiApi = {
  esc,
  el,
  $,
  $$,
  toast,
  copy,
  fmtMs,
  fmtBytes,
  fmtTime,
  fmtDuration,
  byteLen,
  statusBadge,
  statusLabel,
  icon,
  mockFlag,
  STATUS,
}
