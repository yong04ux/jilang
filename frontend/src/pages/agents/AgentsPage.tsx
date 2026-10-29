/**
 * Agent 市场 —— 新设计语言的参考实现（shadcn/ui + Tailwind）
 *
 * ── 这次改造的边界 ────────────────────────────────────────────────
 * 只换「内容区」：页头仍走 PageShell（.page/.page-head/.page-title 是既有
 * 布局契约，多个探针依赖它），列表与卡片换成 components/ui 的 Card/Badge。
 * 这样改动的视觉收益明确，回归面可控。
 *
 * ── 与旧实现的差异（都是有意的） ──────────────────────────────────
 * 1. 卡片用 Flex 两行结构而非 `.card-pad` 内边距堆叠：标题行与能力标签
 *    各自成层，长描述不再把按钮挤走。
 * 2. 名称首字做成带底色的方形标识（原 `.skill-icon`），与技能页观感统一。
 * 3. 能力标签改用 Badge（描边、11px），不再用 `.tag` 的实心底。
 * 4. 加载态用 Skeleton 骨架（原来是单条灰块在 160px 高的盒子里）。
 * 5. 空态与错误态改为显式文案 + 可操作入口，不再只给一句提示。
 *
 * 断言的钩子：`[data-agent-card]` 与 `[data-agent-run]` —— 探针按语义断言，
 * 不再依赖 `.card` 这种会被样式改版影响的类名。
 */
import { useEffect, useState } from 'react'
import { Bot, Play, TriangleAlert } from 'lucide-react'
import { api } from '@/lib/api'
import { go } from '@/app/router'
import { PageFrame, PageShell } from '@/components/PageShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertTitle } from '@/components/ui/alert'

interface AgentItem {
  agent_key: string
  name?: string
  summary?: string
  description?: string
  skill_keys?: string[]
}

const TITLE = 'Agent 市场'
const DESC = '选一个 Agent 来执行你的目标。它会调用合适的能力，过程会写进任务记录。'

function AgentCard({ agent, skillName }: { agent: AgentItem; skillName: Record<string, string> }) {
  const tags = (agent.skill_keys || []).map((key) => skillName[key]).filter(Boolean)
  const initial = String(agent.name || '?').slice(0, 1)

  return (
    <Card data-agent-card={agent.agent_key} className="gap-0">
      <CardHeader className="flex-row items-center justify-between gap-2 pb-0">
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary-soft text-xs font-semibold text-primary"
            aria-hidden="true"
          >
            {initial}
          </span>
          <span data-agent-name className="truncate text-sm font-semibold">
            {agent.name}
          </span>
        </div>
        <Button
          size="sm"
          variant="outline"
          data-agent-run={agent.agent_key}
          onClick={() => go(`/workbench?agent=${encodeURIComponent(agent.agent_key)}`)}
        >
          <Play />
          用此 Agent 运行
        </Button>
      </CardHeader>

      <CardContent className="flex flex-col gap-2 pt-3">
        {agent.summary ? (
          <p className="text-sm leading-relaxed text-foreground">{agent.summary}</p>
        ) : null}
        {agent.description ? (
          <p className="text-xs leading-relaxed text-muted-foreground">{agent.description}</p>
        ) : null}
        {tags.length ? (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {tags.map((name) => (
              <Badge key={name} variant="outline">
                {name}
              </Badge>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

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

  const actions = (
    <Button size="sm" variant="outline" asChild>
      <a href="/workbench" data-link="">
        去 AI 助手
      </a>
    </Button>
  )

  if (loading) {
    return (
      <PageFrame>
        <PageShell title={TITLE} desc={DESC}>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Card key={i} className="gap-0">
                <CardHeader className="flex-row items-center gap-2.5 pb-0">
                  <Skeleton className="size-8 rounded-md" />
                  <Skeleton className="h-4 w-24" />
                </CardHeader>
                <CardContent className="flex flex-col gap-2 pt-3">
                  <Skeleton className="h-3.5 w-full" />
                  <Skeleton className="h-3 w-4/5" />
                  <Skeleton className="h-5 w-20" />
                </CardContent>
              </Card>
            ))}
          </div>
        </PageShell>
      </PageFrame>
    )
  }

  if (error) {
    return (
      <PageFrame>
        <PageShell title={TITLE} desc="">
          <Alert variant="destructive">
            <TriangleAlert />
            <AlertTitle>加载失败：{error.message}</AlertTitle>
          </Alert>
        </PageShell>
      </PageFrame>
    )
  }

  // 只展示中文能力名；目录里没有的（历史遗留 key）直接不出现
  const skillName = (window.CPCatalog?.SKILL_NAME ?? {}) as Record<string, string>

  return (
    <PageFrame>
      <PageShell title={TITLE} desc={DESC} actions={actions}>
        {items.length === 0 ? (
          <Card className="items-center gap-2 py-12 text-center">
            <Bot className="size-6 text-muted-foreground" aria-hidden="true" />
            <p className="text-sm font-medium">暂没有可用的 Agent</p>
            <p className="text-xs text-muted-foreground">
              管理员在服务端配置后，这里会出现可执行的 Agent。
            </p>
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {items.map((agent) => (
              <AgentCard key={agent.agent_key} agent={agent} skillName={skillName} />
            ))}
          </div>
        )}
      </PageShell>
    </PageFrame>
  )
}
