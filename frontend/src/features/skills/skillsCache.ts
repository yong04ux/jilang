/**
 * 技能清单缓存 —— 与旧 `CPCatalog.ensureSkills()`（catalog.js:137-156）同语义。
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
  requires: string[]
  credits: number
  inputSchema: Record<string, any>
  outputSchema: Record<string, any>
  runnable: boolean
  builtin: boolean
  icon: string
  tone: string
  tags: string[]
  prompt: string
}

let skills: Skill[] = []
let pending: Promise<Skill[]> | null = null
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
    requires: item.requires || [],
    credits: item.credits || 0,
    inputSchema: item.input_schema || {},
    outputSchema: item.output_schema || {},
    runnable: item.runnable !== false,
    builtin: item.builtin !== false,
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

export function skillByKey(key: string): Skill | null {
  return skills.filter((s) => s.key === key)[0] || null
}

export function skillLoadError(): unknown {
  return loadError
}

export function currentSkills(): Skill[] {
  return skills
}
