/**
 * 技能广场 / 技能详情。
 *
 * 两级视图共用一个路由（查询参数而不是新增路由），为了保住已在用的深链：
 * 数据校验跑完会跳到 `/skills?skill=competitor_analysis&batch=<id>`。
 *
 * 能力名称/分类/说明/入参全部来自 `GET /api/skills`（skillsCache），
 * 前端只保留「卡片长什么样」（features/skills/presentation.ts）。
 *
 * 表单与结果都是 HTML 字符串：参数表单由 `lib/schema-form` 按 JSON Schema 生成、
 * 用同一套 `read()` 读回；结果由 `lib/render` 与 `features/skills/blocks` 生成。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { esc, icon, toast } from '@/lib/ui'
import { go } from '@/app/router'
import { Icon } from '@/components/shared/Icon'
import { PageFrame, PageShell } from '@/components/shared/PageShell'
import { useTaskPolling } from '@/lib/async-run/useTaskPolling'
import { describe, hydratePickers, read, render as renderForm } from '@/lib/schema-form/schema-form.ts'
import { outputHtml, paintChart } from '@/features/skills/blocks.ts'
import { unmountCharts } from '@/components/shared/charts/mount-lazy'
import { Badge } from '@/components/ui/badge'
import { ensureSkills, skillByKey, skillLoadError, type Skill } from '@/features/skills/skillsCache'

type Dict = Record<string, any>

/** 这两类要真实生成文字/做长分析，等十几秒是常态，走后台任务 + 轮询 */
const SLOW: Record<string, boolean> = { competitor_analysis: true, listing_generation: true }

/** 精选位：放最常用的三项，不按接口顺序。全量列表里它们仍然会出现 */
const FEATURED = ['competitor_analysis', 'listing_generation', 'profit_calc']

interface GridFilter {
  source: string
  cat: string
  q: string
}

/* 页面模块的 filter 是模块级 state，切到详情再回来筛选条件还在。
   这里用一个模块级对象保持同样体验（不想为此引入全局 store）。 */
const gridFilter: GridFilter = { source: 'all', cat: 'all', q: '' }

/* ---------------------------------------------------------------- 广场 */

function toneClass(tone: string): string {
  return tone === 'info' ? 'is-info' : tone === 'neutral' ? 'is-neutral' : ''
}

function Avatar({ skill, size }: { skill: Skill; size?: 'lg' }) {
  return (
    <span className={`sk-avatar ${toneClass(skill.tone)}${size === 'lg' ? ' sk-avatar--lg' : ''}`}>
      {skill.icon}
    </span>
  )
}

function SkillCard({ skill }: { skill: Skill }) {
  const needsKey = skill.requires.indexOf('llm') !== -1
  return (
    <article className="sk-card" data-open={skill.key} onClick={() => go(`/skills?skill=${encodeURIComponent(skill.key)}`)}>
      <div className="sk-card-head">
        <Avatar skill={skill} />
        <div className="sk-card-title-wrap">
          <h3 className="sk-card-title">{skill.name}</h3>
          <span className="sk-card-cat">{skill.cat}</span>
        </div>
        {needsKey ? <span className="badge badge-warn sk-card-badge">需要密钥</span> : null}
      </div>
      <p className="sk-card-desc">{skill.desc}</p>
      <div className="sk-card-tags">
        {skill.tags.map((t) => (
          <span className="sk-tag" key={t}>
            {t}
          </span>
        ))}
      </div>
      <div className="sk-card-foot">
        <span className="sk-card-src">来源：{skill.builtin ? '激浪内置' : '你创建的'}</span>
        <button
          type="button"
          className="btn btn-sm"
          data-open={skill.key}
          onClick={(e) => {
            e.stopPropagation()
            go(`/skills?skill=${encodeURIComponent(skill.key)}`)
          }}
        >
          运行
        </button>
      </div>
    </article>
  )
}

function FacetChips({
  kind,
  label,
  total,
  entries,
  active,
  onPick,
}: {
  kind: 'source' | 'cat'
  label: string
  total: number
  entries: Array<{ value: string; label: string; count: number }>
  active: string
  onPick: (value: string) => void
}) {
  const chip = (value: string, text: string, count: number) => (
    <button
      type="button"
      className={`sk-chip${active === value ? ' is-active' : ''}`}
      data-facet={kind}
      data-value={value}
      key={`${kind}-${value}`}
      onClick={() => onPick(value)}
    >
      {text}
      <span className="sk-chip-num">{count}</span>
    </button>
  )
  return (
    <div className="sk-facet">
      <span className="sk-facet-label">{label}：</span>
      <div className="chips">
        {chip('all', '全部', total)}
        {entries.map((e) => chip(e.value, e.label, e.count))}
      </div>
    </div>
  )
}

