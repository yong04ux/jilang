# 激浪（Cross-border AI Workspace）设计规范

> 版本：2.0 · 体系：**shadcn/ui · Nova** + **Lucide** + **Motion**
> 适用：当前原生 HTML/CSS/JavaScript 前端（无构建步骤）

## 0. 体系选型说明

统一采用一套外部成熟体系，不再自造视觉语言。对应关系：

| 领域 | 参照体系 | 本项目落地方式 |
|---|---|---|
| UI 风格 | shadcn/ui · Nova | 语义 Token + 组件样式（`css/tokens.css`、`components.css`） |
| 图标 | Lucide | 真实 Lucide 路径数据（`js/icons.js`，24 栅格 / 2px 描边） |
| 动画 | Motion | Web Animations API 封装（`js/motion.js`），曲线统一取 Token |
| 布局分栏 | react-resizable-panels | `js/panels.js` 的 `split()`，比例持久化 + 键盘可调 |
| 拖拽 | dnd-kit | `js/panels.js` 的 `sortable()`，原生拖拽重排 |
| 状态管理 | Zustand | `js/store.js` 的 `create()`，选择器订阅 + 持久化 |

**为什么不是直接装这些 npm 包**：前端是无构建的原生工程（后端 FastAPI 直接托管静态文件，
Render 单服务部署）。shadcn/ui、Motion(React)、react-resizable-panels、dnd-kit、Zustand
都是 React 生态包，引入任意一个都需要加 Vite/React 构建链，会同时改掉部署形态。
因此按"**同一套设计语言 + 等价能力**"落地：视觉、图标、曲线、交互模型对齐上游，
实现保持零依赖。后续如果迁移到 React，`components.css` 的组件清单和 Token 名可以直接
映射到 shadcn 组件，`store.js` 的 API 与 Zustand 一致，迁移成本可控。

## 1. 设计目标

激浪是跨境电商 AI 运营工作台。视觉表达**智能、行动、增长、可靠**，不做泛化的"未来科技后台"。

核心原则：

- **边框优先，阴影克制**。层级靠 1px 边框和留白建立，不用玻璃、渐变、发光。
- **品牌蓝是强调色，不是背景色**。蓝色只出现在主操作、链接、焦点环、选中图标。
- **紧凑**。14px 正文、32px 控件、12–20px 内边距，信息密度优先。
- **数据密集区高可读**。表格、表单保持纯白底、高对比，不叠加任何透明效果。
- **演示数据必须诚实标注**，不把模拟结果呈现成真实店铺数据。
- **真实交互优先**，动效不得盖过功能，且必须尊重 `prefers-reduced-motion`。

## 2. 色彩 Token

命名沿用 shadcn 的语义层，页面只用语义名，不写死色值。

| Token | 值 | 用途 |
|---|---|---|
| `--background` | `#FAFAFA` | 页面底（中性 50） |
| `--card` | `#FFFFFF` | 卡片、表格、输入框 |
| `--foreground` | `#0A0A0A` | 主文字（中性 950） |
| `--muted-surface` | `#F5F5F5` | 表头、骨架、禁用底 |
| `--muted-foreground` | `#737373` | 辅助文字 |
| `--border` | `#E5E5E5` | 唯一分隔线颜色 |
| `--primary` | `#1B6EF3` | 主操作、链接、焦点环、选中图标 |
| `--primary-hover` | `#1560DC` | 主操作 Hover |
| `--ring` | `#1B6EF3` | 焦点环 |

语义色独立于主色，禁止用蓝色替代成功/警告/错误：

| Token | 值 | 用途 |
|---|---|---|
| `--success` / `--ok` | `#15803D` | 已完成、已连接 |
| `--warning` / `--warn` | `#B45309` | 等待审批、示例数据、降级 |
| `--destructive` / `--danger` | `#DC2626` | 失败、删除 |
| `--info` | `#2563EB` | 演示提示条、中性信息 |

**强调色的使用配额**：一屏内品牌蓝面积不应超过 5%。默认按钮是白底描边，只有页面的
"唯一主操作"才用 `.btn-primary`。导航选中态用中性底 + 蓝色图标，不用蓝色填充。

旧变量名（`--bg` / `--surface` / `--ink` / `--brand` / `--line` …）保留为兼容别名，
新代码一律用语义名。

## 3. 字体与字号

- 字体栈：`Inter` → `Geist` → 系统字体（PingFang SC / Microsoft YaHei）。
  **不加载外部 Web Font**（Google Fonts 在境内不可用），本机装了 Inter 就自动生效。
