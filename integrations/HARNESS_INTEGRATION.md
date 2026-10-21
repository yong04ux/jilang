# CrossPilot ↔ DeepSeek Harness 集成方案

本文件说明 CrossPilot 如何接入 **DeepSeek Harness 0.2.1-rc.2**。
结论先行：CrossPilot 的业务能力**已经**可以在 Harness 中通过以下两种**当前版本真实支持**
的方式使用；完整的 Cordis 宿主插件（`ctx.tools.register`）骨架也已提供，但**尚未在
真实 Harness 宿主中加载验证**，详见「未验证事项」。

---

## 1. 已核实的 Harness 扩展事实（2026-10，v0.2.1-rc.2）

| 事实 | 来源 | 对本项目的影响 |
|---|---|---|
| 桌面端为 Electron 打包，业务代码在 `app.asar` 内，**安装目录不可修改** | `D:\dsh`（`DeepSeek Harness.exe` FileVersion `0.2.1-rc.2`） | 不生成任何写入安装目录的补丁 |
| 插件体系是 **Cordis**，profile 位于 `%USERPROFILE%\.dsh\profiles\desktop` | `cordis.yml` / `cordis.patch.yml` / `package.json` 的 `dsh.profile.bundles` | 插件以 npm 包或 `link:` 本地包的形式加入 profile bundles |
| 工具通过 `ctx.tools.register(definition)` 注册，定义需含 `name / description / parameters / output / execute` | 官方 Reference · `subsystems/tools.md` | 插件骨架按此接口编写 |
| 工具参数与输出使用统一 JSON Schema DSL，或直接传原始 JSON Schema | 同上 | 骨架中两种都能一眼对应 |
| Skills 由 `ctx.skills` 提供，本地 provider 扫描 `<project>/.dsh/skills`、`<project>/.agents/skills`、`<dshHome>/skills` 等，目录包为 `<name>/SKILL.md` | 官方 Reference · `subsystems/skills.md` | 可直接放置 CrossPilot Skill，无需改 Harness |
| 官方 npm 包 `@deepseek-ai/dsh-tools` 存在（当前 0.0.1-rc.1），导出 `defineTool` 等 | `npm view @deepseek-ai/dsh-tools` | 插件开发时可作为 peer/runtime 依赖 |
| 官方文档站与 GitHub 仓库可公开访问 | `deepseek-harness.github.io` / `api.github.com` | 后续升级时以此为准 |

> 注意：文档站可访问，但本机 `web_fetch` 因 DNS 解析到非公网地址被拒绝；上述下载均通过
> PowerShell `Invoke-WebRequest` 完成。这不影响结论，但记录在此以便复现。

---

## 2. 集成方式 A（推荐，已验证可运行）：Skill + HTTP 工具

Harness 的模型可以调用 `bash` / `pwsh` 等工具执行命令。CrossPilot 提供：

1. **Skill**：`skills/crosspilot-listing/SKILL.md` —— 告诉 Agent 何时调用、如何传参、
   如何解读结果，以及**禁止编造事实**的硬性约束。
2. **HTTP 接口**：在 `backend/` 下 `python -m crosspilot serve` 后，模型用 `curl` / `Invoke-RestMethod`
   调用 `/api/analyze` 与 `/api/listings/generate`。

这条路径只依赖「安装目录外的东西 + 已存在的 shell 工具」，**不修改 Harness 任何文件**，
因此在当前桌面端上可以立即使用。

把 Skill 放进下列任一目录即可被发现（不需要重启 Harness，Skills provider 会监听文件变化）：

- `<你的项目根>/.dsh/skills/crosspilot-listing/SKILL.md`（项目级，推荐）
- `%USERPROFILE%\.dsh\skills\crosspilot-listing/SKILL.md`（用户级）

---

## 3. 集成方式 B（骨架已提供，未在宿主内加载验证）：Cordis 工具插件

目录：`integrations/harness-plugin/`

```
integrations/harness-plugin/
├── package.json          # type: module，声明 peer 依赖 @deepseek-ai/cordis / dsh-tools
├── src/index.ts          # apply(ctx) 中 ctx.tools.register(...)
├── README.md             # 安装、构建、启用与限制
└── tsconfig.json
```

插件在 `apply(ctx)` 中注册两个工具：

- `crosspilot_analyze`：把表单/导入数据 POST 到 `http://127.0.0.1:<port>/api/analyze`
- `crosspilot_generate_listing`：POST 到 `/api/listings/generate`

**为什么插件只做 HTTP 桥接，而不是在插件里重写业务逻辑？**

- 业务逻辑在 Python，与 Harness 解耦，可独立测试与部署；
- 插件只负责 schema 声明与网络调用，体积小、升级风险低；
- 未来若要把 LLM Provider 换成 Harness 宿主模型，只需在插件侧调用 `ctx.agents`
  并把结果回传 CrossPilot（见 `providers.py::HarnessProvider` 的预留说明）。

### 安装步骤（需要在可写 profile 的环境中执行）

```powershell
# 1) 构建插件（Node 24 + pnpm）
cd integrations/harness-plugin
pnpm install
pnpm build

# 2) 以 link 方式加入 profile（不要手工编辑 cordis.yml）
#    二选一：
#    a. Web 侧边栏 → Plugins → Install bundle → 选择 link:<绝对路径>
#    b. 使用 plugin_manager 工具（Creator 预设默认启用）
```

插件会把 CrossPilot 的 base URL 通过 `Config` 暴露，默认 `http://127.0.0.1:8123`。
Desktop 的包安装由 Desktop shell 管理，因此 **不要**期望 CLI 侧的 `dsh plugin` 命令
能改到这个 profile。

---

## 4. 未验证事项（必须如实告知用户）

1. `integrations/harness-plugin` **没有在真实 Harness 宿主中加载过**：当前环境无法
   （也不应）把未构建的 TypeScript 包注入正在运行的桌面端 profile。骨架的接口签名
   来自官方 Reference，但实际导入路径、`defineTool` 的运行时行为、以及 `Config`
   的 schema 校验**未做端到端验证**。
2. `providers.py` 中的 `harness` Provider **未实现**，选择它会明确报错并提示改用
   `rule` 或 `openai`。
3. `openai` Provider 需要真实 API Key；本次**没有**调用任何真实模型，所有测试与演示
   均使用本地规则引擎。
4. 平台字符限制与禁用词为**示例配置**，未经平台最新政策核验。

---

## 5. 升级检查清单

- [ ] 读 `cordis.patch.yml` 确认 profile 的 bundles 列表仍生效
- [ ] 用 `plugin_manager list_bundles` 查看插件加载状态与诊断
- [ ] 对照官方 `subsystems/tools.md` 核对 `ToolDefinition` 字段是否有变更
- [ ] 若 Harness 大版本升级，重新执行 `pnpm run verify-package-meta`（在 Harness 源码仓库内）
- [ ] 检查 `@deepseek-ai/dsh-tools` 的 peer 版本是否仍匹配
