import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowDown, ArrowUp, ChevronDown, Eye, LoaderCircle, Send, Upload, X } from 'lucide-react'
import { api, post, type Plan, type PrintFile } from '../api'
import { randomUUID } from '../uuid'
import { listenForFileDrops } from '../fileDrop'
import { ErrorNotification, PageHeader, Preview, useApp } from '../ui'

interface Draft {
  uid: string; file?: PrintFile; filename: string; uploading?: boolean; error?: string;
  mode: string; expression: string; copies: number; orientation: string; scaling: string;
  plan?: Plan; planSignature?: string; planPending?: boolean; parent_task_id?: string;
}
type Options = { max_copies: number; max_batch_files: number; max_file_mib: number }
const signature = (d: Draft) => JSON.stringify([d.file?.id, d.mode, d.expression, d.orientation, d.scaling])
const isPrepared = (d: Draft) => d.file?.status === 'ready' && d.plan?.status === 'ready' && d.planSignature === signature(d)
const isPending = (d: Draft) => !!(d.uploading || d.file?.status === 'processing' || d.planPending || d.plan?.status === 'processing')

function restoreDrafts(key: string): Draft[] {
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(key) ?? '[]')
    if (!Array.isArray(saved)) return []
    return saved.filter(d => d && typeof d.uid === 'string' && typeof d.filename === 'string'
      && d.file && typeof d.file.id === 'string' && ['all', 'odd', 'even', 'custom'].includes(d.mode)
      && typeof d.expression === 'string' && Number.isInteger(d.copies) && d.copies > 0
      && ['portrait', 'landscape'].includes(d.orientation) && ['actual', 'fit', '75%', '50%', '25%'].includes(d.scaling))
      .map(d => ({ uid: d.uid, filename: d.filename, file: { ...d.file, status: 'processing' },
        mode: d.mode, expression: d.expression, copies: d.copies, orientation: d.orientation,
        scaling: d.scaling, parent_task_id: typeof d.parent_task_id === 'string' ? d.parent_task_id : undefined }))
  } catch { return [] }
}

function pageCount(d: Draft) {
  const count = d.file?.page_count ?? 0
  if (!count) return 0
  if (d.mode === 'all') return count
  if (d.mode === 'odd') return Math.ceil(count / 2)
  if (d.mode === 'even') return Math.floor(count / 2)
  let selected = 0
  for (const part of d.expression.trim().split(/[,，\s]+/)) {
    if (!/^\d+(?:-\d+)?$/.test(part)) return 0
    const bounds = part.split('-').map(Number), start = bounds[0], end = bounds.at(-1)!
    if (start < 1 || end > count || end < start) return 0
    selected += end - start + 1
  }
  return selected
}

