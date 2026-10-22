/* 激浪 · 能力目录
 *
 * 这里描述的是**实际可用的能力**，不是示例业务数据。
 * 业务数据（报告、Listing、任务）一律来自后端 API，不得在此伪造。
 *
 * 约定：只有真正能用的入口才进 NAV。尚未开放的能力不进导航——
 * 与其摆一堆点不开的入口，不如让用户看到的每一项都可用。
 */
(function () {
  "use strict";

  /* ---------------- 导航 ---------------- */
  const NAV = [
    { group: "工作空间", items: [
      { key: "dashboard",   label: "工作台",      icon: "dashboard",  path: "/dashboard" },
      { key: "workbench",   label: "AI 助手",     icon: "chat",       path: "/workbench" },
      { key: "tasks",       label: "任务中心",    icon: "tasks",      path: "/tasks" },
    ]},
    { group: "业务工具", items: [
      { key: "competitors", label: "竞品分析",   icon: "competitors", path: "/competitors" },
      { key: "profit",      label: "成本与利润", icon: "chart",       path: "/profit" },
      { key: "listings",    label: "Listing 工作室", icon: "listing", path: "/listings" },
    ]},
    { group: "Agent 平台", items: [
      { key: "agents",      label: "Agent 市场", icon: "agents",      path: "/agents" },
      { key: "skills",      label: "Skills 技能库", icon: "skills",   path: "/skills" },
    ]},
    { group: "数据与系统", items: [
      { key: "stores",      label: "店铺与渠道", icon: "stores",      path: "/stores" },
      { key: "data",        label: "数据资产",   icon: "data",        path: "/data" },
      { key: "settings",    label: "设置",       icon: "settings",    path: "/settings" },
    ]},
  ];

  const RAIL = ["dashboard", "workbench", "tasks", "competitors", "listings", "data", "stores", "settings"];

  const RAIL_LABEL = {
    dashboard: "工作台",
    workbench: "AI 助手",
    tasks: "任务",
    competitors: "竞品",
    listings: "Listing",
    data: "数据",
    agents: "Agent",
    skills: "技能",
    stores: "店铺",
    settings: "设置",
  };

  /* ---------------- 技能（当前可用的能力清单） ---------------- */
  /* 只列真正能跑的能力。不在这里放「规划中」的条目——
     界面上不出现的东西就不该占一个分类空壳。 */
  const SKILL_CATEGORIES = [
    "推荐", "竞品与Listing", "选品与开发", "产品运营", "数据分析",
  ];

  const SKILLS = [
    {
      key: "competitor_analysis", name: "竞品分析", cat: "竞品与Listing",
      icon: "C", tone: "brand", status: "available",
      desc: "汇总竞品价格、评分、评论与卖点，输出带原文出处的结论与差异化机会。",
      tags: ["价格定位", "评论痛点", "差异化"],
      input: "商品名 · 平台与站点 · 竞品明细（价格、评分、评论）",
      output: "分析报告：价格分布、评论痛点、差异化机会，每条结论附原文出处",
      action: "competitor",
      prompt: "分析这批竞品的价格定位与评论痛点，找出我的差异化机会",
    },
    {
      key: "listing_generation", name: "Listing 生成", cat: "竞品与Listing",
      icon: "L", tone: "info", status: "available",
      desc: "基于已确认的商品事实生成标题、五点描述、产品描述与 Search Terms，并做事实对齐质检。",
      tags: ["标题", "五点", "事实核对"],
      input: "商品事实（规格、卖点、认证）· 目标语言 · 可选用分析报告",
      output: "Listing 草稿：标题、五点描述、产品描述、Search Terms，附事实核对结果",
      action: "listing",
      prompt: "基于已确认的商品资料生成一份英文 Listing 草稿",
    },
    {
      key: "market_summary", name: "市场机会总结", cat: "选品与开发",
      icon: "M", tone: "brand", status: "available",
      desc: "把分析结论归纳成一段可读的市场机会判断，只引用已有证据，不推断销量与规模。",
      tags: ["机会判断", "证据引用"],
      input: "一份已生成的分析报告（只读，不会补数据）",
      output: "市场机会判断，附引用到的原文出处",
      prompt: "把这份竞品分析归纳成市场机会判断",
    },
    {
      key: "data_validation", name: "数据校验与导入", cat: "数据分析",
      icon: "D", tone: "neutral", status: "available",
      desc: "上传 CSV / JSON / Excel，逐行校验字段并给出可定位到单元格的错误报告。",
      tags: ["字段映射", "逐行校验", "错误导出"],
      input: "CSV / JSON / Excel 文件，不超过 5 MB",
      output: "校验结果：有效行数、逐行错误位置、字段统计",
      action: "data",
      prompt: "帮我检查这份竞品数据文件的字段完整度",
    },
    {
      key: "review_mining", name: "评论痛点挖掘", cat: "产品运营",
      icon: "R", tone: "info", status: "available",
      desc: "从评论样本中识别痛点、需求与购买顾虑，附原文引用与出现频次。",
      tags: ["痛点", "需求", "原文证据"],
      input: "评论样本（文本，可选星级与日期）",
      output: "四类主题（痛点 / 低星 / 需求 / 顾虑）+ 出现频次 + 原文",
      action: "competitor",
      prompt: "从这些评论里挖出主要痛点，并附上原文",
    },
  ];

  /* ---------------- Agent（随能力清单一起展示） ---------------- */
  const AGENTS = [
    {
      key: "main", name: "激浪主控 Agent",
      summary: "理解你的业务目标，判断该用哪些技能，把结果整理成可复核的交付物。",
      skills: ["data_validation", "competitor_analysis", "market_summary", "listing_generation"],
    },
    {
      key: "competitor_expert", name: "竞品分析专家",
      summary: "只做竞品与评论洞察，输出带原文出处的分析报告，不写 Listing。",
      skills: ["competitor_analysis", "review_mining"],
    },
    {
      key: "listing_expert", name: "Listing 专家",
      summary: "基于你确认过的商品事实撰写文案，写完再做一遍事实核对。",
      skills: ["listing_generation"],
    },
  ];

  const SKILL_DEFS = SKILLS.map(function (s) {
    return Object.assign({}, s, { runs: null });
  });

  /* 技能 key → 中文名，给「这个 Agent 会哪些技能」这类展示用 */
  const SKILL_NAME = {};
  SKILLS.forEach(function (s) { SKILL_NAME[s.key] = s.name; });

  window.CPCatalog = {
    NAV, RAIL, RAIL_LABEL, SKILL_CATEGORIES, SKILLS, AGENTS, SKILL_DEFS, SKILL_NAME,
  };
})();