function matches(skill: Skill, f: GridFilter): boolean {
  if (f.source === 'builtin' && !skill.builtin) return false
  if (f.source === 'custom' && skill.builtin) return false
  if (f.cat !== 'all' && skill.cat !== f.cat) return false
  const q = f.q.trim().toLowerCase()
  if (!q) return true
  const hay = [skill.name, skill.cat, skill.desc].concat(skill.tags || []).join(' ').toLowerCase()
  return hay.indexOf(q) !== -1
}

function SkillsGrid({ skills }: { skills: Skill[] }) {
  const [filter, setFilter] = useState<GridFilter>({ ...gridFilter })
  const searchRef = useRef<HTMLInputElement>(null)

  const update = (patch: Partial<GridFilter>) => {
    const next = { ...filter, ...patch }
    gridFilter.source = next.source
    gridFilter.cat = next.cat
    gridFilter.q = next.q
    setFilter(next)
  }

  /* 搜索框用原生 input 监听而不是 React onChange：验收脚本/脚本用
     `el.value = x; dispatchEvent(new Event('input'))` 填值时，React 的 value tracker
     会认为值没变从而跳过 onChange（受控输入尤其明显）。这里直接听原生事件。 */
  useEffect(() => {
    const el = searchRef.current
    if (!el) return
    const onInput = () => update({ q: el.value })
    el.addEventListener('input', onInput)
    return () => el.removeEventListener('input', onInput)
  })

  const list = skills.filter((s) => matches(s, filter))

  const facts = (() => {
    const byCat: Record<string, number> = {}
    let builtin = 0
    skills.forEach((s) => {
      if (s.cat) byCat[s.cat] = (byCat[s.cat] || 0) + 1
      if (s.builtin) builtin += 1
    })
    return {
      total: skills.length,
      sources: [
        { value: 'builtin', label: '激浪内置', count: builtin },
        { value: 'custom', label: '你创建的', count: skills.length - builtin },
      ],
      cats: Object.keys(byCat).map((key) => ({
        value: key,
        label: key,
        count: byCat[key],
      })),
    }
  })()

  const featured = FEATURED.map((key) => skills.find((s) => s.key === key)).filter(Boolean) as Skill[]

  return (
    <PageShell
      title="技能广场"
      desc="每个能力都能单独跑一遍：填好参数，直接看结果。同样的能力也会在 AI 助手里按目标自动串起来。"
      actions={
        <a className="btn btn-sm" href="/workbench" data-link="">
          去 AI 助手
        </a>
      }
    >
      {featured.length ? (
        <section className="sk-section">
          <div className="sk-section-head">
            <h2 className="sk-h2">精选技能</h2>
            <a className="sk-more" href="#sk-all">
              查看全部
              <Icon name="arrowRight" />
            </a>
          </div>
          <div className="sk-grid">
            {featured.map((s) => (
              <SkillCard skill={s} key={s.key} />
            ))}
          </div>
        </section>
      ) : null}

      <section className="sk-section" id="sk-all">
        <div className="sk-section-head">
          <h2 className="sk-h2">全部技能</h2>
          <label className="sk-search">
            <Icon name="search" />
            <input
              type="search"
              id="sk-search"
              ref={searchRef}
              placeholder="搜索技能"
              defaultValue={filter.q}
            />
          </label>
        </div>
        <div className="sk-facets" id="sk-facets">
          <FacetChips
            kind="source"
            label="来源"
            total={facts.total}
            entries={facts.sources}
            active={filter.source}
            onPick={(v) => update({ source: v })}
          />
          <FacetChips
            kind="cat"
            label="场景分类"
            total={facts.total}
            entries={facts.cats}
            active={filter.cat}
            onPick={(v) => update({ cat: v })}
          />
        </div>
        <div className="sk-count" id="sk-count">
          共 {list.length} 项
        </div>
        <div id="sk-grid-all">
          {list.length ? (
            <div className="sk-grid">
              {list.map((s) => (
                <SkillCard skill={s} key={s.key} />
              ))}
            </div>
          ) : (
            <div className="sk-empty">
              <Icon name="search" />
              <div>
                <strong>没有匹配的技能</strong>
                <br />
                换个关键词，或把筛选条件清空再试。
              </div>
            </div>
          )}
        </div>
      </section>
    </PageShell>
  )
}

