/**
 * 设置 —— 从旧 `js/pages/settings.js` 迁移。
 *
 * 三条关键约束（原文保留）：
 *  - Key 只显示掩码；保存后立即生效；
 *  - 固定 demo 账号禁止写入任何配置（后端 403，前端提前拦）；
 *  - 自定义 base_url 必须显式勾选，否则只允许预置厂商域名（防 SSRF）。
 *
 * 一处结构性改动：旧实现在每次保存/激活/测试/删除后手工
 * `invalidateHealth() → getHealth(true) → refreshShell()` 三连，
 * 目的是让顶栏那块「厂商 · 模型」重读。React 里顶栏订阅的是同一个 health store，
 * 所以只需 `invalidateHealth() + refresh(true)`，顶栏与本页同时更新，
 * 不会出现「测过了顶栏还显示未验证」。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '@/lib/api'
import { copy, fmtTime, toast } from '@/lib/ui'
import { getHealth, invalidateHealth, useHealthStore } from '@/lib/health/health'
import { logout, useAuthStore } from '@/stores/authStore'
import { Icon } from '@/components/shared/Icon'
import { PageFrame, PageShell } from '@/components/shared/PageShell'

type Dict = Record<string, any>

/* ------------------------------------------------------------ 常量表 */

const SHOW_BASE_URL = ['custom', 'ollama']

/** 审计记录用中文动作名展示；未收录的按模块归类，不暴露内部动作代码 */
const AUDIT_LABEL: Record<string, string> = {
  'auth.login': '登录',
  'auth.logout': '退出登录',
  'auth.register': '注册账号',
  'auth.demo': '创建临时账号',
  'auth.password_change': '修改密码',
  'model.provider_save': '保存模型配置',
  'model.provider_activate': '切换当前模型',
  'model.provider_test': '测试模型连接',
  'model.provider_delete': '删除模型配置',
  'model.update': '更新模型设置',
  'model.reset': '重置模型设置',
  'store.create': '添加店铺',
  'store.sync': '同步店铺',
  'store.disconnect': '断开店铺',
  'listing.generate': '生成 Listing',
  'listing.recheck': '复检 Listing',
  'listing.export': '导出 Listing',
  'listing.version_create': '保存 Listing 版本',
  'approval.request': '提交发布申请',
  'approval.decide': '审批发布申请',
  'invite.create': '生成邀请',
  'invite.accepted': '接受邀请',
  'invite.deleted': '撤销邀请',
  'task.cancel': '取消任务',
  'task.retry': '重试任务',
  'task.run': '执行任务',
  'report.export': '导出报告',
}

const AUDIT_PREFIX: Record<string, string> = {
  auth: '账号操作',
  model: '模型配置变更',
  store: '店铺操作',
  listing: 'Listing 操作',
  approval: '审批操作',
  invite: '成员邀请',
  task: '任务操作',
  report: '报告操作',
}

const TARGET_LABEL: Record<string, string> = {
  user: '成员',
  provider_config: '模型配置',
  store_connection: '店铺',
  listing: 'Listing',
  report: '报告',
  task: '任务',
  invite: '邀请',
  approval: '审批',
}

function auditLabel(action: unknown): string {
  const key = String(action || '')
  if (AUDIT_LABEL[key]) return AUDIT_LABEL[key]
  const prefix = key.split('.')[0]
  return AUDIT_PREFIX[prefix] || '操作记录'
}

function engineLabel(name?: string): string {
  if (!name) return '未配置'
  return name === 'rule' ? '规则生成' : 'AI 模型'
}

function canManage(tenant: Dict | null): boolean {
  return Boolean(tenant && (tenant.role === 'admin' || tenant.role === 'owner'))
}

interface EditingState {
  config_id?: string
  provider: string
  label: string
  base_url: string
  model: string
}

/* ---------------------------------------------------------------- 页面 */


/* ------------------------------------------------------------------ 分区导航
   设置页是 5 张卡的纵向长页，没有分区导航就得靠滚。这里加一条吸顶的
   分区条：点一下滚到对应卡片，滚到哪张就高亮哪个，同时把 ?section= 同步回
   地址（沿用页面已有的深链语义）。

   刻意**不改**卡片的 id 与内部结构：?section= 与 #section-* 是探针契约。 */