- 正文 14px / 行高 1.5；辅助 13px；元信息 12px；卡片标题 14px/600；页面标题 20px/600。
- 数字统一 `font-variant-numeric: tabular-nums`，统计值与表格数字必须用。
- 标题字距 `-.02em` 左右，正文不加字距。

## 4. 图标

- 全部取自 **Lucide**（ISC 许可），24×24 栅格、2px 描边、圆头圆角。
- 路径数据固化在 `js/icons.js`，key 沿用旧名（`dashboard` / `tasks` / `listing` …），
  页面代码不需要关心图标来源。新增图标时从 `lucide-static` 取路径追加。
- 视觉尺寸：侧栏 16px、按钮 14px、顶栏 12px、空态 20px。
- 颜色继承文字；选中项与主操作用品牌蓝；语义状态用语义色。
- **不给每个图标套彩色底块**。只有品牌 Logo、空状态、数据源类型提供图形容器，
  且容器是中性底 + 1px 边框，不用渐变。
- 命名对照：`research`→telescope、`competitors`→grid-2x2、`assets`→image、
  `operations`→chart-column、`skills`→puzzle、`workflows`→workflow、`agents`→bot。

## 5. 形状、间距、高度

- 圆角：控件与徽章 `6px`（`--radius-sm`）、卡片 `10px`（`--radius-lg`）、
  浮层 `12px`（`--radius-xl`）。**不使用胶囊形**（旧版 pill 全部改为圆角矩形）。
- 间距只用四档主值：`4 / 8 / 12 / 16`，结构间距可用 `20 / 28`。
- 控件高度：`24 / 28 / 32 / 36`（`--h-xs/sm/md/lg`），默认 32。
- 阴影只用于浮层：卡片无阴影，Hover 不改阴影；弹层用 `--shadow-lg`。
- 侧栏 208px（收起 56px），顶栏 48px，内容边距 20px。

## 6. 组件规则

| 组件 | 规则 |
|---|---|
| Button | 默认白底描边；`primary` 品牌蓝；`secondary` 中性填充 + 描边；`quiet` 无边框；`danger` 红描边。三档高度 28/32/36 |
| Badge | 20px 高、6px 圆角、11px 字。语义色用浅底 + 同色描边 + 深字；示例数据必须虚线边框 |
| Card | 白底 + 1px 边框 + 10px 圆角，**无阴影**。不是所有内容都卡片化，仅独立可操作单元 |
| Table | 无斑马纹、表头无底色，靠行分隔线；行高 44px；数字右对齐 |
| Tabs | 两套：页面级用下划线式（选中为前景色 2px 下划线，不用蓝色）；控件级用 `segmented`（静默底 + 白滑块） |
| Chip | 28px 高；选中态用**前景色底 + 背景色字**（反向），不用蓝色填充 |
| Input / Select | 32px 高、6px 圆角、`--input` 描边；聚焦时品牌蓝描边 + 3px 淡蓝光圈；Select 用统一 chevron |
| Empty | 40px 中性图标容器 + 标题 + 说明 + 最多两个操作 |
| Skeleton | 中性底 + 透明度脉冲，不用流光扫过 |
| Toast | 浅色卡片 + 语义色图标，不用整块深色 |
| Modal / Drawer | 遮罩 `rgba(10,10,10,.5)`，浮层白底 + 1px 边框 + 大阴影 |

**禁止**：`backdrop-filter` 玻璃、渐变背景、彩色发光、卡片 Hover 浮起、胶囊按钮/徽章。

## 7. 动效（Motion）

统一曲线与时长，写在 Token 里，CSS 与 JS 共用：

| Token | 值 | 用途 |
|---|---|---|
| `--ease-out` | `cubic-bezier(.16,1,.3,1)` | 出现、位移（默认） |
| `--ease-in-out` | `cubic-bezier(.4,0,.2,1)` | 循环动画 |
| `--dur-1` | 120ms | 颜色、边框、Hover |
| `--dur-2` | 180ms | 进场、Toast、Modal |
| `--dur-3` | 280ms | 抽屉、分栏 |

`js/motion.js` 提供 `animate / fadeIn / fadeOut / stagger / inView / tap`，基于 Web
Animations API。当前用在：页面进场（主区块按 22ms 交错淡入）、Toast 进出、浮层进场。
新增动效优先用 `CPMotion`，不要在业务代码里写死 `transition` 时长。

**硬约束**：`prefers-reduced-motion: reduce` 下所有时长归零并与 CSS 同步，
功能不受影响。

## 8. 布局与交互原语

