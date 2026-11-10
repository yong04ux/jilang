/**
 * 技能清单缓存。
 *
 * 三个必须保留的性质：
 *  1. **单飞**：并发调用只发一次请求，后续复用同一个 Promise；
 *  2. **只收可运行的**：`runnable !== false && status === 'available'`；
 *  3. **失败吞错返回空数组**，由页面自己决定怎么提示（不把错误抛给调用方）。
 *
 * 另有 `skillName` 映射，供「这个 Agent 会哪些技能」这类展示使用。
 */
import { api } from '@/lib/api'
import { PRESENTATION } from './presentation'

export interface Skill {
  key: string
  name: string
  cat: string
  desc: string
  status?: string
  renderer?: string
  /** 会调用模型但不是硬依赖：没有 Key 时退回规则引擎 */
  usesLlm: boolean
  credits: number
  inputSchema: Record<string, any>
  outputSchema: Record<string, any>
  runnable: boolean
  builtin: boolean
  source?: string
  /** SKILL.md 正文；只有详情接口会返回 */
  instructions?: string
  icon: string
  tone: string
  tags: string[]
  prompt: string
}

/** 工作台用的可运行技能 */
let skills: Skill[] = []
let pending: Promise<Skill[]> | null = null
/** 技能广场用的全量技能（含导入的说明型技能） */
let allSkills: Skill[] = []
let allPending: Promise<Skill[]> | null = null
let loadError: unknown = null

/** 技能 key → 中文名 */
export const skillName: Record<string, string> = {}

function mergeSkill(item: Record<string, any>): Skill {
  const look = PRESENTATION[item.skill_key] || { icon: '·', tone: '', tags: [], prompt: '' }
  return {
    key: item.skill_key,
    name: item.name,
    cat: item.category || '',
    desc: item.summary || '',
    status: item.status,
    renderer: item.renderer || '',
    usesLlm: item.uses_llm === true,
    credits: item.credits || 0,
    inputSchema: item.input_schema || {},
    outputSchema: item.output_schema || {},
    runnable: item.runnable !== false,
    builtin: item.builtin !== false,
    source: item.source || (item.builtin !== false ? 'builtin' : 'custom'),
    instructions: item.instructions || '',
    icon: look.icon,
    tone: look.tone,
    tags: look.tags,
    prompt: look.prompt,
  }
}

/** 拉一次技能清单并缓存。失败时返回空数组。 */
export function ensureSkills(): Promise<Skill[]> {
  if (skills.length) return Promise.resolve(skills)
  if (pending) return pending
  pending = api
    .get<{ items?: Record<string, any>[] }>('/api/skills')
    .then((res) => {
      skills = (res.items || [])
        .filter((s) => s.runnable !== false && s.status === 'available')
        .map(mergeSkill)
      skills.forEach((s) => {
        skillName[s.key] = s.name
      })
      loadError = null
      pending = null
      return skills
    })
    .catch((err: unknown) => {
      loadError = err
      pending = null
      return []
    })
  return pending
}

/** 技能广场：全量（已删除的不显示），工作台仍然只拿可运行的。 */
export function ensureAllSkills(): Promise<Skill[]> {
  if (allSkills.length) return Promise.resolve(allSkills)
  if (allPending) return allPending
  allPending = api
    .get<{ items?: Record<string, any>[] }>('/api/skills')
    .then((res) => {
      allSkills = (res.items || [])
        .filter((s) => s.status !== 'disabled')
        .map(mergeSkill)
      allSkills.forEach((s) => {
        skillName[s.key] = s.name
      })
      loadError = null
      allPending = null
      return allSkills
    })
    .catch((err: unknown) => {
      loadError = err
      allPending = null
      return []
    })
  return allPending
}

/** 导入/删除后失效缓存：下一次进入页面重新拉接口。 */
export function invalidateSkills(): void {
  skills = []
  allSkills = []
  pending = null
  allPending = null
}

export function skillByKey(key: string): Skill | null {
  return (
    skills.filter((s) => s.key === key)[0] ||
    allSkills.filter((s) => s.key === key)[0] ||
    null
  )
}

export function skillLoadError(): unknown {
  return loadError
}

export function currentSkills(): Skill[] {
  return skills
}
