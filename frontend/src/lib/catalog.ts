/**
 * 能力目录的门面数据：导航、图标栏短标签、Agent 清单。
 *
 * 技能清单本身（名称/分类/入参）来自接口，见 `features/skills/skillsCache`；
 * 这里只放「怎么展示」的静态配置，以及把两者拼成旧 `window.CPCatalog` 的形状 ——
 * 还有代码（workbench）按 `C.NAV` / `C.skillByKey` 读它。
 */
import { PRESENTATION } from '@/features/skills/presentation'
import {
  ensureSkills,
  skillByKey,
  skillLoadError,
  skillName,
  currentSkills,
} from '@/features/skills/skillsCache'

export interface NavItem {
  key: string
  label: string
  icon: string
  path: string
}

export const NAV: Array<{ group: string; items: NavItem[] }> = [
  {
    group: '工作空间',
    items: [
      { key: 'dashboard', label: '工作台', icon: 'dashboard', path: '/dashboard' },
      { key: 'workbench', label: 'AI 助手', icon: 'chat', path: '/workbench' },
      { key: 'tasks', label: '任务中心', icon: 'tasks', path: '/tasks' },
    ],
  },
  {
    group: 'Agent 平台',
    items: [
      { key: 'agents', label: 'Agent 市场', icon: 'agents', path: '/agents' },
      { key: 'skills', label: '技能广场', icon: 'skills', path: '/skills' },
    ],
  },
  {
    group: '数据与系统',
    items: [
      { key: 'stores', label: '店铺与渠道', icon: 'stores', path: '/stores' },
      { key: 'data', label: '数据资产', icon: 'data', path: '/data' },
      { key: 'settings', label: '设置', icon: 'settings', path: '/settings' },
    ],
  },
]

export const RAIL_LABEL: Record<string, string> = {
  dashboard: '工作台',
  workbench: 'AI 助手',
  tasks: '任务',
  competitors: '竞品',
  profit: '利润',
  listings: 'Listing',
  data: '数据',
  agents: 'Agent',
  skills: '技能',
  stores: '店铺',
  settings: '设置',
}

/** Agent 清单（随能力清单一起展示；与后端注册表同源，这里只留展示字段） */
export const AGENTS = [
  {
    key: 'main',
    name: '激浪主控 Agent',
    summary: '理解你的业务目标，判断该用哪些技能，把结果整理成可复核的交付物。',
    skills: ['data_validation', 'competitor_analysis', 'market_summary', 'listing_generation'],
  },
  {
    key: 'competitor_expert',
    name: '竞品分析专家',
    summary: '只做竞品与评论洞察，输出带原文出处的分析报告，不写 Listing。',
    skills: ['competitor_analysis', 'review_mining'],
  },
  {
    key: 'listing_expert',
    name: 'Listing 专家',
    summary: '基于你确认过的商品事实撰写文案，写完再做一遍事实核对。',
    skills: ['listing_generation'],
  },
]

/** 分类 chips：「推荐」是伪分类（等价于全部），其余来自接口 */
export function skillCategories(): string[] {
  const seen: Record<string, boolean> = {}
  const list = ['推荐']
  currentSkills().forEach((s) => {
    if (s.cat && !seen[s.cat]) {
      seen[s.cat] = true
      list.push(s.cat)
    }
  })
  return list
}

export const catalogApi = {
  NAV,
  RAIL_LABEL,
  PRESENTATION,
  AGENTS,
  SKILL_NAME: skillName,
  ensureSkills,
  skillCategories,
  skillByKey,
  skillLoadError,
  get skills() {
    return currentSkills()
  },
}
