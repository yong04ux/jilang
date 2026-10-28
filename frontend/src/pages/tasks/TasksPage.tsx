/**
 * 任务中心 —— 从旧 `js/pages/tasks.js` 迁移。
 *
 * 两条必须保住的行为：
 *  1. **抽屉改地址不重绘**：点行打开详情时只 `history.replaceState` 到 /tasks/{id}，
 *     不经过路由，所以列表不会重挂、滚动位置不丢；刷新该地址才是「列表 + 抽屉」。
 *  2. **运行中任务自动刷新**：抽屉打开时按 1s 轮询任务详情，终态后刷新列表。
 *     这里用的是 S3 修过的 poller（连续失败 5 次才放弃，而不是抖动一次就停）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '@/lib/api'
import { fmtTime, toast } from '@/lib/ui'
import { taskType } from '@/lib/labels'
import { Icon } from '@/components/Icon'
import { PageFrame, PageShell } from '@/components/PageShell'
import { StatusBadge } from '@/components/StatusBadge'
import { useTaskPolling } from '@/features/async-run/useTaskPolling'
import { isRunning } from '@/features/async-run/poller'

type Dict = Record<string, any>

const FILTERS: Array<{ key: string; label: string }> = [
  { key: '', label: '全部' },
  { key: 'running', label: '运行中' },
  { key: 'awaiting_approval', label: '等待审批' },
  { key: 'waiting_for_input', label: '等待补充资料' },
  { key: 'waiting_for_review', label: '等待确认' },
  { key: 'partial', label: '待复核' },
  { key: 'succeeded', label: '已完成' },
  { key: 'failed', label: '失败' },
  { key: 'cancelled', label: '已取消' },
]

/* 结果列的叫法：只有真的有产出才显示，否则 — */
const RESULT_LABEL: Record<string, string> = {
  competitor_analysis: '报告',
  listing_generation: '草稿',
  agent_workflow: '报告',
  publish_listing: '草稿',
  data_import: '批次',
}

const KIND_LABEL: Record<string, string> = {
  publish_listing: '发布 Listing',
}

function originLabel(origin?: string): string {
  return origin === 'chat' ? 'AI 助手' : origin === 'seed' ? '示例数据' : '业务页面'
}

/* ------------------------------------------------------------ 详情抽屉 */

