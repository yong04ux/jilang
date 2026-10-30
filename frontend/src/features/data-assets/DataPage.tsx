/**
 * 数据资产：文件导入、字段映射与数据集列表。
 *
 * 三步导入走真实接口，不是前端假流程：
 *   POST /api/import/preview → 存文件 + 识别列 + 逐行校验（不写业务数据）
 *   POST /api/import/remap   → 按新映射重新校验
 *   POST /api/import/commit  → 按映射写入批次（不可重复提交）
 *
 * 一条纪律：错误永远定位到「行 + 字段」，并且可以导出 CSV 让用户逐条改。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { fmtTime, toast } from '@/lib/ui'
import { Icon } from '@/components/shared/Icon'
import { PageFrame } from '@/components/shared/PageShell'

type Dict = Record<string, any>

/* 可映射的目标字段（与后端 COLUMN_ALIASES 一致） */
const TARGET_FIELDS: Array<{ key: string; label: string }> = [
  { key: '', label: '（忽略此列）' },
  { key: 'name', label: '商品名称' },
  { key: 'brand', label: '品牌' },
  { key: 'asin', label: 'ASIN' },
  { key: 'category', label: '商品类目' },
  { key: 'price', label: '价格' },
  { key: 'currency', label: '币种' },
  { key: 'rating', label: '商品评分' },
  { key: 'review_count', label: '评论总数' },
  { key: 'key_features', label: '商品卖点' },
  { key: 'specifications', label: '商品规格' },
  { key: 'review_text', label: '评论内容' },
  { key: 'review_rating', label: '评论星级' },
  { key: 'review_title', label: '评论标题' },
  { key: 'review_date', label: '评论日期' },
  { key: 'is_demo', label: '是否为示例数据' },
  { key: 'keyword', label: '关键词' },
  { key: 'search_volume', label: '搜索量' },
  { key: 'rank', label: '排名' },
]

function columnName(col: Dict): string {
  return col.source || col.name || col.header || ''
}