const SECTION_ITEMS = [
  { key: 'account', label: '账号' },
  { key: 'model', label: '模型与密钥' },
  { key: 'data', label: '数据源' },
  { key: 'team', label: '团队与角色' },
  { key: 'audit', label: '审计日志' },
]

function useActiveSection(
  keys: string[],
  enabled: boolean,
): { active: string; setActive: (key: string) => void } {
  const [active, setActive] = useState(keys[0] || '')
  const id = keys.join(',')

  useEffect(() => {
    if (!enabled) return
    const pick = () => {
      // 取「已经滚过判定线」的最后一个分区；判定线在顶栏 + 分区条之下
      let current = keys[0] || ''
      for (const key of keys) {
        const el = document.getElementById(`section-${key}`)
        if (el && el.getBoundingClientRect().top <= 110) current = key
      }
      /* 滚到底时页面已经没有余量把最后一个分区顶到判定线上，
         此时直接选最后一项 —— 否则点「团队与角色」会一直高亮上一项。 */
      const atBottom =
        window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 8
      if (atBottom && keys.length) current = keys[keys.length - 1]
      setActive(current)
    }
    pick()
    window.addEventListener('scroll', pick, { passive: true })
    return () => window.removeEventListener('scroll', pick)
    // keys 由调用方按权限算出来，用字符串比较避免每次渲染重绑监听
  }, [id, enabled])

  return { active, setActive }
}

function SectionNav({
  items,
  active,
  onJump,
}: {
  items: { key: string; label: string }[]
  active: string
  onJump: (key: string) => void
}) {
  return (
    <nav
      className="sticky top-14 z-10 -mx-1 mb-4 flex gap-4 overflow-x-auto border-b border-border bg-background px-1"
      aria-label="设置分区"
      id="settings-nav"
    >
      {items.map((item) => {
        const on = item.key === active
        return (
          <button
            key={item.key}
            type="button"
            data-section-nav={item.key}
            aria-current={on ? 'true' : undefined}
            onClick={() => onJump(item.key)}
            className={
              // 下划线式，与 components/ui/tabs 的语言一致：
              // 当前项用品牌蓝描边 + 前景色文字，其余静默
              'relative -mb-px shrink-0 whitespace-nowrap border-b-2 px-0.5 pb-2 pt-2 text-[13px] transition-colors ' +
              (on
                ? 'border-primary font-medium text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground')
            }
          >
            {item.label}
          </button>
        )
      })}
    </nav>
  )
}

