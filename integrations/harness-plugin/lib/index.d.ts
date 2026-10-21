/**
 * CrossPilot → DeepSeek Harness 工具插件（骨架）
 *
 * 状态：已用真实的 `@deepseek-ai/dsh-tools@0.0.1-rc.1` 与
 * `@deepseek-ai/cordis@4.x` 类型定义**通过 TypeScript 编译**；
 * 但**尚未在真实 Harness 宿主进程中加载运行**（见 README 的未验证事项）。
 *
 * 真实接口依据（已在本机 node_modules 的 .d.ts 中核对）：
 * - `@deepseek-ai/dsh-tools` 通过 `declare module '@deepseek-ai/cordis'` 增强 Context，
 *   因此必须导入该模块（下面的 import 不是多余的）；
 * - `defineTool({ name, description, parameters, output: { schema, render }, execute })`
 *   是官方推荐的写法，参数与输出均有类型推导与运行时校验；
 * - 参数用 `{ type: 'string', required: true }` 这样的 per-property 形式；
 * - 输出根用 `{ type: 'json' }` 表示不约束的 JSON 值。
 */
import type { Context } from '@deepseek-ai/cordis';
export declare const name = "crosspilot-tools";
/** 由 Cordis 配置系统校验的插件配置。 */
export interface Config {
    /** CrossPilot 服务地址，默认本地 8123 端口。 */
    baseUrl: string;
    /** 单次请求超时毫秒数。 */
    timeoutMs: number;
}
export declare const DEFAULT_CONFIG: Config;
export declare function apply(ctx: Context, config?: Partial<Config>): void;
