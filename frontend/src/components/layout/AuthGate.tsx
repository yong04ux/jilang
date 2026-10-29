/**
 * 登录门。结构与文案逐条对齐旧 `js/auth.js`（登录 / 注册 / 首次建管理员三态 +
 * 一键体验），未登录时覆盖整屏，业务页面不渲染 —— 避免出现「点了没反应」的假界面。
 */
import { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/shared/Icon'
import { api } from '@/lib/api'
import { friendly, loadAuth, useAuthStore } from '@/stores/authStore'

type Mode = 'login' | 'register' | 'setup'

const DEMO_LABEL = '一键体验'

const POINTS = [
  '竞品分析：价格分布、评论痛点、差异化机会，附原文出处',
  'Listing 生成：基于已确认的商品事实，生成后再做一遍事实核对',
  '数据导入：先预览、再校对字段，有问题可下载清单逐条改',
  '自带模型密钥：平台不提供模型额度，也不保存你的密钥',
]

function toast(message: string, tone?: 'ok' | 'danger') {
  window.CPUi?.toast(message, tone)
}

export function AuthGate() {
  const gateOpen = useAuthStore((s) => s.gateOpen)
  const gateError = useAuthStore((s) => s.gateError)
  const allowRegister = useAuthStore((s) => s.allowRegister)
  const demoAccount = useAuthStore((s) => s.demoAccount)
  const guestTtl = useAuthStore((s) => s.guestTtl)
  const needsSetup = useAuthStore((s) => s.needsSetup)

  const [mode, setMode] = useState<Mode>('login')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [demoBusy, setDemoBusy] = useState(false)
  const [invalid, setInvalid] = useState<{ password?: boolean; confirm?: boolean }>({})
  const [revealPassword, setRevealPassword] = useState(false)
  const [revealConfirm, setRevealConfirm] = useState(false)

  const formRef = useRef<HTMLFormElement>(null)
  const usernameRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const confirmRef = useRef<HTMLInputElement>(null)

  /* 首次启动 → 建管理员；错误文案来自全局（401 / 连不上服务） */
  useEffect(() => {
    setMode(needsSetup ? 'setup' : 'login')
  }, [needsSetup])

  useEffect(() => {
    if (gateError !== null) setError(gateError)
  }, [gateError])

  /* 每次亮起来都把焦点放到第一个输入框（auth.js:279-280） */
  useEffect(() => {
    if (gateOpen) usernameRef.current?.focus()
  }, [gateOpen, mode])

  const isRegister = mode !== 'login'
  const title = mode === 'setup' ? '创建管理员账号' : isRegister ? '创建账号' : '登录'
  const submitLabel = isRegister ? '创建账号' : '登录'
  const busyLabel = isRegister ? '正在创建…' : '正在登录…'
  const hint =
    mode === 'setup'
      ? '这是首次启动，第一个注册的账号会成为管理员，请牢记账号密码。'
      : isRegister
        ? '用户名至少 3 个字符，密码至少 8 位。'
        : ''

  const clearError = () => {
    if (error === null && !invalid.password && !invalid.confirm) return
    setError(null)
    setInvalid({})
  }

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    clearError()

    const username = usernameRef.current?.value.trim() ?? ''
    const password = passwordRef.current?.value ?? ''

    if (isRegister && password !== (confirmRef.current?.value ?? '')) {
      setInvalid({ password: true, confirm: true })
      setError('两次输入的密码不一致，请重新确认。')
      confirmRef.current?.focus()
      return
    }

    setBusy(true)
    try {
      await api.post(mode === 'login' ? '/api/auth/login' : '/api/auth/register', {
        username,
        password,
      })
      // 登录成功但会话没读回来（网络抖动）：不能静默放行，否则页面空着也没提示
      if (!(await loadAuth(true))) {
        setError('账号信息读取失败，请重新登录一次。')
        return
      }
      window.dispatchEvent(new CustomEvent('cp:authenticated'))
    } catch (err) {
      setError(friendly(err))
    } finally {
      setBusy(false)
    }
  }

  const onDemo = async () => {
    clearError()
    setDemoBusy(true)
    try {
      const data = await api.post<{ expires_in_hours?: number }>('/api/auth/demo', {})
      if (!(await loadAuth(true))) {
        setError('临时账号已创建，但会话没有读到，请刷新页面重试。')
        return
      }
      window.dispatchEvent(new CustomEvent('cp:authenticated'))
      const hours = data?.expires_in_hours ? data.expires_in_hours : 24
      toast(`临时账号已创建，${hours} 小时后自动清理`, 'ok')
    } catch (err) {
      setError(friendly(err))
    } finally {
      setDemoBusy(false)
    }
  }

  return (
    <div id="auth-gate" className="auth-gate" hidden={!gateOpen}>
      {gateOpen && (
        <div className="auth-shell">
          <aside className="auth-pitch">
            <div className="auth-lockup">
              <img className="auth-lockup-mark" src="/media/logo-mark.svg?v=2" alt="" />
              <span className="auth-lockup-name">激浪</span>
              <span className="auth-lockup-tag">跨境电商 AI 运营助手</span>
            </div>
            <h2 className="auth-headline">
              把业务目标
              <br />
              变成可复核的执行结果
            </h2>
            <p className="auth-lede">
              竞品分析、Listing 撰写、数据导入与人工审批在同一个流程里完成。每一步都能看到当前状态和判断依据，结果不会替你编造销量或排名。
            </p>
            <ul className="auth-points">
              {POINTS.map((text) => (
                <li className="auth-point" key={text}>
                  <Icon name="check" />
                  <span>{text}</span>
                </li>
              ))}
            </ul>
            <p className="auth-note">
              页面里的示例数据都带「示例」标记，导入你自己的文件后就会换成你的数据。
            </p>
          </aside>

          <div className="auth-card">
            <div className="auth-card-head">
              <img className="auth-card-mark" src="/media/logo-mark.svg?v=2" alt="" />
              <div>
                <h1 className="auth-title">{title}</h1>
                {hint && (
                  <p className="auth-hint" id="auth-hint">
                    {hint}
                  </p>
                )}
              </div>
            </div>

            <form
              id="auth-form"
              className="auth-form"
              autoComplete="on"
              aria-describedby={hint ? 'auth-hint' : undefined}
              ref={formRef}
              onSubmit={onSubmit}
              onInput={clearError}
            >
              <div className="field">
                <label className="field-label" htmlFor="auth-username">
                  用户名
                </label>
                <input
                  id="auth-username"
                  name="username"
                  required
                  minLength={3}
                  maxLength={32}
                  placeholder="至少 3 个字符"
                  autoComplete="username"
                  ref={usernameRef}
                  defaultValue=""
                />
              </div>

              <div className={invalid.password ? 'field is-invalid' : 'field'}>
                <label className="field-label" htmlFor="auth-password">
                  密码
                </label>
                <span className="auth-group">
                  <input
                    id="auth-password"
                    name="password"
                    type={revealPassword ? 'text' : 'password'}
                    required
                    minLength={8}
                    placeholder="至少 8 位"
                    autoComplete={isRegister ? 'new-password' : 'current-password'}
                    ref={passwordRef}
                    defaultValue=""
                  />
                  <button
                    type="button"
                    className="auth-reveal"
                    data-reveal="auth-password"
                    aria-label={revealPassword ? '隐藏密码' : '显示密码'}
                    aria-pressed={revealPassword ? 'true' : 'false'}
                    onClick={() => {
                      setRevealPassword((v) => !v)
                      passwordRef.current?.focus()
                    }}
                  >
                    <Icon name={revealPassword ? 'eyeOff' : 'eye'} />
                  </button>
                </span>
              </div>

              {isRegister && (
                <div className={invalid.confirm ? 'field is-invalid' : 'field'}>
                  <label className="field-label" htmlFor="auth-confirm">
                    确认密码
                  </label>
                  <span className="auth-group">
                    <input
                      id="auth-confirm"
                      name="confirm"
                      type={revealConfirm ? 'text' : 'password'}
                      required
                      minLength={8}
                      placeholder="至少 8 位"
                      autoComplete="new-password"
                      ref={confirmRef}
                      defaultValue=""
                    />
                    <button
                      type="button"
                      className="auth-reveal"
                      data-reveal="auth-confirm"
                      aria-label={revealConfirm ? '隐藏密码' : '显示密码'}
                      aria-pressed={revealConfirm ? 'true' : 'false'}
                      onClick={() => {
                        setRevealConfirm((v) => !v)
                        confirmRef.current?.focus()
                      }}
                    >
                      <Icon name={revealConfirm ? 'eyeOff' : 'eye'} />
                    </button>
                  </span>
                </div>
              )}

              <p className="auth-error" id="auth-error" role="alert" hidden={!error}>
                {error && (
                  <>
                    <Icon name="alert" />
                    <span>{error}</span>
                  </>
                )}
              </p>

              <button type="submit" className="btn btn-primary btn-lg auth-submit" disabled={busy}>
                {busy ? busyLabel : submitLabel}
              </button>
            </form>

            {isRegister ? (
              <p className="auth-alt">
                <button
                  type="button"
                  className="btn-link"
                  id="auth-switch"
                  onClick={() => {
                    setMode('login')
                    setError(null)
                    setInvalid({})
                  }}
                >
                  返回登录
                </button>
              </p>
            ) : allowRegister ? (
              <p className="auth-alt">
                还没有账号？{' '}
                <button
                  type="button"
                  className="btn-link"
                  id="auth-switch"
                  onClick={() => {
                    setMode('register')
                    setError(null)
                    setInvalid({})
                  }}
                >
                  立即注册
                </button>
              </p>
            ) : null}

            <div className="auth-divider">
              <span>或</span>
            </div>

            <button
              type="button"
              className="btn btn-secondary btn-lg auth-demo-btn"
              id="auth-demo"
              disabled={demoBusy}
              onClick={onDemo}
            >
              <Icon name="sparkles" />
              <span className="auth-demo-label">{demoBusy ? '正在创建…' : DEMO_LABEL}</span>
            </button>
            <p className="auth-demo-note">
              创建一个 {guestTtl} 小时临时账号，内容与密钥单独保存，到期自动清理。
              {demoAccount ? (
                <>
                  <br />
                  体验账号 <code>demo</code> 可直接浏览示例数据，但不能保存密钥。
                </>
              ) : null}
            </p>

            <p className="auth-foot">密码与密钥只用于你的账号，不会出现在任何执行结果里。</p>
          </div>
        </div>
      )}
    </div>
  )
}
