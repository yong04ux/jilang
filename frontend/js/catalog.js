/* 激浪 · 能力目录
 *
 * 这里描述的是**实际可用的能力**，不是示例业务数据。
 * 业务数据（报告、Listing、任务）一律来自后端 API，不得在此伪造。
 *
 * 重要：技能的名称、说明、分类、参数清单**只有一份真源**——后端的技能注册表。
 * 这个文件里只留「怎么展示」：图标、色调、标签、起始提示语。
 * 之前这里写死过一整份技能数组，于是同一件能力在代码里存在三份描述，
 * 改一处漏三处；现在列表由 `CPCatalog.ensureSkills()` 拉 `/api/skills` 合并生成。
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
    { group: "Agent 平台", items: [
      { key: "agents",      label: "Agent 市场", icon: "agents",      path: "/agents" },
      { key: "skills",      label: "技能广场",   icon: "skills",   path: "/skills" },
    ]},
    { group: "数据与系统", items: [
      { key: "stores",      label: "店铺与渠道", icon: "stores",      path: "/stores" },
      { key: "data",        label: "数据资产",   icon: "data",        path: "/data" },
      { key: "settings",    label: "设置",       icon: "settings",    path: "/settings" },
    ]},
  ];

  const RAIL_LABEL = {
    dashboard: "工作台",
    workbench: "AI 助手",
    tasks: "任务",
    competitors: "竞品",
    profit: "利润",
    listings: "Listing",
    data: "数据",
    agents: "Agent",
    skills: "技能",
    stores: "店铺",
    settings: "设置",
  };

  /* ---------------- 展示提示（不含能力语义） ----------------
   * icon/tone 决定卡片长相，tags 是短标签，prompt 是工作台里「点这张卡」
   * 填进输入框的那句话。能力叫什么、要什么参数、产出什么，一律来自接口。 */
  /* 卡片上的「头像」用一个汉字 / 字母，比英文首字母好认；
     tone 决定底色，跟页面其余地方的语义色保持一致。 */
  const PRESENTATION = {
    competitor_analysis: {
      icon: "竞", tone: "brand", tags: ["价格定位", "评论痛点", "差异化"],
      prompt: "分析这批竞品的价格定位与评论痛点，找出我的差异化机会",
    },
    listing_generation: {
      icon: "写", tone: "info", tags: ["标题", "五点", "事实核对"],
      prompt: "基于已确认的商品资料生成一份英文 Listing 草稿",
    },
    market_summary: {
      icon: "市", tone: "brand", tags: ["机会判断", "证据引用"],
      prompt: "把这份竞品分析归纳成市场机会判断",
    },
    review_mining: {
      icon: "评", tone: "info", tags: ["痛点", "需求", "原文证据"],
      prompt: "从这些评论里挖出主要痛点，并附上原文",
    },
    data_validation: {
      icon: "校", tone: "neutral", tags: ["字段映射", "逐行校验", "错误定位"],
      prompt: "帮我检查这份竞品数据文件的字段完整度",
    },
    listing_quality: {
      icon: "检", tone: "neutral", tags: ["事实对齐", "待确认项"],
      prompt: "核对这份 Listing 草稿里的数字和卖点是否有出处",
    },
    profit_calc: {
      icon: "利", tone: "neutral", tags: ["成本拆解", "盈亏平衡", "敏感性"],
      prompt: "按这批成本数据算一下定价区间和盈亏平衡",
    },
  };

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

  /* ---------------- 运行时技能清单 ---------------- */
  const A = window.CPApi;

  let skills = [];
  let pending = null;
  let loadError = null;

  /* 技能 key → 中文名，给「这个 Agent 会哪些技能」这类展示用 */
  const SKILL_NAME = {};

  function mergeSkill(item) {
    const look = PRESENTATION[item.skill_key] || { icon: "·", tone: "", tags: [], prompt: "" };
    return {
      key: item.skill_key,
      name: item.name,
      cat: item.category || "",
      desc: item.summary || "",
      status: item.status,
      renderer: item.renderer || "",
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
    };
  }

  /** 拉一次技能清单并缓存。失败时返回空数组（页面自己决定怎么提示）。 */
  function ensureSkills() {
    if (skills.length) return Promise.resolve(skills);
    if (pending) return pending;
    pending = A.get("/api/skills")
      .then(function (res) {
        skills = (res.items || [])
          .filter(function (s) { return s.runnable !== false && s.status === "available"; })
          .map(mergeSkill);
        skills.forEach(function (s) { SKILL_NAME[s.key] = s.name; });
        loadError = null;
        pending = null;
        return skills;
      })
      .catch(function (err) {
        loadError = err;
        pending = null;
        return [];
      });
    return pending;
  }

  /** 分类 chips：「推荐」是伪分类（等价于全部），其余来自接口 */
  function skillCategories() {
    const seen = {};
    const list = ["推荐"];
    skills.forEach(function (s) {
      if (s.cat && !seen[s.cat]) {
        seen[s.cat] = true;
        list.push(s.cat);
      }
    });
    return list;
  }

  function skillByKey(key) {
    return skills.filter(function (s) { return s.key === key; })[0] || null;
  }

  function skillLoadError() {
    return loadError;
  }

  window.CPCatalog = {
    NAV, RAIL_LABEL, PRESENTATION, AGENTS, SKILL_NAME,
    ensureSkills, skillCategories, skillByKey, skillLoadError,
    get skills() { return skills; },
  };
})();
