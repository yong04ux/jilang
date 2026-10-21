# CrossPilot Harness 插件说明（骨架）

把 CrossPilot 的两个业务能力注册为 Harness 模型可调用的工具：

| 工具 | 作用 | 对应 HTTP |
|---|---|---|
| `crosspilot_analyze` | 竞品分析 | `POST /api/analyze` |
| `crosspilot_generate_listing` | Listing 生成 | `POST /api/listings/generate` |

## 依赖

- CrossPilot 服务已启动（默认 `http://127.0.0.1:8123`）
- Node.js ≥ 20
- Harness 0.2.1-rc.2 及以上

## 构建

```powershell
cd integrations/harness-plugin
pnpm install
pnpm build
```

构建产物在 `lib/`，`package.json` 的 `main` 指向 `lib/index.js`。

## 启用（二选一）

1. **Web 插件页**：侧边栏 → Plugins → Install bundle → 输入 `link:<本目录绝对路径>`
2. **plugin_manager 工具**：让 Agent 调用 `install_bundle`（Creator 预设默认启用该工具）

两种方式都会修改 profile 的 `package.json` 与 `cordis.patch.yml`，**不要手工编辑**这两份文件。

## 验证状态（2026-10，本机实测）

已在本机完成：

| 检查 | 结果 |
|---|---|
| `pnpm/npm install` 拉取 `@deepseek-ai/dsh-tools@0.0.1-rc.1`、`@deepseek-ai/cordis@4.x` | ✅ |
| `npx tsc -p tsconfig.json` 严格模式编译 | ✅ 0 error |
| mock `ctx.tools` 注册，确认生成 2 个 `ToolDefinition` | ✅（`scripts/smoke.mjs`） |
| 真实调用 `/api/analyze`、`/api/listings/generate` | ✅ |
| 错误路径（不存在的 report_id）抛错 | ✅ |
| 在**真实 Harness 宿主进程**中加载本插件 | ❌ **未验证** |

冒烟脚本：

```powershell
# 1) 先启动 CrossPilot（8123 端口）
cd ..\.. ; $env:PYTHONPATH='.'; python -m crosspilot serve --port 8123

# 2) 另一个终端
cd integrations\harness-plugin
npm run build
node scripts/smoke.mjs
```

## 未验证事项（必读）

- 本插件**没有在真实 Harness 宿主中加载过**。在能写 profile 的环境中仍需验证：
  - 桌面端的 `@deepseek-ai/dsh-tools` 实际版本是否与 `0.0.1-rc.1` 的 peer 范围兼容；
  - `cordis.patch.yml` 的 bundle 字段名（当前骨架按 `dsh.bundle.patch` 猜测）；
  - `Config` 是否被 Cordis 正确校验（当前签名 `apply(ctx, config)`）。
- 若注册失败，优先检查 `ctx.tools.register()` 是否可用（需要 `dsh-tools` 已挂载），
  以及插件是否被 profile 的 bundles 列表加载。

## 与业务服务的关系

插件**不做**任何业务计算，只负责：

1. 把模型参数转成 CrossPilot 的请求体；
2. 调用 HTTP 接口；
3. 用一段简短的文本摘要渲染工具结果。

这样即便插件加载失败，CrossPilot 仍可独立运行；反之亦然。

## 本地快速验证（不经过 Harness）

```powershell
node --version              # >= 20
# 直接调用接口，确认服务契约
curl.exe -s http://127.0.0.1:8123/api/health
```
