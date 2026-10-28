/**
 * Agent 市场 —— 从旧 `js/pages/misc.js:24-82` 迁移。
 *
 * 展示约定：只出现用户能理解的概念（能力中文名、能干什么），
 * 目录里没有的 key 直接不出现（历史遗留 key 不该漏到界面上）。
 */
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { go } from '@/app/router'
import { Icon } from '@/components/Icon'
import { PageFrame, PageShell } from '@/components/PageShell'

interface AgentItem {
  agent_key: string
  name?: string
  summary?: string
  description?: string
  skill_keys?: string[]
}

const DESC = '选一个 Agent 来执行你的目标。它会调用合适的能力，过程会写进任务记录。'

export function AgentsPage() {
  const [items, setItems] = useState<AgentItem[]>([])
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    api
      .get<{ items?: AgentItem[] }>('/api/agents')
      .then((data) => {
        if (!alive) return
        setItems(data.items || [])
        setError(null)
      })
      .catch((err: unknown) => {
        if (!alive) return
        setError(err as Error)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  if (loading) {
    return (
      <PageFrame>
        <PageShell title="Agent 市场" desc={DESC}>
          <div className="skeleton skeleton-line" style={{ height: 160 }} />
        </PageShell>
      </PageFrame>
    )
  }

  if (error) {
    return (
      <PageFrame>
        <PageShell title="Agent 市场" desc="">
          <div className="callout callout-danger">
            <Icon name="alert" />
            <div>加载失败：{error.message}</div>
          </div>
        </PageShell>
      </PageFrame>
    )
  }

  // 只展示中文能力名；目录里没有的（历史遗留 key）直接不出现
  const skillName = (window.CPCatalog?.SKILL_NAME ?? {}) as Record<string, string>

  return (
    <PageFrame>
      <PageShell
        title="Agent 市场"
        desc={DESC}
        actions={
          <a className="btn btn-sm" href="/workbench" data-link="">
            去 AI 助手
          </a>
        }
      >
        <div className="card-grid-3">
          {items.length === 0 ? (
            <p className="t-sm t-muted">暂没有可用的 Agent</p>
          ) : (
            items.map((agent) => {
              const tags = (agent.skill_keys || [])
                .map((key) => skillName[key])
                .filter(Boolean)
              return (
                <div className="card card-pad" key={agent.agent_key}>
                  <div className="row between gap-2">
                    <div className="row gap-2">
                      <span className="skill-icon">{String(agent.name || '?').slice(0, 1)}</span>
                      <span className="t-section">{agent.name}</span>
                    </div>
                    <button
                      type="button"
                      className="btn btn-sm"
                      data-agent-run={agent.agent_key}
                      onClick={() => go(`/workbench?agent=${encodeURIComponent(agent.agent_key)}`)}
                    >
                      用此 Agent 运行
                    </button>
                  </div>
                  <p className="t-sm t-soft mt-3">{agent.summary}</p>
                  {agent.description ? (
                    <p className="t-xs t-muted mt-2">{agent.description}</p>
                  ) : null}
                  {tags.length ? (
                    <div className="skill-tags mt-3">
                      {tags.map((name) => (
                        <span className="tag" key={name}>
                          {name}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              )
            })
          )}
        </div>
      </PageShell>
    </PageFrame>
  )
}