export function SettingsPage({ section }: { section?: string }) {
  const [providers, setProviders] = useState<Dict | null>(null)
  const [tenant, setTenant] = useState<Dict | null>(null)
  const [members, setMembers] = useState<Dict[]>([])
  const [sources, setSources] = useState<Dict[]>([])
  const [auditItems, setAuditItems] = useState<Dict[]>([])
  const [ready, setReady] = useState(false)
  /* 团队 / 数据源进视野才请求；审计在打开弹窗时才请求 */
  const [membersLoaded, setMembersLoaded] = useState(false)
  const [sourcesLoaded, setSourcesLoaded] = useState(false)

  const [editing, setEditing] = useState<EditingState | null>(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  /* 表单是非受控的（ref + defaultValue），与旧实现一致：
     探针/脚本用 `el.value = x; dispatch('input')` 填表时必须生效，
     受控输入会把这类赋值吞掉（React 的 value tracker 认为没变）。 */
  const formKey = useRef(0)
  const labelRef = useRef<HTMLInputElement>(null)
  const apiKeyRef = useRef<HTMLInputElement>(null)
  const baseUrlRef = useRef<HTMLInputElement>(null)
  const modelRef = useRef<HTMLInputElement>(null)
  const allowCustomRef = useRef<HTMLInputElement>(null)
  /* 厂商下拉同时驱动 datalist 候选与「自定义地址」勾选框的可用状态 */
  const [providerKey, setProviderKey] = useState('deepseek')
  const [modelHint, setModelHint] = useState(
    '列表是常用候选；点「读取可用模型」可以拉取你这个账号真正能用的模型名。',
  )
  const [liveModels, setLiveModels] = useState<Record<string, string[]>>({})
  const [invite, setInvite] = useState<Dict | null>(null)
  const [inviteRole, setInviteRole] = useState('editor')
  const [auditOpen, setAuditOpen] = useState(false)

  const health = useHealthStore((s) => s.data)
  const user = useAuthStore((s) => s.user) ?? useAuthStore((s) => s.me)
  const username = (user as Dict | null)?.username || ''
  const isDemo = username.toLowerCase() === 'demo'
  const manage = canManage(tenant)

  /* ------------------------------------------------------------ 载入 */

  useEffect(() => {
    let alive = true
    ;(async () => {
      const [prov, ten] = await Promise.all([
        api.get<Dict>('/api/settings/providers').catch(() => ({ items: [], presets: [] })),
        api.get<Dict>('/api/tenants/current').catch(() => null),
      ])
      if (!alive) return
      setProviders(prov)
      setTenant(ten)
      setReady(true)
      // 顶栏「厂商 · 模型」与这里共用一份缓存
      void getHealth().catch(() => null)
    })()
    return () => {
      alive = false
    }
  }, [])

  /* 每个分区各自的请求，只发一次 */
  const loadedSections = useRef<Record<string, boolean>>({})
  const loadSection = useCallback(async (key: string) => {
    if (loadedSections.current[key]) return
    loadedSections.current[key] = true
    if (key === 'team') {
      const mem = await api.get<{ items?: Dict[] }>('/api/tenants/members').catch(() => ({ items: [] }))
      setMembers(mem?.items || [])
      setMembersLoaded(true)
    } else if (key === 'data') {
      const src = await api.get<{ items?: Dict[] }>('/api/marketplace/sources').catch(() => ({ items: [] }))
      setSources(src?.items || [])
      setSourcesLoaded(true)
    } else if (key === 'audit') {
      const audit = await api.get<{ items?: Dict[] }>('/api/audit?limit=20').catch(() => ({ items: [] }))
      setAuditItems(audit?.items || [])
    }
  }, [])

  /* 分区卡片滚进视野时再拉它自己的数据 */
  useEffect(() => {
    if (!ready) return
    const seen: Record<string, boolean> = {}
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return
          const key = (entry.target as HTMLElement).id.replace('section-', '')
          if (seen[key]) return
          seen[key] = true
          void loadSection(key)
        })
      },
      { rootMargin: '240px 0px' },
    )
    ;['data', 'team'].forEach((key) => {
      const el = document.getElementById(`section-${key}`)
      if (el) observer.observe(el)
    })
    return () => observer.disconnect()
  }, [ready, loadSection])

  const items: Dict[] = providers?.items || []
  const presets: Dict[] = providers?.presets || []

  /** 模型候选 = 现场读到的（优先） + 预置厂商的常用候选 */
  const modelCandidates = (providerKey: string): string[] => {
    const preset = presets.find((p) => p.key === providerKey)
    const live = liveModels[providerKey] || []
    const common = (preset && preset.common_models) || []
    const seen: Record<string, boolean> = {}
    return live.concat(common).filter((name) => {
      if (!name || seen[name]) return false
      seen[name] = true
      return true
    })
  }

  /* ------------------------------------------------------- 配置的增删改 */

  const resetFormChrome = (key: string) => {
    formKey.current += 1
    setProviderKey(key)
    setModelHint('列表是常用候选；点「读取可用模型」可以拉取你这个账号真正能用的模型名。')
    setFormError(null)
  }

  const startCreate = () => {
    const preset = presets.find((p) => p.key === 'deepseek')
    resetFormChrome('deepseek')
    setEditing({
      provider: 'deepseek',
      label: '默认',
      base_url: preset?.base_url || '',
      model: preset?.default_model || '',
    })
  }

  const startEdit = (item: Dict) => {
    resetFormChrome(item.provider)
    setEditing({
      config_id: item.config_id,
      provider: item.provider,
      label: item.label,
      base_url: item.base_url || '',
      model: item.model || '',
    })
  }

  /** 换厂商：清空并填入该厂商的预置地址与默认模型（旧实现直接写 DOM，这里同样写 DOM） */
  const changeProvider = (key: string) => {
    const preset = presets.find((p) => p.key === key)
    setProviderKey(key)
    setEditing((prev) => (prev ? { ...prev, provider: key } : prev))
    if (baseUrlRef.current) baseUrlRef.current.value = preset?.base_url || ''
    if (modelRef.current) modelRef.current.value = preset?.default_model || ''
    if (allowCustomRef.current && key !== 'custom') allowCustomRef.current.checked = false
  }

  /** 保存/激活/测试/删除之后：让顶栏与本页共用的 health 重读 */
  const refreshHealth = async () => {
    invalidateHealth()
    await useHealthStore.getState().refresh(true)
  }

  const reloadProviders = async () => {
    try {
      setProviders(await api.get<Dict>('/api/settings/providers'))
    } catch {
      /* 保持原样 */
    }
  }

  const saveProvider = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!editing) return
    setFormError(null)
    const payload: Dict = {
      provider: providerKey,
      label: (labelRef.current?.value || '默认').trim(),
      base_url: (baseUrlRef.current?.value || '').trim() || null,
      model: (modelRef.current?.value || '').trim() || null,
      api_key: (apiKeyRef.current?.value || '').trim() || null,
      allow_custom_base_url: Boolean(allowCustomRef.current?.checked),
    }
    if (editing.config_id) payload.config_id = editing.config_id
    if (!payload.api_key && !editing.config_id) delete payload.api_key

    setBusy(true)
    try {
      const saved = await api.post<{ config?: Dict }>('/api/settings/providers', payload)
      const cfg = saved?.config || {}
      toast(
        cfg.is_active
          ? '已保存并设为当前使用；可点「测试」验证连通性'
          : '配置已保存，可点「测试」验证，或「设为当前」切换',
        'ok',
      )
      setEditing(null)
      await reloadProviders()
      await refreshHealth()
    } catch (err) {
      setFormError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const activate = async (configId: string) => {
    try {
      await api.post(`/api/settings/providers/${encodeURIComponent(configId)}/activate`, {})
      toast('已切换当前使用的配置', 'ok')
      await reloadProviders()
      await refreshHealth()
    } catch (err) {
      toast((err as Error).message, 'danger')
    }
  }

  const testProvider = async (configId: string) => {
    try {
      const result = await api.post<{ ok?: boolean; elapsed_ms?: number; detail?: string }>(
        `/api/settings/providers/${encodeURIComponent(configId)}/test`,
        {},
      )
      toast(
        result.ok ? `连通正常（${result.elapsed_ms || 0} ms）` : `失败：${result.detail}`,
        result.ok ? 'ok' : 'danger',
      )
      await reloadProviders()
      try {
        await refreshHealth()
      } catch {
        /* 忽略 */
      }
    } catch (err) {
      toast((err as Error).message, 'danger')
    }
  }

  const removeProvider = async (configId: string) => {
    if (!window.confirm('删除这套配置？已保存的 Key 会一并删除，且不可恢复。')) return
    try {
      await api.del(`/api/settings/providers/${encodeURIComponent(configId)}`)
      toast('配置已删除', 'ok')
      await reloadProviders()
      await refreshHealth()
    } catch (err) {
      toast((err as Error).message, 'danger')
    }
  }

  /** 读取该账号真正可用的模型清单：模型名各家常改，问服务端比抄文档可靠 */
  const fetchModels = async () => {
    if (!editing) return
    try {
      const data = await api.post<{ items?: string[]; hint?: string }>(
        '/api/settings/providers/models',
        {
          provider: providerKey,
          base_url: (baseUrlRef.current?.value || '').trim() || null,
          api_key: (apiKeyRef.current?.value || '').trim() || null,
          allow_custom_base_url: Boolean(allowCustomRef.current?.checked),
          config_id: editing.config_id || null,
        },
      )
      const list = data?.items || []
      setLiveModels((prev) => ({ ...prev, [providerKey]: list }))
      if (list.length && modelRef.current && !modelRef.current.value) {
        modelRef.current.value = list[0]
      }
      setModelHint(
        list.length
          ? `共 ${list.length} 个可用模型，点模型输入框即可下拉选择。`
          : data?.hint || '这个接口没有返回模型清单，可以手动填写厂商文档里的模型名。',
      )
      toast(list.length ? `读到 ${list.length} 个可用模型` : '没有读到模型清单', list.length ? 'ok' : 'danger')
    } catch (err) {
      setModelHint((err as Error).message)
      toast((err as Error).message, 'danger')
    }
  }


  const createInvite = async () => {
    try {
      const data = await api.post<Dict>('/api/tenants/invites', { role: inviteRole })
      setInvite(data)
    } catch (err) {
      toast((err as Error).message, 'danger')
    }
  }

  const memberName = useMemo(() => {
    const map: Record<string, string> = {}
    members.forEach((m) => {
      map[m.user_id] = m.display_name || m.username
    })
    return map
  }, [members])

  /* 当前角色能看到的分区：审计只对管理员出现，导航条也不能列出来 */
  const sectionItems = useMemo(
    () => (manage ? SECTION_ITEMS : SECTION_ITEMS.filter((item) => item.key !== 'audit')),
    [manage],
  )
  const { active: activeSection, setActive: setActiveSection } = useActiveSection(
    sectionItems.map((item) => item.key),
    ready,
  )

  const jumpToSection = (key: string) => {
    const target = document.getElementById(`section-${key}`)
    if (!target) return
    // 先即时高亮：平滑滚动要几百毫秒，等滚完再变色会显得没反应
    setActiveSection(key)
    target.scrollIntoView({ block: 'start', behavior: 'smooth' })
    // 静默改地址：与任务抽屉同一套做法，不走路由，页面不重挂
    history.replaceState({}, '', `/settings?section=${key}`)
  }

  /* ?section=account|model|data|team|audit → 滚动到对应卡片（旧实现同样支持） */
  useEffect(() => {
    if (!ready || !section) return
    const target = document.getElementById(`section-${section}`)
    if (target) target.scrollIntoView({ block: 'start' })
  }, [ready, section])

  const providerInfo = health?.provider || {}
  const activeText = engineLabel(providerInfo.name) + (providerInfo.model ? ` · ${providerInfo.model}` : '')

  if (!ready) {
    return (
      <PageFrame>
        <PageShell title="设置" desc="账号、模型密钥、团队成员与数据来源。">
          <div className="skeleton skeleton-line" style={{ height: 180 }} />
        </PageShell>
      </PageFrame>
    )
  }

  return (
    <PageFrame>
      <PageShell title="设置" desc="账号、模型密钥、团队成员与数据来源。">
        <SectionNav items={sectionItems} active={activeSection} onJump={jumpToSection} />

        <div className="settings-grid">
          {/* ---------------- 账号 ---------------- */}
          <div className="card scroll-mt-28" id="section-account">
            <div className="card-head">
              <div>
                <div className="card-title">账号</div>
                <div className="card-sub">当前登录身份</div>
              </div>
            </div>
            <div className="card-body">
              <div className="kv">
                <span className="kv-k">用户名</span>
                <span className="kv-v">{(user as Dict)?.username || '—'}</span>
              </div>
              <div className="kv">
                <span className="kv-k">显示名</span>
                <span className="kv-v">{(user as Dict)?.display_name || '—'}</span>
              </div>
              <div className="kv">
                <span className="kv-k">管理员</span>
                <span className="kv-v">{(user as Dict)?.is_admin ? '是' : '否'}</span>
              </div>
              <div className="kv">
                <span className="kv-k">账号类型</span>
                <span className="kv-v">
                  {isDemo ? (
                    <span className="badge badge-warn">共享体验账号</span>
                  ) : (user as Dict)?.is_guest ? (
                    <span className="badge badge-warn">
                      临时账号（{fmtTime((user as Dict)?.guest_expires_at)} 过期）
                    </span>
                  ) : (
                    <span className="badge">普通账号</span>
                  )}
                </span>
              </div>
              <div className="row gap-2 mt-4">
                <button type="button" className="btn btn-sm" id="btn-logout" onClick={() => void logout()}>
                  退出登录
                </button>
              </div>
            </div>
          </div>

          {/* ---------------- 模型与密钥 ---------------- */}
          <div className="card scroll-mt-28" id="section-model">
            <div className="card-head">
              <div>
                <div className="card-title">模型与密钥</div>
                <div className="card-sub">平台不提供模型额度：每个账号使用自己的 API Key</div>
              </div>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                id="prov-new"
                disabled={isDemo}
                onClick={startCreate}
              >
                <Icon name="plus" />
                新增配置
              </button>
            </div>
            <div className="card-body">
              {isDemo ? (
                <div className="callout callout-warn">
                  <Icon name="alert" />
                  <div>
                    <strong>共享体验账号不能保存 API Key</strong>：它由所有人共用。
                    请使用「一键体验」创建自己的临时账号后再配置。
                  </div>
                </div>
              ) : null}

              <div className="row between wrap gap-2 mb-2">
                <span className="t-sm t-bold">已保存的配置</span>
                <span className="t-xs t-muted">当前生效：{activeText}</span>
              </div>

              {items.length === 0 ? (
                <div className="empty" style={{ padding: 'var(--sp-5)' }}>
                  <span className="empty-icon">
                    <Icon name="settings" />
                  </span>
                  <p className="empty-title">还没有配置</p>
                  <p className="empty-desc">
                    激浪不提供模型额度。添加一个你自己的模型配置并设为当前使用后，才能运行生成类任务。
                  </p>
                  <div className="empty-actions">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      id="prov-empty-new"
                      disabled={isDemo}
                      onClick={startCreate}
                    >
                      添加模型配置
                    </button>
                  </div>
                </div>
              ) : (
                items.map((c) => (
                  <div className="cfg-row" key={c.config_id}>
                    <div className="cfg-main">
                      <div className="cfg-title">
                        {c.label}
                        <span className="badge">{c.provider}</span>
                        {c.is_active ? <span className="badge badge-brand">当前使用</span> : null}
                        {!c.enabled ? <span className="badge">已禁用</span> : null}
                        {c.last_test_ok === true ? (
                          <span className="badge badge-ok">测试通过</span>
                        ) : c.last_test_ok === false ? (
                          <span className="badge badge-danger">测试失败</span>
                        ) : null}
                      </div>
                      <div className="cfg-sub">
                        {c.model || '—'}
                        {SHOW_BASE_URL.indexOf(c.provider) >= 0 ? ` · ${c.base_url || '—'}` : ''}
                        <br />
                        Key：{c.has_api_key ? c.api_key_masked || '已保存' : '未保存'}
                        {c.last_tested_at ? ` · 最近测试 ${fmtTime(c.last_tested_at)}` : ''}
                        {c.last_test_ok === false && c.last_test_detail ? (
                          <>
                            <br />
                            <span className="t-danger">{c.last_test_detail}</span>
                          </>
                        ) : null}
                      </div>
                    </div>
                    <div className="cfg-actions">
                      <button type="button" className="btn btn-sm" data-test={c.config_id} onClick={() => testProvider(c.config_id)}>
                        测试
                      </button>
                      {c.is_active ? (
                        <button type="button" className="btn btn-sm" disabled>
                          已激活
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-sm btn-primary"
                          data-activate={c.config_id}
                          onClick={() => activate(c.config_id)}
                        >
                          设为当前
                        </button>
                      )}
                      <button type="button" className="btn btn-sm btn-quiet" data-edit={c.config_id} onClick={() => startEdit(c)}>
                        编辑
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        data-delete={c.config_id}
                        onClick={() => removeProvider(c.config_id)}
                      >
                        删除
                      </button>
                    </div>
                  </div>
                ))
              )}

              {editing ? (
                <form
                  id="prov-form"
                  className="card card-pad"
                  style={{ marginTop: 'var(--sp-4)' }}
                  key={formKey.current}
                  onSubmit={saveProvider}
                >
                  <div className="row between">
                    <div>
                      <div className="card-title">{editing.config_id ? '编辑配置' : '新增配置'}</div>
                      <div className="card-sub">
                        不同厂商用接口地址与模型名区分；Anthropic、Google 走各自官方协议，已自动适配
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn-icon"
                      id="prov-cancel"
                      aria-label="取消"
                      onClick={() => setEditing(null)}
                    >
                      <Icon name="close" />
                    </button>
                  </div>

                  <div className="grid-2 mt-4">
                    <label className="field">
                      <span className="field-label">
                        厂商 <span className="t-danger">*</span>
                      </span>
                      <select
                        name="provider"
                        id="prov-provider"
                        defaultValue={editing.provider}
                        onChange={(e) => changeProvider(e.target.value)}
                      >
                        {presets.map((p) => (
                          <option value={p.key} key={p.key}>
                            {p.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      <span className="field-label">配置标签</span>
                      <input
                        name="label"
                        ref={labelRef}
                        defaultValue={editing.label}
                        placeholder="例如 主 Key / 备用"
                      />
                    </label>
                  </div>

                  <label className="field mt-3">
                    <span className="field-label">
                      API Key {editing.config_id ? '' : <span className="t-danger">*</span>}
                    </span>
                    <input
                      name="api_key"
                      ref={apiKeyRef}
                      type="password"
                      autoComplete="off"
                      defaultValue=""
                      placeholder={editing.config_id ? '留空表示不修改' : 'sk-...'}
                    />
                    <span className="field-help">
                      加密保存；保存后只显示末四位。生成时只用于调用模型，不会出现在结果里。
                    </span>
                  </label>

                  <label className="field mt-3">
                    <span className="field-label">接口地址</span>
                    <input
                      name="base_url"
                      ref={baseUrlRef}
                      defaultValue={editing.base_url}
                      placeholder="留空使用厂商默认地址"
                    />
                    <span className="field-help" id="prov-url-hint">
                      预置厂商只允许其官方域名；其他地址需选择「自定义」并勾选下方确认。
                    </span>
                  </label>

                  <label className="row gap-2 mt-3" style={{ cursor: 'pointer' }} id="prov-custom-row">
                    <input
                      type="checkbox"
                      name="allow_custom"
                      ref={allowCustomRef}
                      disabled={providerKey !== 'custom'}
                      defaultChecked={false}
                    />
                    <span className="t-sm">
                      我确认使用自定义接口地址（仅限 OpenAI 兼容服务，不能指向内网）
                    </span>
                  </label>

                  <div className="field mt-3">
                    <span className="field-label">
                      模型 <span className="t-danger">*</span>
                    </span>
                    <div className="row gap-2">
                      <input
                        name="model"
                        ref={modelRef}
                        className="grow"
                        list="prov-model-options"
                        autoComplete="off"
                        defaultValue={editing.model}
                        placeholder="从列表里选，或直接填写模型名"
                      />
                      <button type="button" className="btn btn-sm" id="prov-fetch-models" onClick={fetchModels}>
                        读取可用模型
                      </button>
                    </div>
                    <datalist id="prov-model-options">
                      {modelCandidates(providerKey).map((name) => (
                        <option value={name} key={name} />
                      ))}
                    </datalist>
                    <span className="field-help" id="prov-model-hint">
                      {modelHint}
                    </span>
                  </div>

                  <p className="callout callout-danger mt-3" id="prov-error" hidden={!formError}>
                    {formError}
                  </p>
                  <div className="row gap-2 mt-4">
                    <button type="submit" className="btn btn-primary" disabled={busy}>
                      {busy ? '保存中…' : '保存配置'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-quiet"
                      id="prov-cancel-2"
                      onClick={() => setEditing(null)}
                    >
                      取消
                    </button>
                  </div>
                </form>
              ) : null}


              <div className="callout callout-info mt-4">
                <Icon name="info" />
                <span>
                  支持 OpenAI 兼容接口：DeepSeek、OpenAI、Moonshot、智谱、通义、硅基流动、OpenRouter、Ollama，也可以填自定义地址；另有
                  Anthropic Claude 与 Google Gemini。
                </span>
              </div>
            </div>
          </div>

          {/* ---------------- 数据源 ---------------- */}
          <div className="card scroll-mt-28" id="section-data">
            <div className="card-head">
              <div>
                <div className="card-title">数据源</div>
                <div className="card-sub">每个数据域现在用的是哪一份数据、上次什么时候同步</div>
              </div>
            </div>
            <div className="card-body">
              {!sourcesLoaded ? (
                <p className="t-sm t-muted">正在载入数据来源…</p>
              ) : sources.length === 0 ? (
                <p className="t-sm t-muted">暂时读不到数据来源信息。</p>
              ) : (
                sources.map((s, i) => {
                  let badge: React.ReactNode
                  if (s.mode === 'upload') badge = <span className="badge">你的文件</span>
                  else if (s.configured && s.mode === 'live')
                    badge = <span className="badge badge-ok">已连接</span>
                  else if (s.configured) badge = <span className="badge">示例数据</span>
                  else badge = <span className="badge">未设置</span>
                  return (
                    <div className="src-row" key={i}>
                      <span className="grow">
                        <span className="src-name">{s.label}</span>
                        <span className="src-desc">
                          {s.detail}
                          {s.last_sync_at ? ` · 最后同步 ${fmtTime(s.last_sync_at)}` : ''}
                        </span>
                      </span>
                      <span className="src-flags">{badge}</span>
                    </div>
                  )
                })
              )}
              <div className="row gap-2 mt-4">
                <a className="btn btn-sm" href="/stores" data-link="">
                  管理店铺与渠道
                </a>
              </div>
            </div>
          </div>

          {/* ---------------- 团队 ---------------- */}
          <div className="card scroll-mt-28" id="section-team">
            <div className="card-head">
              <div>
                <div className="card-title">团队与角色</div>
                <div className="card-sub">
                  {tenant ? `${tenant.name} · 我的角色 ${tenant.role}` : '租户信息不可用'}
                </div>
              </div>
            </div>
            <div className="card-body">
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>成员</th>
                      <th>角色</th>
                      <th>加入时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!membersLoaded ? (
                      <tr>
                        <td colSpan={3} className="t-muted">
                          正在载入成员…
                        </td>
                      </tr>
                    ) : members.length ? (
                      members.map((m, i) => (
                        <tr key={i}>
                          <td>{m.display_name || m.username}</td>
                          <td>{m.role}</td>
                          <td className="t-muted">{fmtTime(m.joined_at)}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={3} className="t-muted">
                          暂无成员
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {manage ? (
                <>
                  <div className="row gap-2 mt-4 wrap">
                    <select
                      id="invite-role"
                      style={{ maxWidth: 200 }}
                      value={inviteRole}
                      onChange={(e) => setInviteRole(e.target.value)}
                    >
                      <option value="editor">editor（可执行任务）</option>
                      <option value="viewer">viewer（只读）</option>
                      <option value="admin">admin（可管理成员）</option>
                    </select>
                    <button type="button" className="btn btn-sm" id="btn-invite" onClick={createInvite}>
                      生成邀请令牌
                    </button>
                  </div>
                  <div className="callout callout-info mt-3">
                    <Icon name="info" />
                    <span>邀请链接只显示一次，复制后发给同事即可。</span>
                  </div>
                  <div id="invite-result" className="mt-3">
                    {invite ? (
                      <div className="callout callout-info">
                        <Icon name="info" />
                        <div>
                          <strong>邀请令牌（只显示一次）</strong>
                          <div className="t-mono mt-2" style={{ wordBreak: 'break-all' }}>
                            {invite.token}
                          </div>
                          <div className="t-xs t-muted mt-2">
                            角色：{invite.invite?.role} · 过期：{fmtTime(invite.invite?.expires_at)}
                          </div>
                          <button
                            type="button"
                            className="btn btn-sm mt-2"
                            id="invite-copy"
                            onClick={() => void copy(invite.token, '邀请令牌')}
                          >
                            复制令牌
                          </button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                </>
              ) : (
                <div className="callout callout-info mt-3">
                  <Icon name="info" />
                  <span>只有 admin / owner 可以邀请成员与查看审计日志。</span>
                </div>
              )}
            </div>
          </div>

          {/* ---------------- 审计 ---------------- */}
          {manage ? (
            <div className="card card-pad scroll-mt-28" id="section-audit">
              <div className="row between gap-2">
                <div>
                  <div className="card-title">审计日志</div>
                  <div className="card-sub">记录谁在什么时候改了什么，写入后不可修改</div>
                </div>
                <button
                  type="button"
                  className="btn btn-sm"
                  id="btn-audit"
                  onClick={() => {
                    setAuditOpen(true)
                    void loadSection('audit')
                    void loadSection('team')
                  }}
                >
                  查看
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </PageShell>

      {auditOpen
        ? createPortal(
            <AuditModal
              items={auditItems}
              memberName={memberName}
              onClose={() => setAuditOpen(false)}
            />,
            document.body,
          )
        : null}
    </PageFrame>
  )
}

/**
 * 审计日志弹窗。表格一共 20 行四列，摊在设置页上会占半个页面，日常又不需要常看，
 * 所以默认收起，点「查看」再浮上来。
 */
function AuditModal({
  items,
  memberName,
  onClose,
}: {
  items: Dict[]
  memberName: Record<string, string>
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="modal"
      id="audit-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="audit-modal-title"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="modal-card is-wide">
        <div className="modal-head">
          <div>
            <div className="card-title" id="audit-modal-title">
              审计日志
            </div>
            <div className="card-sub">最近 20 条；记录写入后不可修改</div>
          </div>
          <button type="button" className="btn-icon" data-audit-close="" aria-label="关闭" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>
        <div className="modal-body">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>动作</th>
                  <th>操作者</th>
                  <th>对象</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {items.length ? (
                  items.map((item, i) => (
                    <tr key={i}>
                      <td>{auditLabel(item.action)}</td>
                      <td className="t-xs">{memberName[item.actor_id] || '—'}</td>
                      <td className="t-xs t-muted">{TARGET_LABEL[item.target_type] || '—'}</td>
                      <td className="t-muted t-xs">{fmtTime(item.created_at)}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={4} className="t-muted">
                      暂无记录
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-quiet" data-audit-close="" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}
