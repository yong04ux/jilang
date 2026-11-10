/**
 * Agent 市场：按海报卡列出可用 Agent，点「使用此 Agent」带到工作台。
 *
 * 视觉走「反调印刷」海报墙（骨架与技能广场共用，样式在 styles/skills.css）：
 * 跨列不等宽 + ±1deg 倾斜 + 3px 墨框 + 硬投影，卡角压一个名称首字的巨型描边水印；
 * 标题黑体 900、说明宋体、编号与标签等宽。水印只在装饰层，主操作按钮不受影响。
 *
 * 内容全部来自 `GET /api/agents`：后端没给就是空态，不补假 Agent。
 *
 * 断言钩子：`[data-agent-card]`、`[data-agent-run]`、`[data-agent-name]` ——
 * 按语义断言，不依赖会被样式改版影响的类名。
 */
import { useEffect, useState } from 'react'
import { Bot, Play, TriangleAlert } from 'lucide-react'
import { api } from '@/lib/api'
import { go } from '@/app/router'
import { PageFrame, PageShell } from '@/components/shared/PageShell'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertTitle } from '@/components/ui/alert'
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'

interface AgentItem {
  agent_key: string
  name?: string
  summary?: string
  description?: string
  skill_keys?: string[]
}

const TITLE = 'Agent 市场'

/** 水印字：优先取名称里第一个汉字（「Listing 专家」→ 专），没有汉字才退回首字符 */
function glyphOf(name?: string): string {
  const s = String(name || '')
  const cjk = s.match(/[一-鿿]/)
  return cjk ? cjk[0] : s.slice(0, 1) || '·'
}

function AgentCard({
  agent,
  skillName,
  onDetail,
}: {
  agent: AgentItem
  skillName: Record<string, string>
  onDetail: (agent: AgentItem) => void
}) {
  const tags = (agent.skill_keys || []).map((key) => skillName[key]).filter(Boolean)
  const glyph = glyphOf(agent.name)

  return (
    <article className="ag-card" data-agent-card={agent.agent_key}>
      {/* 巨型描边汉字：名称首字，纯装饰层，永远不压在主操作上 */}
      <span className="ag-glyph" aria-hidden="true">
        {glyph}
      </span>

      <header className="ag-card-head">
        <span className="ag-card-headline">
          <span data-agent-name className="ag-name">
            {agent.name}
          </span>
        </span>
      </header>

      {agent.summary ? <p className="ag-card-sum">{agent.summary}</p> : null}
      {agent.description ? <p className="ag-card-desc">{agent.description}</p> : null}
      {tags.length ? (
        <div className="ag-card-tags">
          {tags.map((name) => (
            <Badge key={name} variant="outline">
              {name}
            </Badge>
          ))}
        </div>
      ) : null}

      <div className="ag-card-foot">
        <div className="ag-foot-left">
          <button
            type="button"
            className="ag-detail"
            data-agent-detail={agent.agent_key}
            onClick={() => onDetail(agent)}
          >
            详情
          </button>
          {tags.length ? (
            <span className="ag-foot-label">可调用能力 {tags.length} 项</span>
          ) : null}
        </div>
        <Button
          size="sm"
          variant="outline"
          className="ag-run"
          data-agent-run={agent.agent_key}
          onClick={() => go(`/workbench?agent=${encodeURIComponent(agent.agent_key)}`)}
        >
          <Play />
          使用此 Agent
        </Button>
      </div>
    </article>
  )
}

export function AgentsPage() {
  const [items, setItems] = useState<AgentItem[]>([])
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState<AgentItem | null>(null)

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
        <PageShell title={TITLE}>
          <div className="ag-wall">
            {[0, 1, 2].map((i) => (
              <div className="ag-skeleton" key={i} aria-hidden="true">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-7 w-3/5" />
                <Skeleton className="h-3.5 w-full" />
                <Skeleton className="h-3 w-4/5" />
                <Skeleton className="mt-auto h-8 w-40" />
              </div>
            ))}
          </div>
        </PageShell>
      </PageFrame>
    )
  }

  if (error) {
    return (
      <PageFrame>
        <PageShell title={TITLE}>
          <Alert variant="destructive">
            <TriangleAlert />
            <AlertTitle>加载失败：{error.message}</AlertTitle>
          </Alert>
        </PageShell>
      </PageFrame>
    )
  }

  // 只展示中文能力名；目录里没有的 key 直接不出现
  const skillName = (window.CPCatalog?.SKILL_NAME ?? {}) as Record<string, string>

  return (
    <PageFrame>
      <PageShell title={TITLE} actions={actions}>
        {items.length === 0 ? (
          <div className="ag-empty">
            <span className="ag-empty-tape">空</span>
            <Bot className="ag-empty-icon" aria-hidden="true" />
            <p className="ag-empty-title">暂没有可用的 Agent</p>
            <p className="ag-empty-desc">
              管理员在服务端配置后，这里会出现可执行的 Agent。
            </p>
          </div>
        ) : (
          <div className="ag-wall">
            {items.map((agent) => (
              <AgentCard
                key={agent.agent_key}
                agent={agent}
                skillName={skillName}
                onDetail={setDetail}
              />
            ))}
          </div>
        )}
      </PageShell>

      <Sheet open={Boolean(detail)} onOpenChange={(open) => !open && setDetail(null)}>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>{detail?.name || 'Agent'}</SheetTitle>
            <SheetDescription>{detail?.summary || ''}</SheetDescription>
          </SheetHeader>

          <div className="flex flex-col gap-4 px-4 text-sm">
            {detail?.description ? (
              <div>
                <div className="mb-1 text-xs font-medium text-muted-foreground">能力说明</div>
                <p className="leading-relaxed text-foreground">{detail.description}</p>
              </div>
            ) : null}

            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">可调用的技能</div>
              {(detail?.skill_keys || []).length ? (
                <div className="flex flex-wrap gap-1.5">
                  {(detail?.skill_keys || []).map((key) => (
                    <Badge key={key} variant="outline">
                      {skillName[key] || key}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">这个 Agent 没有登记可调用的技能。</p>
              )}
            </div>
          </div>

          <SheetFooter>
            <SheetClose asChild>
              <Button variant="outline" size="sm">
                关闭
              </Button>
            </SheetClose>
            <Button
              size="sm"
              onClick={() => {
                const key = detail?.agent_key
                setDetail(null)
                if (key) go(`/workbench?agent=${encodeURIComponent(key)}`)
              }}
            >
              <Play />
              使用此 Agent
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </PageFrame>
  )
}
