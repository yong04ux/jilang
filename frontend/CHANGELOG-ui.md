# 前端视觉体系变更记录

## v2.2 · 界面只留业务语言

这一版不换视觉，只清内容：把「给开发者看的」从界面里清出去，每一处都按它背后的  
**业务状态**重新表述，而不是换个说法继续展示。

### 判断标准

1. 开发标记（Mock / TODO / Placeholder / Stub）、内部实现说明（接口未接入、暂未实现）     
   → **不是换个词，而是删掉或改成下一步动作**。
2. 内部标识（`trace_id` / `task_id` / `skill_key` / `base_url` / `rule` / `US` / `en-US`）     
   → **数据层保留，展示层翻译**；统一走 `js/labels.js` 的 `CPLabel`。
3. 为了填版面编出来的数字（销售额 / 订单量 / 转化率）     
   → **整块删除**，换成空态说明。
4. 用户根本走不到的入口（未开放的能力）     
   → **不进导航、不进路由**，直接 404，界面上不解释「为什么还没做」。

### 变更

- **导航与路由**：去掉 5 个点不开的入口（解析 / 素材 / 运营 / 工作流 / 知识库）与 `soon` 徽章；    
  `/app.js` 里对应路由一并删除，未开放能力落到 404。
- **Agent 与技能库**：卡片去掉 `agent_key`、`v1`、`Beta`、`可用` 徽章、DAG 说明；    
  技能表改为「能做什么 / 你需要准备 / 你会得到」三列，不再列 `skill_key` 与 schema。
- **店铺与渠道**：`Mock` / `Live` / `mode` → 「示例店铺 / 已连接 / 未设置 / 你的文件」；    
  删除虚构的订单量、销量、收入、客单价四张指标卡。
- **任务中心**：去掉 `task_id`、`error_code`、`requested_by`、原始 JSON 输出块；    
  审批文案从「通过也不会真实发布——平台接口尚未接入」改为「通过后把内容复制到店铺后台，在那里完成发布」。
- **工作台**：删除「原始」Tab（`resultRawPane` 整块是 `task_id` / `degraded_reason` 的调试转储）；    
  「已降级执行」→「执行参数是按文字推断的」。
- **Listing 工作室**：质检问题标题从 `issue.code`（`unsupported_claim` 之类）    
  改为严重程度（必须改 / 建议改 / 提示）+ 中文位置。
- **设置**：成员表去 `user_id`；审计表把 28 个 action 代码翻成中文动作、对象类型翻成中文；    
  删除「数据可以模拟，标记必须真实」整段开发者说明；`BYOK` 全部移除。
- **数据资产**：逐行错误表的字段名从 `<code>product_name</code>` 改为中文。
- **报告渲染**：`report.engine` → 规则生成 / AI 模型生成；平台 / 站点 / 语言 / 章节名 /    
  证据字段 / 事实台账来源全部翻译；置信度 `medium` → 中。
- **竞品分析表单**：原来让人粘贴 JSON（帮助文案写着「必填 `name`；可选 price / rating / reviews / is_demo」），    
  改成结构化的竞品卡片——名称 / 价格 / 评分 / 评论数 / 一条真实评论，可增删；    
  关键词改成「词 | 搜索量 | 排名」每行一条。工作台同样改成每行一个竞品。
- **空态措辞**：评论洞察在样本不足时从「没有评论样本，无法做主题挖掘」    
  改为「已收到 N 条评论样本，还不足以归纳主题」，不再和表格里的样本数自相矛盾。

### 后端配套（面向用户的文案）

新增 `backend/crosspilot/labels.py`，在接口边界把内部标识翻成业务语言：

- `humanize_field()`：`body.competitors[0].own_price` → `竞品 · 第 1 项 · 你的价格`
- `humanize_message()`：Pydantic 的 `Field required` / `Input should be a valid number`    
  → `必填，不能为空` / `需要数字`
- `engine_label()` / `data_source_label()` / `language_label()`：`rule` / `manual` / `en-US`    
  → `规则生成` / `手工填写` / `英文`

接入点：`app.py` 两个 422 处理器、`api/helpers.py`、`api/imports.py`、  
`services/import_service.py`、`services/report_service.py`、`ingest/importers.py`、  
`engine/listing_llm.py`、`llm/llm.py`。

同时清掉了若干直接把实现细节写给用户的字符串：`配置 CROSSPILOT_DEEPSEEK_API_KEY 后重新生成`、  
`生成引擎：rule-fallback`、`{type(exc).__name__}: {exc}`（把 Python 异常类名写进导入错误）、  
`缺少必填字段 name（商品名称）`。

### 新增文件

- `frontend/js/labels.js` —— `CPLabel`：站点 / 语言 / 平台 / 字段 / 任务类型 / 严重程度。    
  `index.html` 在 `catalog.js` 之后引入。单一来源，工作台、任务中心、报告、草稿共用一套说法。