/* ---------------------------------------------------------------- 详情 */

function SkillDetail({ skill, batch }: { skill: Skill; batch: string }) {
  const formRef = useRef<HTMLDivElement>(null)
  const resultRef = useRef<HTMLDivElement>(null)

  const [running, setRunning] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [result, setResult] = useState<Dict | null>(null)
  /* 执行引擎：来自接口的 engine 字段（{kind,label,provider,model}） */
  const engine = ((result as Dict | null)?.engine ?? null) as
    | { kind?: string; label?: string; provider?: string; model?: string }
    | null
  const [errorText, setErrorText] = useState('')
  const [steps, setSteps] = useState<Dict[]>([])
  const [resultHtml, setResultHtml] = useState('')
  const [revealSignal, setRevealSignal] = useState(0)

  const needsKey = skill.requires.indexOf('llm') !== -1
  const needs = describe(skill.inputSchema, { max: 5 })

  /* 表单是 HTML 字符串，挂载后补两件事：文件选择读 base64、报告/Listing 选择器填数据 */
  useEffect(() => {
    const host = formRef.current
    if (!host) return
    void hydratePickers(host)

    const input = host.querySelector('input[type="file"][data-path]') as HTMLInputElement | null
    if (!input) return
    const onChange = () => {
      const file = input.files && input.files[0]
      if (!file) return
      const label = host.parentElement?.querySelector('[data-file-name]')
      if (file.size > 5 * 1024 * 1024) {
        input.value = ''
        if (label) label.textContent = '文件超过 5 MB，请拆分后再试'
        return
      }
      const reader = new FileReader()
      reader.onload = () => {
        const data = String(reader.result || '')
        input.setAttribute('data-base64', data.split(',')[1] || '')
        input.setAttribute('data-filename', file.name)
        if (label) label.textContent = `已选择：${file.name}`
      }
      reader.readAsDataURL(file)
    }
    input.addEventListener('change', onChange)
    return () => input.removeEventListener('change', onChange)
  }, [skill.key])

  /* 结果区：写 HTML → 补图标 → 画成本图 → 必要时滚进视口 */
  useEffect(() => {
    const host = resultRef.current
    if (!host) return
    // 结果区是字符串重绘：旧图表宿主已被替换掉，先卸载避免 root 泄漏
    unmountCharts()
    window.CPIcon?.hydrate(host)
    if (result) paintChart(host, skill.key, result)
    if (revealSignal > 0) {
      const box = host.getBoundingClientRect()
      if (box.top > window.innerHeight - 80 || box.bottom < 0) {
        host.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      }
    }
  }, [resultHtml, result, skill.key, revealSignal])

  const showResult = (html: string, reveal = true) => {
    setResultHtml(html)
    if (reveal) setRevealSignal((n) => n + 1)
  }

  const clearFieldErrors = () => {
    const host = formRef.current
    if (!host) return
    host.querySelectorAll('.is-invalid').forEach((el) => el.classList.remove('is-invalid'))
    host.querySelectorAll('.field-error').forEach((el) => el.remove())
  }

  /* 服务端回的是中文标签（"商品名称"），表单上也是中文标签，按标签文本对上即可 */
  const applyFieldErrors = (errors: Dict[]) => {
    const host = formRef.current
    if (!host) return
    errors.slice(0, 6).forEach((err) => {
      const wanted = String(err.field || '').split(' · ')[0].trim()
      if (!wanted) return
      const holders = Array.from(host.querySelectorAll('[data-holder]'))
      const holder = holders.filter((el) => {
        const label = el.querySelector('.field-label')
        return label && label.textContent.replace('*', '').trim().indexOf(wanted) === 0
      })[0]
      if (!holder) return
      holder.classList.add('is-invalid')
      const tip = document.createElement('span')
      tip.className = 'field-error'
      tip.textContent = err.message || '这一格需要修正'
      holder.appendChild(tip)
    })
  }

  const handleError = (err: Dict) => {
    const detail = err.detail || {}
    if (err.status === 428) {
      showResult(
        `<div class="callout callout-warn">${icon('alert')}<div>` +
          `<strong>这一步需要你自己的模型密钥</strong><br>${esc(err.message)}` +
          `<div class="row gap-2 mt-2"><a class="btn btn-primary btn-sm" href="/settings" data-link>` +
          `${icon('settings')}去配置 API Key</a></div></div></div>`,
      )
      return
    }
    if (err.status === 422 && Array.isArray(detail.errors) && detail.errors.length) {
      applyFieldErrors(detail.errors)
      showResult(
        `<div class="callout callout-warn">${icon('alert')}<div>${esc(
          detail.message || '有几处需要修正',
        )}</div></div>`,
      )
      return
    }
    setErrorText(err.message || '这次运行没有完成')
    showResult(`<div class="callout callout-danger">${icon('alert')}<div>${esc(err.message || '这次运行没有完成')}</div></div>`)
  }

  const submit = async () => {
    if (running) return
    const host = formRef.current
    clearFieldErrors()

    let payload: Dict
    try {
      payload = read(host as unknown as ParentNode, skill.inputSchema)
    } catch (err) {
      const e = err as Dict
      applyFieldErrors([{ field: e.field, message: e.message }])
      return
    }
    if (batch && skill.key === 'competitor_analysis') payload.import_batch_id = batch

    setRunning(true)
    setResult(null)
    setErrorText('')
    setSteps([])
    setResultHtml(`<div class="sk-loading">${icon('clock')}<span>正在运行…</span></div>`)

    try {
      if (SLOW[skill.key]) {
        const res = await api.post<{ task_id?: string }>(
          `/api/skills/${encodeURIComponent(skill.key)}/run?async_run=true`,
          payload,
        )
        setTaskId(res.task_id || null)
        return
      }
      const res = await api.post<Dict>(`/api/skills/${encodeURIComponent(skill.key)}/run`, payload)
      setResult(res)
      setRunning(false)
      showResult(outputHtml(skill.key, res))
    } catch (err) {
      setRunning(false)
      handleError(err as Dict)
    }
  }

  /* 慢技能：后台任务 + 1s 轮询（poller 已修成连续失败 5 次才放弃） */
  useTaskPolling({
    taskId,
    enabled: Boolean(taskId) && running,
    onUpdate: (detail) => {
      const list = (detail as Dict).steps || []
      setSteps(list)
      setResultHtml(
        `<div class="sk-loading">${icon('clock')}<span>正在运行…</span></div>` +
          (window.CPAsyncRun?.stepList?.(list, []) ?? '') +
          `<div class="row gap-2 mt-2"><button type="button" class="btn btn-sm" id="sk-cancel">取消运行</button></div>`,
      )
    },
    onDone: (detail) => {
      const d = detail as Dict
      const task = d.task || {}
      setRunning(false)
      setTaskId(null)
      setSteps(d.steps || [])
      if (task.status === 'succeeded') {
        const sk = (d.result || {}).skill || {}
        const output = sk.output || (d.result || {}).report || (d.result || {}).listing || {}
        const payload = {
          output,
          is_demo: Boolean(sk.is_demo),
          result_ref: sk.result_ref,
          task_id: task.task_id,
          /* 执行引擎必须跟着结果走：无密钥时是规则引擎，有密钥是大模型。
             界面上要如实显示，不能让人以为规则生成的结果是模型跑的。 */
          engine: d.engine || (d.result || {}).engine || null,
        }
        setResult(payload)
        showResult(outputHtml(skill.key, payload))
        return
      }
      const message = task.error_message || '这次运行没有完成，可以重试一次'
      setErrorText(message)
      showResult(`<div class="callout callout-danger">${icon('alert')}<div>${esc(message)}</div></div>`)
    },
    onError: (err) => {
      setRunning(false)
      showResult(
        `<div class="callout callout-danger">${icon('alert')}<div>${esc(
          (err as Error).message || '任务状态读取失败',
        )}</div></div>`,
      )
    },
  })

  /* 取消按钮在结果区里，是 HTML 字符串渲染的 —— 用事件委托接住 */
  useEffect(() => {
    const host = resultRef.current
    if (!host) return
    const onClick = async (event: MouseEvent) => {
      const btn = (event.target as Element)?.closest?.('#sk-cancel') as HTMLButtonElement | null
      if (!btn || !taskId) return
      btn.disabled = true
      try {
        const resp = await api.post<{ detail?: string }>(
          `/api/tasks/${encodeURIComponent(taskId)}/cancel`,
          {},
        )
        toast(resp?.detail || '已请求取消', 'ok')
      } catch (err) {
        btn.disabled = false
        toast((err as Error).message, 'danger')
      }
    }
    host.addEventListener('click', onClick)
    return () => host.removeEventListener('click', onClick)
  }, [taskId])

  return (
    <>
      <a className="sk-back" href="/skills" data-link="">
        <Icon name="chevronLeft" />
        技能广场
      </a>
      <section className="sk-detail" id="sk-detail">
        <div className="sk-detail-head">
          <Avatar skill={skill} size="lg" />
          <div className="sk-detail-title">
            <h2 className="sk-h2">{skill.name}</h2>
            <span className="sk-card-cat">{skill.cat}</span>
          </div>
          {needsKey ? (
            <span className="badge badge-warn">需要密钥</span>
          ) : (
            <span className="badge badge-ok">本地计算</span>
          )}
        </div>
        <p className="sk-detail-desc">{skill.desc}</p>
        {skill.tags.length ? (
          <div className="sk-card-tags">
            {skill.tags.map((t) => (
              <span className="sk-tag" key={t}>
                {t}
              </span>
            ))}
          </div>
        ) : null}
        {needs ? (
          <p className="field-help mt-3">
            你需要准备：<strong>{needs}</strong>
          </p>
        ) : null}
        {batch && skill.key === 'competitor_analysis' ? (
          <div className="callout callout-info mt-3">
            <Icon name="info" />
            <div>已带入刚才校验通过的那批数据。</div>
          </div>
        ) : null}

        <form id="sk-form" className="mt-4" autoComplete="off">
          <div ref={formRef} dangerouslySetInnerHTML={{ __html: renderForm(skill.inputSchema, {}) }} />
        </form>

        {engine ? (
          <div className="mt-4 flex items-center gap-2 text-xs" id="sk-engine" data-engine={engine.kind || ''}>
            <Badge variant={engine.kind === 'llm' ? 'info' : 'outline'}>{engine.label || '规则引擎'}</Badge>
            <span className="text-muted-foreground">这次结果由它生成</span>
          </div>
        ) : null}

        {/* 结果区放在运行条之前：运行条是吸底的，结果放它后面会被压在视口外 */}
        <div
          className="sk-result"
          id="sk-result"
          ref={resultRef}
          dangerouslySetInnerHTML={{ __html: resultHtml }}
        />
        <div className="sk-run-bar">
          <button type="button" className="btn btn-primary btn-sm" id="sk-run" disabled={running} onClick={submit}>
            <Icon name={running ? 'clock' : 'play'} />
            {running ? '运行中…' : '运行'}
          </button>
          <span className="t-xs t-muted" id="sk-hint">
            {needsKey ? '这一步会调用你自己的模型密钥' : '全部本地计算，不调用模型'}
          </span>
        </div>
      </section>
    </>
  )
}