export default function Submit() {
  const { notify, user } = useApp()
  const storageKey = 'print-drafts-v1:' + user.id
  const navigate = useNavigate(), location = useLocation()
  const picker = useRef<HTMLInputElement>(null)
  const visitId = useRef(randomUUID())
  const visit = useQuery({ queryKey: ['submit-visit', visitId.current], queryFn: () => post<{ visit_count: number; print_total_pages: number }>('/printing/visit', { visit_id: visitId.current }), staleTime: Infinity, refetchOnWindowFocus: false })
  const statistics = useQuery({ queryKey: ['submit-statistics'], queryFn: () => api<{ visit_count: number; print_total_pages: number }>('/printing/statistics'), enabled: !!visit.data, refetchInterval: 10000 })
  const totals = statistics.data ?? visit.data
  const retry = useRef<{ signature: string; key: string } | null>(null)
  const [drafts, setDrafts] = useState<Draft[]>(() => restoreDrafts(storageKey)), [busy, setBusy] = useState(false)
  const [previewUid, setPreviewUid] = useState<string | null>(null)
  const [draggingFiles, setDraggingFiles] = useState(false)
  const draftCount = useRef(drafts.length); draftCount.current = drafts.length
  const options = useQuery({ queryKey: ['printing-options'], queryFn: () => api<Options>('/printing/options') })
  const update = useCallback((uid: string, changes: Partial<Draft>) => setDrafts(values => values.map(d => d.uid === uid ? { ...d, ...changes } : d)), [])
  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(drafts.filter(d => d.file).map(d => ({
        uid: d.uid, filename: d.filename, file: d.file, mode: d.mode, expression: d.expression,
        copies: d.copies, orientation: d.orientation, scaling: d.scaling, parent_task_id: d.parent_task_id,
      }))))
    } catch { /* Storage restrictions must not prevent printing. */ }
  }, [drafts, storageKey])
  useEffect(() => {
    const taskId = location.state?.taskId as string | undefined
    if (!taskId) return
    let active = true
    api<{ file: PrintFile; plan: Plan; copies: number; parent_task_id: string }>('/tasks/' + taskId + '/resubmit-plan').then(data => {
      if (!active) return
      setDrafts(values => [...values, { uid: randomUUID(), file: data.file, filename: data.file.filename, mode: 'custom', expression: data.plan.page_numbers.join(','), copies: data.copies, orientation: data.plan.orientation, scaling: data.plan.scaling, parent_task_id: data.parent_task_id }])
      navigate('/submit', { replace: true, state: null })
    }).catch(error => { if (active) notify(error, true) })
    return () => { active = false }
  }, [location.state, navigate])
  async function addFiles(files: File[]) {
    if (busy) { notify('正在提交打印，请稍后再上传', true); return }
    if (!options.data) { notify('上传配置尚未加载，请稍后重试', true); return }
    if (!files.length) { notify('请拖入文件，暂不支持文件夹', true); return }
    if (files.some(file => !/\.(pdf|png|jpe?g|bmp|txt|docx?|xlsx?|pptx?)$/i.test(file.name))) { notify('请选择 PDF、Word、Excel、PPT、图片或 TXT 文件', true); return }
    if (draftCount.current + files.length > options.data.max_batch_files) { notify('文件数量超过单批上限', true); return }
    draftCount.current += files.length
    const added = files.map(file => ({ uid: randomUUID(), filename: file.name, uploading: true, mode: 'all', expression: '', copies: 1, orientation: 'portrait', scaling: 'actual' } as Draft))
    setDrafts(values => [...values, ...added])
    let uploaded = 0
    for (let index = 0; index < files.length; index++) {
      try {
        if (files[index].size > options.data.max_file_mib * 1048576) throw new Error('文件大小超过上限')
        let file: PrintFile | null = null
        if (crypto.subtle) {
          const digest = await crypto.subtle.digest('SHA-256', await files[index].arrayBuffer())
          const sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
          file = (await post<{ file: PrintFile | null }>('/files/lookup', { sha256 })).file
        }
        if (!file) {
          const data = new FormData(); data.set('file', files[index])
          file = await api<PrintFile>('/files', { method: 'POST', body: data })
        }
        update(added[index].uid, { file, uploading: false })
        uploaded++
      } catch (error) { update(added[index].uid, { error: (error as Error).message, uploading: false }) }
    }
    if (uploaded) notify(`已上传 ${uploaded} 个文件`)
  }
  const addFilesRef = useRef(addFiles); addFilesRef.current = addFiles
  useEffect(() => listenForFileDrops(window, setDraggingFiles, files => { void addFilesRef.current(files) }), [])
  function move(from: number, to: number) {
    if (busy || to < 0 || to >= drafts.length) return
    setDrafts(values => { const next = [...values]; const [item] = next.splice(from, 1); next.splice(to, 0, item); return next })
    notify('排序已更新')
  }
  const prepared = drafts.filter(isPrepared), pages = drafts.reduce((sum, d) => sum + pageCount(d) * d.copies, 0)
  const hasPending = drafts.some(isPending)
  const previewDraft = drafts.find(d => d.uid === previewUid)
  async function submit() {
    if (busy || hasPending || !prepared.length) return
    setBusy(true)
    const items = prepared.map(d => ({ plan_id: d.plan!.id, copies: d.copies, parent_task_id: d.parent_task_id ?? null }))
    const bodySignature = JSON.stringify(items)
    if (retry.current?.signature !== bodySignature) retry.current = { signature: bodySignature, key: randomUUID() }
    try {
      await post('/print-batches', { idempotency_key: retry.current.key, items })
      const remaining = drafts.length - prepared.length
      setDrafts(values => values.filter(d => !prepared.some(p => p.uid === d.uid)))
      retry.current = null
      notify(remaining ? `已提交 ${prepared.length} 个文件，${remaining} 个未提交` : '已提交')
      navigate('/queue')
    } catch (error) { notify(error as Error, true) } finally { setBusy(false) }
  }
  return <><PageHeader title="提交打印" subtitle={<span className="submit-statistics"><span>访问次数 {totals?.visit_count ?? '—'}</span><span>累计打印 {totals?.print_total_pages ?? '—'} 页</span></span>} /><ErrorNotification error={options.error ?? visit.error ?? statistics.error} /><div className="submit-layout">
    <button type="button" className="upload-zone" disabled={busy || !options.data} onClick={() => picker.current?.click()}>
      <span className="upload-icon-circle"><Upload size={42} /></span><strong>选择文件</strong><span className="upload-drag-hint">或拖放文件到页面任意位置</span><small className="upload-formats">PDF、Word、Excel、PPT、图片、TXT</small>
    </button><input ref={picker} type="file" hidden multiple accept=".pdf,.png,.jpg,.jpeg,.bmp,.txt,.doc,.docx,.xls,.xlsx,.ppt,.pptx" onChange={e => { void addFiles(Array.from(e.target.files ?? [])); e.target.value = '' }} />
    <aside className="submission-sidebar"><div className="submission-toolbar"><div><span>文件数 <strong>{drafts.length}</strong></span><span>总页数 <strong>{pages}</strong></span></div>
      <button className="button button-primary" disabled={!prepared.length || busy || hasPending} onClick={() => void submit()}><Send size={16} />{busy ? '提交中' : '打印'}</button></div>
      <div className="upload-list"><AnimatePresence initial={false}>{drafts.map((draft, index) => <FileCard key={draft.uid} draft={draft} maxCopies={options.data?.max_copies ?? 20}
        update={changes => update(draft.uid, changes)} remove={() => { setDrafts(values => values.filter(d => d.uid !== draft.uid)); notify('文件已移除') }} move={offset => move(index, index + offset)} first={index === 0} last={index === drafts.length - 1}
        preview={() => setPreviewUid(draft.uid)} disabled={busy} />)}</AnimatePresence>{!drafts.length && <p className="empty-upload-list">尚未添加文件</p>}</div>
    </aside></div><Preview planId={previewDraft && isPrepared(previewDraft) ? previewDraft.plan!.id : null} open={!!previewDraft} close={() => setPreviewUid(null)} />
    {createPortal(<AnimatePresence>{draggingFiles && <motion.div className="file-drop-overlay" role="status" aria-live="polite"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .12 }}>
      <div className="file-drop-frame"><div className="file-drop-content"><span className="file-drop-icon"><Upload size={54} strokeWidth={1.5} /></span>
        <span className="file-drop-eyebrow">提交打印</span><strong>{busy ? '正在提交，请稍候' : !options.data ? '正在连接，请稍候' : '松手上传'}</strong>
        <p>{busy || !options.data ? '准备完成后即可继续拖放文件' : '拖到这里就好，支持一次上传多个文件'}</p>
        <span className="file-drop-formats">PDF、Word、Excel、PPT、图片、TXT</span>
      </div></div></motion.div>}</AnimatePresence>, document.body)}
    </>
}