- `backend/crosspilot/labels.py` —— 后端侧同名能力（Python）。

### 验证

- `node --check` 全部前端脚本通过；`compileall` 后端通过。
- `scripts/ui_shots_login.mjs` 七种状态全绿。
- `scripts/ui_shots_auth_v2.mjs` 十页 0 控制台错误。    
  其中 `/competitors`、`/listings`、`/data` 的 `callout-danger` 是「还没填 API Key」的正常提示。
- 接口实测：缺字段 → `竞品 · 第 1 项 · 价格：需要数字`；    
  多余字段 → `这一项不用填，删掉即可`；导入解析失败 → 不再出现异常类名。
- 端到端跑通一次竞品分析：报告头 `Amazon · 美国站`、竞品表 `还缺 核心卖点、规格、品牌`、    
  建议区 `机会 中 / 置信 中`、章节 `A+ 内容 / 主图 / 标题`。

## v2.1 · 登录页重做

只动 `js/auth.js` 的渲染部分与 `css/pages.css` 的 `.auth-*` 段，  
认证状态、接口路径、事件派发（`cp:authenticated` / `cp:logout`）全部保持原样。

### 变更

- **信息层次**：左侧品牌叙事重排——标题改两行阶梯式（`把业务目标 / 变成可复核的执行结果`），    
  正文按 46ch 限宽；四条卖点的对勾图标从绿色改为中性描边，    
  避免四条绿勾给人「已全部完成」的错觉。
- **卡片去阴影**：`.auth-card` 不再挂 `.card` 类，改用 1px 边框建立层次（Nova 零阴影）。
- **密码可见性**：新增 `eye` / `eyeOff` 图标（`js/icons.js`），    
  密码框右侧加切换按钮，带 `aria-pressed` 与随状态变化的 `aria-label`。    
  按钮放在 `label` 之外——`label` 内只允许被标记的那个控件，嵌套 `button` 属非法结构。
- **错误提示**：改为表单内联条（`role="alert"` + 图标），不再整页 toast。    
  `api.js` 已区分「凭据错误」与「会话过期」，这里直接展示服务端中文原文；    
  网络层错误统一翻成「连不上服务，请检查网络后重试」。
- **加载态**：按钮文案从「处理中…」改为具体动作（`正在登录…` / `正在创建…`），    
  demo 按钮只换 label 文本，不再销毁重建图标。
- **矮屏裁切修复**：`.auth-gate` 由 `align-items: center` 改为    
  `.auth-shell { margin: auto }`。前者在内容高于视口时会把卡片顶部裁掉且滚不上去，    
  实测 560px 高视口下现在 `cardTop=40`、`scrollHeight 617 > clientHeight 560`，顶部可见可滚。
- **点阵背景**：保留但加径向遮罩渐隐，避免整屏网格显得死板。

### 验证

`frontend/scripts/ui_shots_login.mjs` 覆盖六种状态（默认 / 密码可见 / 密码错误 /  
注册态 / 760px 窄屏 / 560px 矮屏），另跑全站 10 页回归：0 控制台错误。  
密码错误实测提示「用户名或密码不正确」，不再误报「登录已过期」。

## v2.0 · 迁移到 shadcn/ui · Nova

液态玻璃方案已整体下线，不再有 `css/liquid-glass.css`。当前体系见 `design.md`。

### 变更

- **Token 重建**：`css/tokens.css` 改为 shadcn 语义层    
  （`--background / --card / --foreground / --muted-surface / --border / --primary / --ring`），    
  旧变量名保留为兼容别名，页面样式无需改动。
- **组件重写**：`css/components.css`、`css/layout.css`、`css/base.css` 按 Nova 规范重写——    
  边框优先、无阴影、控件 32px、圆角 6px / 卡片 10px、胶囊形全部改圆角矩形。
- **去掉玻璃**：全站移除 `backdrop-filter`、渐变背景、彩色发光；数据资产页 Hero 与统计卡    
  改为中性底 + 1px 边框。`frontend/css/liquid-glass.css` 删除。
- **图标换 Lucide**：`js/icons.js` 用真实 Lucide 路径数据重建（24 栅格 / 2px 描边），    
  key 不变，共 56 个图标。
- **动效层**：新增 `js/motion.js`（Web Animations API，曲线与时长取自 Token），    
  页面进场、Toast、浮层进场统一走它。
- **分栏与拖拽**：新增 `js/panels.js`，提供 `split()`（工作台左右栏可拖拽、比例持久化、    
  键盘可调）与 `sortable()`（列表拖拽重排）。
- **状态管理**：新增 `js/store.js`（Zustand 同构 API），外壳的侧栏折叠与提示条关闭已迁移。
- **下拉框**：原生 `select` 去掉系统箭头，统一为 Lucide chevron。

### 验证

本地后端 + Edge headless 逐页实测：11 个核心页面 0 控制台错误，  
分栏组件实测左 749px / 右 458px（总 1208px，比例 62%），`aria-valuenow` 正确。