export function DataPage() {
  const [fileName, setFileName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<Dict | null>(null)
  /** 用户改过的映射（列名 → 目标字段）；没改过的用接口识别结果 */
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [errorText, setErrorText] = useState('')
  const [previewed, setPreviewed] = useState(false)
  const [busy, setBusy] = useState<'remap' | 'commit' | null>(null)
  const [sources, setSources] = useState<Dict[]>([])
  const [sourcesLoaded, setSourcesLoaded] = useState(false)
  const [sourcesFailed, setSourcesFailed] = useState(false)

  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let alive = true
    api
      .get<{ items?: Dict[] }>('/api/data-sources?limit=10')
      .then((data) => {
        if (!alive) return
        setSources(data.items || [])
        setSourcesFailed(false)
      })
      .catch(() => {
        if (alive) setSourcesFailed(true)
      })
      .finally(() => {
        if (alive) setSourcesLoaded(true)
      })
    return () => {
      alive = false
    }
  }, [])

  const columns: Dict[] = result?.columns || []
  const errors: Dict[] = result?.errors || []

  /** 收集完整映射：用户改过的优先，其余用接口识别值；空值表示忽略 */
  const collectMapping = (): Record<string, string> => {
    const out: Record<string, string> = {}
    columns.forEach((col) => {
      const name = columnName(col)
      const target = overrides[name] !== undefined ? overrides[name] : col.field || ''
      if (target) out[name] = target
    })
    return out
  }

  const onUpload = async () => {
    if (!file) return
    setErrorText('')
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    try {
      const data = await api.postForm<Dict>('/api/import/preview', form)
      setResult(data)
      setOverrides({})
      const errs = (data.errors || []).length
      toast(
        data.status === 'needs_mapping'
          ? '需要先确认字段映射'
          : errs
            ? `校验完成，有 ${errs} 行错误`
            : '校验通过，可以提交',
        errs || data.status === 'needs_mapping' ? 'danger' : 'ok',
      )
    } catch (err) {
      const detail = (err as Dict)?.detail
      setErrorText((err as Error).message)
      if (detail && detail.errors) {
        setResult({
          filename: file.name,
          total_rows: 0,
          valid_rows: 0,
          preview: [],
          columns: [],
          errors: detail.errors,
          status: 'rejected',
        })
      }
    } finally {
      setUploading(false)
      setPreviewed(true)
    }
  }

  const repreview = async () => {
    if (!result || !result.data_source_id) {
      toast('请先上传文件', 'danger')
      return
    }
    const mapping = collectMapping()
    if (!Object.keys(mapping).length) {
      toast('至少映射一列（通常是 name）', 'danger')
      return
    }
    setBusy('remap')
    try {
      const next = await api.post<Dict>('/api/import/remap', {
        data_source_id: result.data_source_id,
        field_mapping: mapping,
      })
      setResult(next)
      const errs = (next.errors || []).length
      toast(
        next.status === 'validated'
          ? '映射已生效，可以提交'
          : errs
            ? `仍有 ${errs} 行错误`
            : '映射不完整，请补全必填列',
        next.status === 'validated' ? 'ok' : 'danger',
      )
    } catch (err) {
      toast((err as Error).message, 'danger')
    } finally {
      setBusy(null)
    }
  }

  const commit = async () => {
    if (!result || !result.data_source_id) return
    const mapping = collectMapping()
    if (!Object.keys(mapping).length) {
      toast('请先完成字段映射（至少 name）', 'danger')
      return
    }
    setBusy('commit')
    try {
      const committed = await api.post<Dict>('/api/import/commit', {
        data_source_id: result.data_source_id,
        field_mapping: mapping,
      })
      const next: Dict = {
        ...result,
        status: 'imported',
        valid_rows: committed.valid_rows || committed.total_rows || 0,
        total_rows: committed.total_rows || result.total_rows,
        task_id: committed.task_id,
      }
      setResult(next)
      toast(`导入完成：${next.valid_rows} 个竞品已写入批次`, 'ok')
    } catch (err) {
      const detail = (err as Dict)?.detail
      const detailErrors = detail && detail.errors
      if (detailErrors) {
        setResult({ ...result, status: 'rejected', errors: detailErrors })
      }
      toast((err as Error).message, 'danger')
    } finally {
      setBusy(null)
    }
  }

  const exportErrors = () => {
    if (!errors.length) return
    const quote = (v: unknown) => {
      const s = v === null || v === undefined ? '' : String(v)
      return '"' + s.replace(/"/g, '""') + '"'
    }
    const header = 'row,field,message,value\n'
    const body = errors
      .map((e) => [e.row, quote(e.field), quote(e.message), quote(e.value)].join(','))
      .join('\n')
    const blob = new Blob(['\uFEFF' + header + body], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'import-errors.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  const statusBadgeText = useMemo(() => {
    if (!result) return null
    return result.status === 'validated' ? (
      <span className="badge badge-ok">校验通过</span>
    ) : result.status === 'imported' ? (
      <span className="badge badge-ok">已提交</span>
    ) : result.status === 'needs_mapping' ? (
      <span className="badge badge-warn">需要字段映射</span>
    ) : result.status === 'rejected' ? (
      <span className="badge badge-danger">有错误</span>
    ) : (
      <span className="badge">{result.status || ''}</span>
    )
  }, [result])

  const statValid = !result
    ? '待导入'
    : result.status === 'validated'
      ? '校验通过'
      : errors.length
        ? '需检查'
        : '待映射'

  const latest = sources[0]

  /* ------------------------------------------------------------ 结果卡 */

  const renderResultCard = () => {
    if (!result) {
      return (
        <div className="card">
          <div className="empty">
            <span className="empty-icon">
              <Icon name="table" />
            </span>
            <p className="empty-title">还没有导入结果</p>
            <p className="empty-desc">上传文件后，这里会先显示识别到的列与预览，再由你确认字段映射。</p>
          </div>
        </div>
      )
    }
    if (uploading) {
      return (
        <div className="card">
          <div className="empty">
            <span className="empty-icon">
              <Icon name="upload" />
            </span>
            <p className="empty-title">正在上传并校验</p>
            <p className="empty-desc">大文件可能需要几秒钟。</p>
          </div>
        </div>
      )
    }

    return (
      <div className="card">
        <div className="card-head">
          <div>
            <div className="card-title">校验结果</div>
            <div className="card-sub">
              {result.filename || result.source_name || ''} ·{' '}
              {result.format || result.source_format || ''} · 共 {result.total_rows || 0} 行
            </div>
          </div>
          {statusBadgeText}
        </div>
        <div className="card-body">
          <div className="metric-grid">
            <div className="metric-cell">
              <div className="metric-label">有效竞品</div>
              <div className="metric-value">{result.valid_rows || 0}</div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">错误行</div>
              <div className="metric-value">{errors.length}</div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">总行数</div>
              <div className="metric-value">{result.total_rows || 0}</div>
            </div>
            <div className="metric-cell">
              <div className="metric-label">识别字段</div>
              <div className="metric-value">{columns.length}</div>
            </div>
          </div>

          {(result.preview || []).length ? (
            <>
              <div className="t-section mt-4">数据预览</div>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>名称</th>
                      <th className="num">价格</th>
                      <th className="num">评论样本</th>
                      <th>来源</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(result.preview || []).map((c: Dict, i: number) => (
                      <tr key={i}>
                        <td>{c.name}</td>
                        <td className="num">
                          {c.price === null || c.price === undefined
                            ? '—'
                            : Number(c.price).toFixed(2)}
                        </td>
                        <td className="num">{(c.reviews || []).length}</td>
                        <td>
                          {c.is_demo ? (
                            <span className="badge badge-warn">示例数据</span>
                          ) : (
                            <span className="badge badge-ok">已导入</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}

          {errors.length ? (
            <>
              <div className="t-section mt-4">
                逐行错误
                {errors.length > 50 ? `（显示前 50 条，共 ${errors.length} 条）` : ''}
              </div>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th className="num">行</th>
                      <th>字段</th>
                      <th>原因</th>
                      <th>原值</th>
                    </tr>
                  </thead>
                  <tbody>
                    {errors.slice(0, 50).map((e, i) => (
                      <tr key={i}>
                        <td className="num">{e.row}</td>
                        <td>{e.field || ''}</td>
                        <td>{e.message || ''}</td>
                        <td className="t-muted">
                          {e.value === null || e.value === undefined ? '' : String(e.value)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button type="button" className="btn btn-sm mt-2" id="data-export-errors" onClick={exportErrors}>
                <Icon name="download" />
                下载错误 CSV
              </button>
            </>
          ) : null}

          {(result.warnings || []).length ? (
            <div className="callout callout-warn mt-3">
              <Icon name="alert" />
              <div>
                {(result.warnings || []).map((w: string, i: number) => (
                  <span key={i}>
                    {w}
                    {i < (result.warnings || []).length - 1 ? <br /> : null}
                  </span>
                ))}
              </div>
            </div>
          ) : null}

          {result.status === 'imported' && (result.valid_rows || 0) > 0 ? (
            <div className="row gap-2 mt-4">
              <a className="btn btn-primary btn-sm" href="/workbench" data-link="">
                <Icon name="chat" />
                在 AI 助手里用这批数据
              </a>
            </div>
          ) : null}
        </div>
      </div>
    )
  }

  const renderMappingCard = () => {
    if (!columns.length) return null
    return (
      <div className="card mt-4">
        <div className="card-head">
          <div>
            <div className="card-title">字段映射</div>
            <div className="card-sub">识别错的列可以手动改；选「忽略」的列不会进入数据</div>
          </div>
        </div>
        <div className="card-body">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>文件列</th>
                  <th>识别结果</th>
                  <th>映射到</th>
                </tr>
              </thead>
              <tbody>
                {columns.map((col, i) => {
                  const name = columnName(col)
                  const detected = col.field || ''
                  const current = overrides[name] !== undefined ? overrides[name] : detected
                  return (
                    <tr key={`${name}-${i}`}>
                      <td>
                        <span className="source-column-name">{name}</span>
                      </td>
                      <td>
                        {detected ? (
                          <span className="badge badge-ok">已识别</span>
                        ) : (
                          <span className="badge badge-warn">需映射</span>
                        )}
                      </td>
                      <td>
                        <select
                          data-map-col={name}
                          style={{ maxWidth: 260 }}
                          value={current}
                          onChange={(e) =>
                            setOverrides((prev) => ({ ...prev, [name]: e.target.value }))
                          }
                        >
                          {TARGET_FIELDS.map((f) => (
                            <option value={f.key} key={f.key}>
                              {f.label}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="row gap-2 mt-4">
            <button
              type="button"
              className="btn btn-primary"
              id="data-commit"
              disabled={!result?.can_commit || busy !== null}
              onClick={commit}
            >
              {busy === 'commit' ? '提交中…' : '提交导入'}
            </button>
            <button
              type="button"
              className="btn"
              id="data-repreview"
              disabled={busy !== null}
              onClick={repreview}
            >
              {busy === 'remap' ? '校验中…' : '用新映射重新校验'}
            </button>
          </div>
          {!result?.can_commit ? (
            <p className="t-xs t-warn mt-2">当前有行级错误或未识别列，修正后才能提交。</p>
          ) : null}
        </div>
      </div>
    )
  }

  /* ------------------------------------------------------------ 数据集列表 */

  const renderSources = () => {
    if (!sourcesLoaded) {
      return (
        <div className="data-source-empty">
          <span className="data-mini-icon">
            <Icon name="database" />
          </span>
          <div>
            <div className="card-title">数据集列表</div>
            <p className="card-sub">读取中…</p>
          </div>
        </div>
      )
    }
    if (sourcesFailed) {
      return (
        <div className="data-source-empty">
          <span className="data-mini-icon">
            <Icon name="database" />
          </span>
          <div>
            <div className="card-title">暂时无法读取数据集</div>
            <p className="card-sub">请稍后刷新，或先导入一个文件。</p>
          </div>
        </div>
      )
    }
    if (!sources.length) {
      return (
        <div className="data-source-empty">
          <span className="data-mini-icon">
            <Icon name="database" />
          </span>
          <div>
            <div className="card-title">数据集列表</div>
            <p className="card-sub">导入并保存文件后，数据集会显示在这里。</p>
          </div>
          <span className="badge">暂无数据集</span>
        </div>
      )
    }
    return (
      <div className="data-source-table-wrap">
        <table className="table data-source-table">
          <thead>
            <tr>
              <th>数据集名称</th>
              <th>记录数量</th>
              <th>更新时间</th>
              <th>数据来源</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s, i) => (
              <tr key={i}>
                <td>
                  <div className="data-dataset-name">
                    <span className="data-file-icon">
                      <Icon name="file" />
                    </span>
                    <span>
                      <strong>{s.name || '未命名数据集'}</strong>
                      <small>{String(s.format || '文件').toUpperCase()}</small>
                    </span>
                  </div>
                </td>
                <td className="num">{s.row_count || 0} 条</td>
                <td>{fmtTime(s.created_at)}</td>
                <td>文件导入</td>
                <td>
                  {s.status === 'imported' ? (
                    <span className="badge badge-ok">已导入</span>
                  ) : s.status === 'needs_mapping' ? (
                    <span className="badge badge-warn">待映射</span>
                  ) : s.status === 'rejected' ? (
                    <span className="badge badge-danger">需检查</span>
                  ) : (
                    <span className="badge">{s.status || '处理中'}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <PageFrame>
      <div className="page data-page">
        <div className="page-inner">
          <section className="data-hero">
            <div className="data-hero-copy">
              <div className="data-eyebrow">CROSS-BORDER COMMERCE · DATA HUB</div>
              <div className="data-title-row">
                <h1 className="page-title">数据资产</h1>
                <span className="badge badge-brand">
                  <Icon name="sparkles" />
                  示例数据
                </span>
              </div>
              <p className="page-desc">管理商品数据、校验导入文件，并维护统一的数据字段。</p>
            </div>
            <div className="data-hero-note">
              <span className="data-hero-mark">
                <Icon name="database" />
              </span>
              <div>
                <strong>让数据成为运营决策的起点</strong>
                <p>当前可通过文件导入体验数据校验与字段映射，真实平台数据将在完成连接后呈现。</p>
              </div>
            </div>
          </section>

          <section className="data-overview" aria-label="数据概览">
            <div className="data-stat-card">
              <span className="data-stat-icon">
                <Icon name="data" />
              </span>
              <div>
                <span className="data-stat-label">已保存数据集</span>
                <strong id="data-stat-sources">{sourcesLoaded ? String(sources.length) : '—'}</strong>
                <small>个数据集</small>
              </div>
            </div>
            <div className="data-stat-card">
              <span className="data-stat-icon">
                <Icon name="check" />
              </span>
              <div>
                <span className="data-stat-label">最近校验</span>
                <strong id="data-stat-valid">{statValid}</strong>
                <small>导入文件后自动更新</small>
              </div>
            </div>
            <div className="data-stat-card">
              <span className="data-stat-icon">
                <Icon name="clock" />
              </span>
              <div>
                <span className="data-stat-label">最近导入</span>
                <strong id="data-stat-latest">
                  {latest ? fmtTime(latest.created_at) || '已记录' : '—'}
                </strong>
                <small id="data-stat-latest-note">
                  {latest ? latest.name || '最近导入的数据集' : '等待文件导入'}
                </small>
              </div>
            </div>
            <div className="data-stat-card">
              <span className="data-stat-icon">
                <Icon name="layers" />
              </span>
              <div>
                <span className="data-stat-label">数据来源</span>
                <strong>文件导入</strong>
                <small>CSV · JSON · Excel</small>
              </div>
            </div>
          </section>

          <section className="data-main-grid">
            <div>
              <div className="card card-pad data-upload-panel">
                <div className="row between">
                  <div>
                    <div className="card-title">导入商品数据</div>
                    <div className="card-sub">CSV / JSON / Excel，先预览再提交</div>
                  </div>
                  <span className="t-xs t-muted">≤ 5 MB</span>
                </div>
                <label className="file-drop mt-4" id="data-drop">
                  <input
                    type="file"
                    id="data-file"
                    accept=".csv,.json,.xlsx"
                    ref={fileRef}
                    onChange={(e) => {
                      const picked = e.target.files && e.target.files[0]
                      setFile(picked || null)
                      setFileName(picked ? picked.name : '')
                    }}
                  />
                  <Icon name="upload" />
                  <span className="file-drop-title">点击选择文件</span>
                  <span className="file-drop-hint">支持 .csv / .json / .xlsx，单文件不超过 5 MB</span>
                  <span className="t-xs t-muted" id="data-filename">
                    {fileName || '尚未选择文件'}
                  </span>
                </label>
                <p className="callout callout-danger mt-3" id="data-error" hidden={!errorText}>
                  {errorText}
                </p>
                <div className="row gap-2 mt-3">
                  <button
                    type="button"
                    className="btn btn-primary"
                    id="data-upload"
                    disabled={!file || uploading}
                    onClick={onUpload}
                  >
                    <Icon name="upload" />
                    {previewed ? '预览并校验' : '开始导入'}
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    id="data-demo"
                    onClick={() => toast('示例文件：examples/competitors_sample.csv（可直接选择该文件）', 'ok')}
                  >
                    <Icon name="download" />
                    示例文件
                  </button>
                </div>
                <p className="form-note t-xs t-muted mt-2">
                  支持 CSV、JSON、Excel。导入前可预览并确认字段映射。
                </p>
              </div>
            </div>

            <div className="card data-result-panel" id="data-result">
              {renderResultCard()}
              {renderMappingCard()}
            </div>
          </section>

          <section className="card data-source-panel">
            <div className="card-head">
              <div>
                <div className="card-title">数据集列表</div>
                <div className="card-sub">查看已保存的数据集与最近更新时间</div>
              </div>
              <span className="badge" id="data-source-count">
                {sources.length} 个数据集
              </span>
            </div>
            <div id="data-sources-content">{renderSources()}</div>
          </section>
        </div>
      </div>
    </PageFrame>
  )
}