- **分栏**：`CPPanels.split(el, { storageKey, defaultSize, min, max })`。
  在容器前两个子节点之间插入 1px 拖拽条，比例写入 `--split-a`，落 localStorage；
  支持方向键 ±2%（Shift ±8%）、Home/End 到边界、双击复位；
  `role="separator"` + `aria-valuenow` 可访问。
- **拖拽重排**：`CPPanels.sortable(list, { item, onEnd })`，原生 `draggable`，
  结束后回调返回新顺序的 `data-id` 数组。
- **状态**：`CPStore.create(initializer)`，API 与 Zustand 一致
  （`getState / setState / subscribe`），`subscribe(selector, fn)` 只在选中值变化时触发；
  `CPStore.persist(store, key, pick)` 做 localStorage 持久化。
  当前外壳的侧栏折叠、提示条关闭已迁移到 store。
- **响应式**：≤960px 分栏退化为上下堆叠并隐藏拖拽条；≤980px 侧栏只留图标；
  ≤720px 表格转卡片、页面头改纵向。

## 9. 数据资产页面规则

- 页面标题：数据资产。说明文案以用户任务为中心，避免 "Mock / Seed / Connector" 等工程术语。
- 顶部全局提示用"演示环境"表达数据来源，不解释内部模拟实现。
- 隐藏普通用户不需要的数据源内部 ID；诊断场景按需提供。
- 字段映射下拉优先显示中文业务名称，底层 key 不变。
- 演示数据用统一"示例数据"标记，导入数据显示"已导入"。
- 不得把模拟数据标记成已连接店铺数据。
- 导入、校验、提交、错误 CSV 导出等现有接口行为必须保留。

## 10. 交互与可访问性

- 所有按钮保留 hover / active / disabled / focus-visible 状态。
- 不用颜色作为唯一状态提示；状态同时提供文字。
- 焦点环统一 `outline: 2px solid var(--ring)` + 2px offset，不用 box-shadow 伪焦点。
- 保持键盘导航；分栏拖拽条可用方向键操作。
- 尊重 `prefers-reduced-motion`。
- 错误提示说明用户可以采取的下一步，内部堆栈留在日志。
- 移动端避免侧栏、表格和卡片产生横向溢出。

## 11. 用户可见文案

界面上只出现**用户要做的判断**和**用户能采取的动作**，不出现实现细节。

**禁止出现在 UI 里的词**：HttpOnly / Cookie / 会话凭据 / 日志 / 模型上下文 / 接口 /
端点 / endpoint / payload / schema / 注册表 / skill_key / is_mock / seed / Mock / BYOK /
哈希 / 序列化 / 事务。

**写法对照**：

| 不要写 | 改成 |
|---|---|
| 会话凭据由 HttpOnly Cookie 承载 | （直接删掉，不解释怎么实现） |
| 密码经加盐哈希后保存在数据库 | （删掉） |
| 密钥不会写入日志，也不会进入模型上下文 | 密码与密钥只用于你的账号，不会出现在任何执行结果里 |
| 数据导入：预览 → 字段映射 → 提交 → 错误 CSV | 数据导入：先预览、再校对字段，有问题可下载清单逐条改 |
| Mock 连接 / Mock 徽章 | 演示连接 / 示例 |
| 平台发布接口尚未接入 | 目前只能记录审批结论，还不会真的发布到平台 |

**原则**：

1. 说结果和边界，不说机制。诚实说明"还没接"是必须的，但不能用工程词汇表达。
2. 面向用户用业务名词（商品标题、五点描述、价格），不用字段名和内部 key。
3. 示例数据统一用「示例」标识，不用「Mock」「演示数据」混着叫。

## 12. 验收清单

- [ ] 页面底色 `#FAFAFA`、卡片纯白 + 1px 边框、无阴影、无玻璃、无渐变。
- [ ] 品牌蓝只出现在主操作、链接、焦点环、选中图标。
- [ ] 图标全部为 Lucide 形态（24 栅格 / 2px 描边），无描边粗细混用。
- [ ] 控件高度 32px、圆角 6px、卡片圆角 10px，无胶囊形。
- [ ] 表格无斑马纹、表头无底色、数字右对齐。
- [ ] 动效统一用 `--dur-*` / `--ease-*`，`reduced-motion` 下全部关闭。
- [ ] 工作台左右栏可拖拽，刷新后比例保持，键盘可调。
- [ ] 不向普通用户展示 Mock / Seed / 接口 / Cookie 等开发者术语。
- [ ] 模拟数据与用户导入数据能被清楚区分。
- [ ] 原有路由、上传、校验、字段映射和提交功能未被视觉改造破坏。