function TaskDrawer({
  taskId,
  onClose,
  onListRefresh,
}: {
  taskId: string
  onClose: () => void
  onListRefresh: () => void
}) {
  const [detail, setDetail] = useState<Dict | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const stepsRef = useRef<HTMLDivElement>(null)

  const loadDetail = useCallback(async () => {
    try {
      const data = await api.get<Dict>(`/api/tasks/${encodeURIComponent(taskId)}`)
      setDetail(data)
      setLoadError(null)
    } catch (err) {
      setLoadError((err as Error).message || String(err))
    }
  }, [taskId])

  useEffect(() => {
    setDetail(null)
    setLoadError(null)
    void loadDetail()
  }, [loadDetail])

  const status = (detail?.task || {}).status || ''
  const running = Boolean(detail) && isRunning(status)

  useTaskPolling({
    taskId,
    enabled: running,
    onUpdate: (data) => setDetail(data as Dict),
    onDone: (data) => {
      setDetail(data as Dict)
      onListRefresh()
    },
    onError: () => {
      /* 单次失败继续轮询（poller 内部已处理），这里不打扰用户 */
    },
  })

  /* Esc 关闭（原实现是 document 级监听，关闭时移除） */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  /* 执行步骤由旧 CPAsyncRun.stepList 产出 HTML 字符串，补一次图标 hydrate */
  useEffect(() => {
    if (stepsRef.current) window.CPIcon?.hydrate(stepsRef.current)
  }, [detail])

  const task: Dict = detail?.task || {}
  const result: Dict = detail?.result || {}
  const pendingInfo: Dict | null =
    detail?.pending || result.pending || (task.output || {}).pending || null
  const canCancel = ['queued', 'running', 'cancelling'].includes(task.status)
  const approvalId = (task.output || {}).approval_id

  const decide = async (decision: 'approved' | 'rejected') => {
    setBusy(true)
    try {
      await api.post(`/api/approvals/${encodeURIComponent(approvalId)}/decide`, { decision })
      toast(decision === 'approved' ? '已通过（未实际发布）' : '已拒绝', 'ok')
      onClose()
      onListRefresh()
    } catch (err) {
      toast((err as Error).message, 'danger')
      setBusy(false)
    }
  }

  const confirmStep = async (decision: 'continue' | 'cancel') => {
    setBusy(true)
    try {
      // token 把「确认的是哪一次暂停」绑定住，防止拿着过期清单去确认
      const pendingNow = (task.output || {}).pending || {}
      await api.post(`/api/tasks/${encodeURIComponent(task.task_id)}/confirm`, {
        decision,
        confirmation_token: pendingNow.confirmation_token || '',
      })
      toast(decision === 'continue' ? '已继续生成' : '已取消', 'ok')
      onClose()
      onListRefresh()
    } catch (err) {
      toast((err as Error).message, 'danger')
      setBusy(false)
    }
  }

  const cancelTask = async () => {
    setBusy(true)
    try {
      const resp = await api.post<{ detail?: string }>(
        `/api/tasks/${encodeURIComponent(task.task_id)}/cancel`,
        {},
      )
      toast(resp?.detail || '已请求取消', 'ok')
    } catch (err) {
      toast((err as Error).message, 'danger')
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <>
      <div className="drawer-scrim" id="task-drawer-scrim" onClick={onClose} />
      <aside
        className="drawer is-wide"
        role="dialog"
        aria-modal="true"
        aria-label="任务详情"
      >
        <div className="drawer-head">
          <div className="task-detail-head">
            <span className="t-section">任务详情</span>
          </div>
          <button type="button" className="btn-icon" id="task-drawer-close" aria-label="关闭" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>

        <div className="drawer-body" id="task-drawer-body">
          {loadError ? (
            <div className="callout callout-danger">
              <Icon name="alert" />
              <div>
                <strong>任务加载失败</strong>
                <br />
                {loadError}
              </div>
            </div>
          ) : !detail ? (
            <>
              <div className="skeleton skeleton-line" />
              <div className="skeleton skeleton-line" />
            </>
          ) : (
            <>
              <div className="row between wrap gap-3">
                <div>
                  <div className="row gap-2 wrap">
                    <span className="t-title" style={{ fontSize: 'var(--fs-lg)' }}>
                      {task.title}
                    </span>
                    <StatusBadge status={task.status} />
                  </div>
                  <div className="t-xs t-muted mt-1">
                    {taskType(task.type)} · {fmtTime(task.created_at)}
                    {/* 如实标出这次是规则算的还是模型写的 */}
                    {result && result.engine ? ` · ${result.engine.label}` : ''}
                  </div>
                </div>
                <div className="row gap-2">
                  {canCancel ? (
                    <button type="button" className="btn btn-sm" id="task-cancel" disabled={busy} onClick={cancelTask}>
                      取消任务
                    </button>
                  ) : null}
                </div>
              </div>

              {task.error_message ? (
                <div className="callout callout-danger mt-3">
                  <Icon name="alert" />
                  <div>
                    <strong>这个任务没有完成</strong>
                    <br />
                    {task.error_message}
                  </div>
                </div>
              ) : null}

              {task.status === 'awaiting_approval' && approvalId ? (
                <div className="callout callout-warn mt-3">
                  <Icon name="shield" />
                  <div>
                    <strong>等待发布审批</strong>
                    <br />
                    通过后把内容复制到店铺后台，在那里完成发布。
                    <div className="row gap-2 mt-2">
                      <button type="button" className="btn btn-sm btn-primary" data-decide="approved" disabled={busy} onClick={() => decide('approved')}>
                        通过
                      </button>
                      <button type="button" className="btn btn-sm" data-decide="rejected" disabled={busy} onClick={() => decide('rejected')}>
                        拒绝
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}

              {task.status === 'waiting_for_review' && pendingInfo ? (
                <div className="callout callout-warn mt-3">
                  <Icon name="info" />
                  <div>
                    <strong>需要你确认是否继续</strong>
                    <br />
                    {pendingInfo.question || '是否继续？'}
                    {pendingInfo.reasons && pendingInfo.reasons.length ? (
                      <ul className="t-xs t-muted mt-2 mb-0">
                        {pendingInfo.reasons.map((r: string, i: number) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    ) : null}
                    {pendingInfo.affected_conclusions && pendingInfo.affected_conclusions.length ? (
                      <div className="t-xs t-muted mt-2">
                        受影响：{pendingInfo.affected_conclusions.join('；')}
                      </div>
                    ) : null}
                    <div className="row gap-2 mt-2">
                      <button type="button" className="btn btn-sm btn-primary" data-confirm="continue" disabled={busy} onClick={() => confirmStep('continue')}>
                        继续生成
                      </button>
                      <button type="button" className="btn btn-sm" data-confirm="cancel" disabled={busy} onClick={() => confirmStep('cancel')}>
                        取消
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}

              {['queued', 'running'].includes(task.status) ? (
                <div className="callout callout-info mt-3">
                  <Icon name="info" />
                  <div>任务正在执行。取消会在当前步骤结束后生效，进度会自动刷新。</div>
                </div>
              ) : null}

              {task.status === 'cancelling' ? (
                <div className="callout callout-warn mt-3">
                  <Icon name="info" />
                  <div>已请求取消，等待当前步骤结束。</div>
                </div>
              ) : null}

              <hr className="divider mt-4 mb-4" />
              <div className="t-section mb-3">执行步骤</div>
              <div
                ref={stepsRef}
                dangerouslySetInnerHTML={{
                  __html:
                    window.CPAsyncRun?.stepList?.(
                      detail.steps || [],
                      (result && result.plan) || (task.output || {}).plan || [],
                    ) ?? '',
                }}
              />
            </>
          )}
        </div>
      </aside>
    </>,
    document.body,
  )
}

/* ---------------------------------------------------------------- 页面 */

export function TasksPage({ initialTaskId }: { initialTaskId?: string }) {
  const [status, setStatus] = useState('')
  const [searchText, setSearchText] = useState('')
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<Dict[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [approvals, setApprovals] = useState<Dict[]>([])
  const [role, setRole] = useState('')
  const [activeTaskId, setActiveTaskId] = useState<string | null>(initialTaskId ?? null)
  const [version, setVersion] = useState(0)

  /* 搜索 250ms 防抖；与旧实现一致，只在值真的变了才触发加载 */
  useEffect(() => {
    const next = searchText.trim()
    const timer = window.setTimeout(() => {
      if (next !== query) setQuery(next)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [searchText, query])

  const reloadList = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    let alive = true
    setLoading(true)
    const params = new URLSearchParams()
    if (status) params.set('status', status)
    if (query) params.set('q', query)

    ;(async () => {
      let data: { items?: Dict[] }
      try {
        data = await api.get<{ items?: Dict[] }>(
          '/api/tasks' + (params.toString() ? '?' + params.toString() : ''),
        )
      } catch (err) {
        if (!alive) return
        setError((err as Error).message)
        setLoading(false)
        return
      }
      if (!alive) return
      setItems(data.items || [])
      setError(null)
      setLoading(false)

      // 待审批：admin/owner 可直接处理；其他角色只读
      try {
        const [pendingRes, tenantRes] = await Promise.all([
          api.get<{ items?: Dict[] }>('/api/approvals?status=pending'),
          api.get<{ role?: string }>('/api/tenants/current'),
        ])
        if (!alive) return
        setApprovals(pendingRes.items || [])
        setRole(tenantRes.role || '')
      } catch {
        if (alive) {
          setApprovals([])
          setRole('')
        }
      }
    })()

    return () => {
      alive = false
    }
  }, [status, query, version])

  const openDrawer = (taskId: string) => {
    setActiveTaskId(taskId)
    // 让 URL 可分享；不触发路由重绘（router 只在 popstate / go() 时通知）
    if (location.pathname !== `/tasks/${taskId}`) {
      history.replaceState({}, '', `/tasks/${taskId}`)
    }
  }

  const closeDrawer = useCallback(() => {
    setActiveTaskId(null)
    // 关闭时把地址还原成列表页，同样不动路由
    if (location.pathname.startsWith('/tasks/')) {
      history.replaceState({}, '', '/tasks')
    }
  }, [])

  const filtered = Boolean(status || query)
  const canDecide = role === 'admin' || role === 'owner'

  const decideApproval = async (approvalId: string, decision: 'approved' | 'rejected') => {
    try {
      await api.post(`/api/approvals/${encodeURIComponent(approvalId)}/decide`, { decision })
      toast(decision === 'approved' ? '已通过，可以到店铺后台发布了' : '已拒绝', 'ok')
      reloadList()
    } catch (err) {
      toast((err as Error).message, 'danger')
    }
  }

  const resetFilters = () => {
    setStatus('')
    setSearchText('')
    setQuery('')
  }

  const chips = useMemo(
    () =>
      FILTERS.map((f) => (
        <button
          type="button"
          className={f.key === status ? 'chip is-active' : 'chip'}
          data-status={f.key}
          key={f.key}
          onClick={() => setStatus(f.key)}
        >
          {f.label}
        </button>
      )),
    [status],
  )

  return (
    <PageFrame>
      <PageShell
        title="任务中心"
        desc="所有任务都在这里统一追踪状态、步骤与错误；点击任意一行在右侧抽屉里查看详情。"
      >
        <div className="card">
          <div className="card-head" style={{ flexWrap: 'wrap', gap: 12 }}>
            <div className="chips" id="task-filters">
              {chips}
            </div>
            <div className="row gap-2">
              <input
                type="search"
                className="task-search"
                id="task-search"
                placeholder="搜索任务名称"
                aria-label="搜索任务"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
              />
              <span className="t-xs t-muted" id="task-count" style={{ whiteSpace: 'nowrap' }}>
                {loading ? '' : `共 ${items.length} 条`}
              </span>
            </div>
          </div>

          <div id="task-body">
            {error ? (
              <div className="card-body">
                <div className="callout callout-danger">
                  <Icon name="alert" />
                  <div>加载失败：{error}</div>
                </div>
              </div>
            ) : loading ? (
              <div className="card-body">
                <div className="skeleton skeleton-line" />
                <div className="skeleton skeleton-line" />
                <div className="skeleton skeleton-line" />
              </div>
            ) : (
              <>
                {approvals.length ? (
                  <div className="card card-pad mb-3" style={{ marginBottom: 'var(--sp-4)' }}>
                    <div className="row between wrap gap-2">
                      <div>
                        <div className="card-title">待审批（{approvals.length}）</div>
                        <div className="card-sub">
                          发布 Listing 前需要管理员确认。通过后把内容复制到店铺后台，在那里完成发布。
                        </div>
                      </div>
                    </div>
                    <div className="mt-3">
                      {approvals.map((a) => {
                        const payload = a.payload || {}
                        const title = payload.product_name || payload.listing_id || 'Listing 发布请求'
                        return (
                          <div
                            className="row between wrap gap-2"
                            style={{ padding: '10px 0', borderTop: '1px solid var(--line)' }}
                            key={a.approval_id}
                          >
                            <div>
                              <div className="t-sm">{title}</div>
                              <div className="t-xs t-muted">
                                {KIND_LABEL[a.kind] || '审批请求'} · {fmtTime(a.created_at)}
                              </div>
                            </div>
                            {canDecide ? (
                              <div className="row gap-2">
                                <button
                                  type="button"
                                  className="btn btn-sm btn-primary"
                                  data-approve={a.approval_id}
                                  onClick={() => decideApproval(a.approval_id, 'approved')}
                                >
                                  通过
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-sm"
                                  data-reject={a.approval_id}
                                  onClick={() => decideApproval(a.approval_id, 'rejected')}
                                >
                                  拒绝
                                </button>
                              </div>
                            ) : (
                              <span className="t-xs t-muted">等待管理员处理</span>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ) : null}

                {items.length === 0 ? (
                  <div className="empty">
                    <span className="empty-icon">
                      <Icon name="tasks" />
                    </span>
                    <p className="empty-title">
                      {filtered ? '没有符合条件的任务' : '还没有任务'}
                    </p>
                    <p className="empty-desc">
                      {filtered
                        ? '试试清除筛选，或换一个关键词。'
                        : '去 AI 助手发起一个任务，或在业务页面直接执行。'}
                    </p>
                    <div className="empty-actions">
                      {filtered ? (
                        <button type="button" className="btn btn-sm" id="task-reset" onClick={resetFilters}>
                          清除筛选
                        </button>
                      ) : (
                        <a className="btn btn-primary btn-sm" href="/workbench" data-link="">
                          发起任务
                        </a>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>任务</th>
                          <th>类型</th>
                          <th>来源</th>
                          <th>状态</th>
                          <th className="num">创建</th>
                          <th className="num">结果</th>
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((t) => (
                          <tr
                            data-task-row={t.task_id}
                            tabIndex={0}
                            style={{ cursor: 'pointer' }}
                            key={t.task_id}
                            onClick={() => openDrawer(t.task_id)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault()
                                openDrawer(t.task_id)
                              }
                            }}
                          >
                            <td>
                              <strong>{t.title}</strong>
                            </td>
                            <td className="t-muted">{taskType(t.type)}</td>
                            <td className="t-muted">{originLabel(t.origin)}</td>
                            <td>
                              <StatusBadge status={t.status} />
                            </td>
                            <td className="t-muted num">{fmtTime(t.created_at)}</td>
                            <td className="num t-muted">
                              {t.result_ref ? RESULT_LABEL[t.type] || '记录' : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </PageShell>

      {activeTaskId ? (
        <TaskDrawer taskId={activeTaskId} onClose={closeDrawer} onListRefresh={reloadList} />
      ) : null}
    </PageFrame>
  )
}