/* ---------------------------------------------------------------- 页面 */

export function SkillsPage({ query }: { query: Record<string, string> }) {
  const [skills, setSkills] = useState<Skill[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'empty'>('loading')

  useEffect(() => {
    let alive = true
    void ensureSkills().then((list) => {
      if (!alive) return
      setSkills(list)
      setState(list.length ? 'ready' : 'empty')
    })
    return () => {
      alive = false
    }
  }, [])

  const wanted = String(query.skill || '')
  const batch = String(query.batch || '')
  const skill = useMemo(() => (wanted ? skillByKey(wanted) : null), [wanted, skills])

  if (state === 'loading') {
    return (
      <PageFrame>
        <div className="page">
          <div className="page-inner">
            <div className="skeleton skeleton-line" style={{ height: 180 }} />
          </div>
        </div>
      </PageFrame>
    )
  }

  if (state === 'empty') {
    const err = skillLoadError()
    return (
      <PageFrame>
        <PageShell title="技能广场" desc="">
          <div className="callout callout-warn">
            <Icon name="alert" />
            <div>
              {err ? '技能列表暂时读不出来，刷新一下再试。' : '暂时没有可以运行的能力。'}
            </div>
          </div>
        </PageShell>
      </PageFrame>
    )
  }

  return (
    <PageFrame>
      {/* key 必须带 skill.key：否则换技能时组件被复用，上一个技能的
          结果与运行状态会残留（现有实现靠 render() 里的 reset() 清干净） */}
      {skill ? (
        <SkillDetail key={skill.key} skill={skill} batch={batch} />
      ) : (
        <SkillsGrid skills={skills} />
      )}
    </PageFrame>
  )
}
