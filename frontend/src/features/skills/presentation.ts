/**
 * 技能卡片的**展示**配置：图标字、色调、短标签、起始提示语。
 *
 * 这里不含任何能力语义 —— 技能叫什么、要什么参数、产出什么，全部来自
 * `GET /api/skills`（见 skillsCache.ts）。之前这里写死过一整份技能数组，
 * 改一处漏三处，所以现在只留「怎么展示」。
 */
export interface Presentation {
  icon: string
  tone: string
  tags: string[]
  prompt: string
}

export const PRESENTATION: Record<string, Presentation> = {
  competitor_analysis: {
    icon: '竞',
    tone: 'brand',
    tags: ['价格定位', '评论痛点', '差异化'],
    prompt: '分析这批竞品的价格定位与评论痛点，找出我的差异化机会',
  },
  listing_generation: {
    icon: '写',
    tone: 'info',
    tags: ['标题', '五点', '事实核对'],
    prompt: '基于已确认的商品资料生成一份英文 Listing 草稿',
  },
  market_summary: {
    icon: '市',
    tone: 'brand',
    tags: ['机会判断', '证据引用'],
    prompt: '把这份竞品分析归纳成市场机会判断',
  },
  review_mining: {
    icon: '评',
    tone: 'info',
    tags: ['痛点', '需求', '原文证据'],
    prompt: '从这些评论里挖出主要痛点，并附上原文',
  },
  data_validation: {
    icon: '校',
    tone: 'neutral',
    tags: ['字段映射', '逐行校验', '错误定位'],
    prompt: '帮我检查这份竞品数据文件的字段完整度',
  },
  listing_quality: {
    icon: '检',
    tone: 'neutral',
    tags: ['事实对齐', '待确认项'],
    prompt: '核对这份 Listing 草稿里的数字和卖点是否有出处',
  },
  profit_calc: {
    icon: '利',
    tone: 'neutral',
    tags: ['成本拆解', '盈亏平衡', '敏感性'],
    prompt: '按这批成本数据算一下定价区间和盈亏平衡',
  },
}