function FileCard({ draft, maxCopies, update, remove, move, first, last, preview, disabled }: {
  draft: Draft; maxCopies: number; update: (changes: Partial<Draft>) => void; remove: () => void; move: (offset: number) => void;
  first: boolean; last: boolean; preview: () => void; disabled: boolean;
}) {
  const [requestError, setRequestError] = useState<Error | null>(null), [retryVersion, setRetryVersion] = useState(0), [advanced, setAdvanced] = useState(false)
  const [editingPages, setEditingPages] = useState(false)
  const awaitingPages = draft.mode === 'custom' && (!draft.expression.trim() || (editingPages && pageCount(draft) === 0))
  const updateRef = useRef(update); updateRef.current = update
  const readyPlans = useRef(new Map<string, Plan>())
  const currentSignature = signature(draft)
  const file = useQuery({ queryKey: ['file', draft.file?.id], queryFn: () => api<PrintFile>('/files/' + draft.file!.id), enabled: !!draft.file && draft.file.status === 'processing', refetchInterval: query => ['ready', 'failed'].includes(query.state.data?.status ?? '') ? false : 2000 })
  const plan = useQuery({ queryKey: ['plan', draft.plan?.id], queryFn: () => api<Plan>('/render-plans/' + draft.plan!.id), enabled: !!draft.plan && draft.plan.status === 'processing', refetchInterval: query => ['ready', 'failed'].includes(query.state.data?.status ?? '') ? false : 1000 })
  useEffect(() => { if (file.data && file.data.status !== draft.file?.status) updateRef.current({ file: file.data }) }, [file.data, draft.file?.status])
  useEffect(() => { if (plan.data && plan.data.id === draft.plan?.id && plan.data.status !== draft.plan?.status) updateRef.current({ plan: plan.data }) }, [plan.data, draft.plan?.id, draft.plan?.status])
  useEffect(() => {
    if (draft.plan?.status === 'ready' && draft.planSignature) readyPlans.current.set(draft.planSignature, draft.plan)
  }, [draft.plan, draft.planSignature])
  useEffect(() => {
    if (draft.file?.status !== 'ready') return
    const controller = new AbortController()
    setRequestError(null)
    if (awaitingPages) {
      updateRef.current({ plan: undefined, planSignature: undefined, planPending: false })
      return
    }
    const cached = readyPlans.current.get(currentSignature)
    if (cached) {
      updateRef.current({ plan: cached, planSignature: currentSignature, planPending: false })
      return
    }
    updateRef.current({ plan: undefined, planSignature: undefined, planPending: true })
    const timer = window.setTimeout(async () => {
      try {
        const generated = await api<Plan>('/render-plans', { method: 'POST', signal: controller.signal, body: JSON.stringify({ document_id: draft.file!.id, mode: draft.mode, expression: draft.expression, orientation: draft.orientation, scaling: draft.scaling }) })
        if (!controller.signal.aborted) {
          if (generated.status === 'ready') readyPlans.current.set(currentSignature, generated)
          updateRef.current({ plan: generated, planSignature: currentSignature, planPending: false })
        }
      } catch (error) { if (!controller.signal.aborted) { setRequestError(error as Error); updateRef.current({ planPending: false }) } }
    }, 300)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [currentSignature, draft.file?.status, retryVersion, awaitingPages])
  const failed = draft.error || draft.file?.status === 'failed' || draft.plan?.status === 'failed' || requestError
  const ready = isPrepared(draft), pending = isPending(draft)
  const change = (changes: Partial<Draft>) => {
    setRequestError(null)
    const nextSignature = signature({ ...draft, ...changes })
    const cached = readyPlans.current.get(nextSignature)
    update({ ...changes, plan: cached, planSignature: cached ? nextSignature : undefined, planPending: !cached })
  }
  return <motion.article layout="position" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 12 }} transition={{ duration: .2 }} className={'file-card ' + (failed ? 'file-failed' : '')}>
    <header><button className={'icon-button preview-upload ' + (failed ? 'preview-failed' : '')} title={pending ? '正在生成预览' : failed ? '重试预览' : '预览'} aria-label={pending ? '正在生成预览' : failed ? '重试预览' : '预览'} disabled={!!pending || disabled || draft.file?.status !== 'ready'} onClick={() => { if (ready) preview(); else setRetryVersion(value => value + 1) }}>
      {pending ? <LoaderCircle size={19} className="spin" /> : failed ? <X size={19} /> : <Eye size={19} />}</button>
      <div className="file-title"><strong title={draft.filename}>{draft.filename}</strong><small>{draft.file?.page_count ? `${pageCount(draft)} / ${draft.file.page_count} 页` : ''}</small></div>
      <button className="icon-button" title="上移" disabled={disabled || first} aria-label="上移文件" onClick={() => move(-1)}><ArrowUp size={15} /></button><button className="icon-button" title="下移" disabled={disabled || last} aria-label="下移文件" onClick={() => move(1)}><ArrowDown size={15} /></button>
      <button className="icon-button remove-button" title="移除" disabled={disabled} aria-label="移除文件" onClick={remove}><X size={18} /></button></header>
    <fieldset disabled={disabled || draft.file?.status !== 'ready'}><div className="file-controls"><div className="segmented" role="group" aria-label="页码范围"><motion.span aria-hidden="true" className="page-mode-slider" initial={false} animate={{ x: `${['all', 'odd', 'even', 'custom'].indexOf(draft.mode) * 100}%` }} transition={{ duration: .24, ease: [.22, 1, .36, 1] }} />{[['all', '全部页'], ['odd', '奇数页'], ['even', '偶数页'], ['custom', '自定义']].map(([value, label]) => <button type="button" key={value} disabled={value === 'even' && (draft.file?.page_count ?? 0) < 2} className={draft.mode === value ? 'selected' : ''} aria-pressed={draft.mode === value} onClick={() => { if (value !== draft.mode) change({ mode: value }) }}>{label}</button>)}</div>
      <label className="copies-label">份数<input type="number" step={1} min={1} max={maxCopies} value={draft.copies} onChange={e => { const copies = Math.min(maxCopies, Math.max(1, Math.trunc(Number(e.target.value)) || 1)); if (copies !== draft.copies) update({ copies }) }} /></label></div>
      <AnimatePresence initial={false}>{draft.mode === 'custom' && <motion.div key="custom" className="custom-editor" initial={{ height: 0, opacity: 0, overflow: 'hidden' }} animate={{ height: 'auto', opacity: 1, overflow: 'hidden', transitionEnd: { overflow: 'visible' } }} exit={{ height: 0, opacity: 0, overflow: 'hidden' }}><input className="page-expression" value={draft.expression} onFocus={() => setEditingPages(true)} onBlur={() => setEditingPages(false)} onChange={e => change({ expression: e.target.value })} placeholder="例如：3,1-2,3" aria-label="自定义页码" /></motion.div>}</AnimatePresence>
      <button className={'advanced-toggle ' + (advanced ? 'expanded' : '')} type="button" aria-expanded={advanced} onClick={() => setAdvanced(value => !value)}><ChevronDown size={15} />高级设置</button>
      <AnimatePresence initial={false}>{advanced && <motion.div className="advanced-wrapper" initial={{ height: 0, opacity: 0, overflow: 'hidden' }} animate={{ height: 'auto', opacity: 1, overflow: 'hidden', transitionEnd: { overflow: 'visible' } }} exit={{ height: 0, opacity: 0, overflow: 'hidden' }}><div className="advanced-controls"><label>方向<select value={draft.orientation} onChange={e => change({ orientation: e.target.value })}><option value="portrait">纵向</option><option value="landscape">横向</option></select></label><label>缩放<select value={draft.scaling} onChange={e => change({ scaling: e.target.value })}><option value="actual">实际尺寸</option><option value="fit">适合可打印区域</option><option value="75%">75%</option><option value="50%">50%</option><option value="25%">25%</option></select></label></div></motion.div>}</AnimatePresence>
    </fieldset><ErrorNotification needsAdmin={[draft.file?.error_code, draft.plan?.error_code].some(code => ['converter_unavailable', 'conversion_failed', 'render_failed'].includes(code ?? ''))} error={draft.error ? new Error(draft.error) : requestError ?? file.error ?? plan.error ?? (draft.file?.status === 'failed' ? new Error('文件处理失败') : draft.plan?.status === 'failed' ? new Error('预览生成失败') : null)} />
  </motion.article>
}
