/**
 * API 客户端 —— 与旧 `frontend/js/api.js`（97 行）语义逐条对齐。
 *
 * 四条不可改的行为（页面全靠它们分支）：
 *  1. 同源 Cookie 会话：`credentials: "same-origin"`，不加 Authorization、不读 token；
 *  2. 网络层失败 → `ApiError("网络不可用，请确认服务仍在运行", 0, null)`；
 *  3. 业务接口 401 → 先调 unauthorizedHandler，再抛「登录已过期」；
 *     但入口接口（登录/注册）的 401 必须走正常报错，否则「密码错了」会被
 *     显示成「登录已过期」；
 *  4. 非 2xx → `detail = data?.detail ?? data`，文案由 `describe()` 拼装。
 *
 * 页面用 `err.status === 428 / 422 / 409` 做分支，所以 status 与 detail 必须原样带出。
 */

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
    // es2020 目标下 Error 子类的原型链需要手动修复，否则 instanceof 失效
    Object.setPrototypeOf(this, ApiError.prototype)
  }
}

/** 登录 / 注册这类「入口」接口：401 表示账号密码不对，不是会话过期 */
const AUTH_ENTRY_PATHS = ["/api/auth/login", "/api/auth/register"] as const

export function isAuthEntry(path: string): boolean {
  return AUTH_ENTRY_PATHS.some((p) => path.indexOf(p) === 0)
}

interface DetailLike {
  message?: string
  code?: string
  errors?: Array<{ field?: string; row?: number; message?: string }>
}

/** 把后端 detail 拼成中文可读文案；与旧实现逐字一致 */
export function describe(detail: unknown, status: number): string {
  if (!detail) return `请求失败（HTTP ${status}）`
  if (typeof detail === "string") return detail
  if (typeof detail === "object" && detail !== null) {
    const d = detail as DetailLike
    if (d.message) {
      const errors = Array.isArray(d.errors) ? d.errors : []
      if (!errors.length) {
        // 后端的 code 是内部分类，不进界面；只对「缺 Key」这一类做可读补充
        const hint =
          d.code === "api_key_required" ? "（需要先在设置里填入 API Key）" : ""
        return d.message + hint
      }
      const first = errors.slice(0, 3).map((e) => {
        const field = e.field ? e.field + "：" : e.row ? "第 " + e.row + " 行：" : ""
        return field + (e.message || "")
      })
      return d.message + " · " + first.join("；")
    }
  }
  if (Array.isArray(detail)) {
    return detail
      .map((e) =>
        e && typeof e === "object" && "msg" in e
          ? String((e as { msg?: unknown }).msg ?? "")
          : JSON.stringify(e),
      )
      .join("；")
  }
  return String(detail)
}

export type HttpMethod = "GET" | "POST" | "PUT" | "DELETE"

export interface RequestOptions {
  method?: HttpMethod
  /** 会被 JSON.stringify 并带 Content-Type: application/json */
  body?: unknown
  /** 原样作为 body，Content-Type 交给浏览器（multipart boundary） */
  form?: FormData
  headers?: Record<string, string>
}

type UnauthorizedHandler = (() => void) | null
let unauthorizedHandler: UnauthorizedHandler = null

export async function request<T = unknown>(
  path: string,
  options?: RequestOptions,
): Promise<T> {
  const opts = options ?? {}
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(opts.headers ?? {}),
  }
  const init: RequestInit = {
    method: opts.method ?? "GET",
    credentials: "same-origin",
    headers,
  }
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json"
    init.body = JSON.stringify(opts.body)
  }
  if (opts.form !== undefined) {
    init.body = opts.form
  }

  let resp: Response
  try {
    resp = await fetch(path, init)
  } catch {
    throw new ApiError("网络不可用，请确认服务仍在运行", 0, null)
  }

  const text = await resp.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }

  /* 只有业务接口的 401 才代表登录态失效；入口接口的 401 走下面的正常报错流程 */
  if (resp.status === 401 && !isAuthEntry(path)) {
    if (unauthorizedHandler) unauthorizedHandler()
    const detail = (data as { detail?: unknown } | null)?.detail
    throw new ApiError("登录已过期，请重新登录", 401, detail)
  }

  if (!resp.ok) {
    const detail =
      data && typeof data === "object" && "detail" in (data as object)
        ? (data as { detail: unknown }).detail
        : data
    throw new ApiError(describe(detail, resp.status), resp.status, detail)
  }
  return data as T
}

export const api = {
  request,
  get: <T = unknown>(path: string) => request<T>(path),
  post: <T = unknown>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body }),
  put: <T = unknown>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body }),
  del: <T = unknown>(path: string, body?: unknown) =>
    request<T>(path, { method: "DELETE", body }),
  postForm: <T = unknown>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", form }),
  onUnauthorized(fn: UnauthorizedHandler) {
    unauthorizedHandler = fn
  },
}
