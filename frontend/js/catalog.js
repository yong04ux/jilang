/* 激浪 · 能力目录
 *
 * 这里描述的是**真实能力**（已实现 / 开发中），不是示例业务数据。
 * 业务数据（报告、Listing、任务）一律来自后端 API，不得在此伪造。
 */
(function () {
  "use strict";

  /* ---------------- 导航（完整规划，未实现项标 soon） ---------------- */
  const NAV = [
    { group: "工作空间", items: [
      { key: "dashboard",   label: "工作台",      icon: "dashboard",  path: "/dashboard" },
      { key: "workbench",   label: "AI 助手",     icon: "chat",       path: "/workbench" },
      { key: "tasks",       label: "任务中心",    icon: "tasks",      path: "/tasks" },
    ]},
    { group: "业务工具", items: [
      { key: "competitors", label: "竞品分析",   icon: "competitors", path: "/competitors" },
      { key: "listings",    label: "Listing 工作室", icon: "listing", path: "/listings" },
      { key: "research",    label: "选品与市场研究", icon: "research",  path: "/research",  soon: true },
      { key: "assets",      label: "商品素材工作室", icon: "assets",  path: "/assets",     soon: true },
      { key: "operations",  label: "运营分析",   icon: "operations",  path: "/operations", soon: true },
    ]},
    { group: "Agent 平台", items: [
      { key: "agents",      label: "Agent 市场", icon: "agents",      path: "/agents" },
      { key: "skills",      label: "Skills 技能库", icon: "skills",   path: "/skills" },
      { key: "workflows",   label: "工作流",     icon: "workflows",   path: "/workflows",  soon: true },
    ]},
    { group: "数据与系统", items: [
      { key: "stores",      label: "店铺与渠道", icon: "stores",      path: "/stores" },
      { key: "data",        label: "数据资产",   icon: "data",        path: "/data" },
      { key: "knowledge",   label: "知识库",     icon: "knowledge",   path: "/knowledge",  soon: true },
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

  /* ---------------- 技能（真实能力清单） ---------------- */
  const SKILL_CATEGORIES = [
    "推荐", "选品与开发", "竞品与Listing", "产品运营", "营销广告", "数据分析", "合规检测", "已接入",
  ];

  const SKILLS = [
    {
      key: "competitor_analysis", name: "竞品分析", cat: "竞品与Listing",
      icon: "C", tone: "brand", status: "available",
      desc: "汇总竞品价格、评分、评论与卖点，输出带证据分级的结论与差异化机会。",
      tags: ["价格定位", "评论痛点", "差异化"],
      input: "商品名 · 平台/站点 · 竞品明细（价格/评分/评论）",
      output: "AnalysisReport（价格统计/痛点/证据引用/差异化）",
      action: "competitor",
      prompt: "分析这批竞品的价格定位与评论痛点，找出我的差异化机会",
    },
    {
      key: "listing_generation", name: "Listing 生成", cat: "竞品与Listing",
      icon: "L", tone: "info", status: "available",
      desc: "基于已确认的商品事实生成标题、五点描述、产品描述与 Search Terms，并做事实对齐质检。",
      tags: ["标题", "五点", "事实台账"],
      input: "商品事实（规格/卖点/认证）· 目标语言 · 可选报告",
      output: "ListingDraft（标题/五点/描述/质检/事实台账）",
      action: "listing",
      prompt: "基于已确认的商品资料生成一份英文 Listing 草稿",
    },
    {
      key: "data_validation", name: "数据校验与导入", cat: "数据分析",
      icon: "D", tone: "neutral", status: "available",
      desc: "上传 CSV / JSON / Excel，逐行校验字段并给出可定位到单元格的错误报告。",
      tags: ["字段映射", "逐行校验", "错误导出"],
      input: "文件字节流（CSV/JSON/XLSX，≤5MB）",
      output: "校验结果（有效行/逐行错误/字段统计）",
      action: "data",
      prompt: "帮我检查这份竞品数据文件的字段完整度",
    },
    {
      key: "review_mining", name: "评论痛点挖掘", cat: "产品运营",
      icon: "R", tone: "info", status: "available",
      desc: "从评论样本中识别痛点、需求与购买顾虑，附原文引用与出现频次。",
      tags: ["痛点", "需求", "原文证据"],
      input: "评论样本（文本 + 可选星级/日期）",
      output: "四类主题（痛点/低星/需求/顾虑）+ 频次 + 原文",
      action: "competitor",
      prompt: "从这些评论里挖出主要痛点，并附上原文",
    },
    {
      key: "market_summary", name: "市场机会总结", cat: "选品与开发",
      icon: "M", tone: "brand", status: "dev",
      desc: "把分析结论归纳成一段可读的市场机会判断，只引用已有证据，不推断销量与规模。",
      tags: ["机会判断", "证据引用"],
      input: "已有 AnalysisReport（只读，不新增数据）",
      output: "机会总结文本 + 引用到的证据锚点",
      prompt: "把这份竞品分析归纳成市场机会判断",
    },
    {
      key: "keyword_layout", name: "关键词布局", cat: "营销广告",
      icon: "K", tone: "neutral", status: "dev",
      desc: "在无搜索量数据时只做词表整理与布局建议，不计算机会分、不推断流量。",
      tags: ["Search Terms", "字节限制"],
      input: "关键词表（搜索量/排名可为空）· 平台字节上限",
      output: "Search Terms 草案 + 布局说明（无指标则不打分）",
      prompt: "整理这批关键词并给出 Search Terms 布局建议",
    },
  ];

  /* ---------------- Agent（真实定义，随 Registry 落地） ---------------- */
  const AGENTS = [
    {
      key: "main", name: "激浪主控 Agent", version: "0.3.0", status: "available",
      summary: "解析业务目标、编排 Skills、交付结构化结果；执行由 LangGraph 图与确定性检查点驱动。",
      skills: ["data_validation", "competitor_analysis", "market_summary", "listing_generation"],
      tools: ["read_data_asset", "run_competitor_analysis", "generate_listing", "run_quality_check"],
    },
    {
      key: "competitor_expert", name: "竞品分析专家", version: "0.3.0", status: "available",
      summary: "只做竞品与评论洞察，输出证据分级报告；不生成 Listing。",
      skills: ["competitor_analysis", "review_mining"],
      tools: ["run_competitor_analysis"],
    },
    {
      key: "listing_expert", name: "Listing 专家", version: "0.3.0", status: "beta",
      summary: "基于事实台账撰写文案，并做事实对齐质检。",
      skills: ["listing_generation"],
      tools: ["generate_listing", "run_quality_check"],
    },
  ];

  const SKILL_DEFS = SKILLS.map(function (s) {
    return Object.assign({}, s, { runs: null });
  });

  window.CPCatalog = {
    NAV, RAIL, RAIL_LABEL, SKILL_CATEGORIES, SKILLS, AGENTS, SKILL_DEFS,
  };
})();
