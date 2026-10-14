import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRightLeft, Ban, CalendarPlus, Download, FileUp, PencilLine, RotateCcw, ShieldCheck, UsersRound, X } from 'lucide-react'
import { api, patch, post, time } from '../api'
import { Empty, ErrorNotice, Modal, PageHeader, useApp } from '../ui'
import { validateContacts } from '../contacts'

interface Member { id: string; student_id: string; email: string; phone: string; banned: boolean; admin: boolean; created_at: string; expires_at: string }
interface ImportRow { line: number; student_id: string; status: string; reason: string }
export default function Members() {
  const { branding, notify } = useApp()
  const picker = useRef<HTMLInputElement>(null)
  const commitKey = useRef('')
  const [page, setPage] = useState(1)
  const [csv, setCsv] = useState<File | null>(null)
  const [rows, setRows] = useState<ImportRow[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [target, setTarget] = useState<Member | null>(null)
  const [expiryTarget, setExpiryTarget] = useState<Member | null>(null)
  const [expiryValue, setExpiryValue] = useState('')
  const [expiryError, setExpiryError] = useState<Error | null>(null)
  const [importError, setImportError] = useState<Error | null>(null)
  const members = useQuery({ queryKey: ['members', page], queryFn: () => api<{ items: Member[]; has_more: boolean }>('/admin/students?page=' + page) })
  async function action(work: () => Promise<unknown>, message: string) { setBusy(true); setError(null); try { await work(); notify(message); await members.refetch() } catch (e) { setError(e as Error) } finally { setBusy(false) } }
  function closeImport() {
    if (busy) return
    setCsv(null)
    setRows([])
    setImportError(null)
  }
  async function confirmImport() {
    if (!csv || busy) return
    setBusy(true)
    setImportError(null)
    try {
      const body = new FormData()
      body.set('file', csv)
      const result = await api<{ added: number; skipped: number; invalid: number }>('/admin/import/commit?key=' + commitKey.current, { method: 'POST', body })
      setCsv(null)
      setRows([])
      setPage(1)
      notify(`新增 ${result.added}，跳过 ${result.skipped}，无效 ${result.invalid}`)
      await members.refetch()
    } catch (err) { setImportError(err as Error) }
    finally { setBusy(false) }
  }
  return <><PageHeader title="用户管理" />
    <ErrorNotice error={error ?? members.error} /><section className="import-guide"><span><UsersRound size={22} /></span><div><strong>导入用户</strong></div><div className="import-guide-actions"><a className="button button-small" download="members-template.csv" href={'data:text/csv;charset=utf-8,' + encodeURIComponent('\ufeffstudent_id,email（选填）,phone（选填）\n0001,,\n')}><Download size={16} />下载模板</a><button className="button button-small button-primary" disabled={busy} onClick={() => picker.current?.click()}><FileUp size={16} />导入 CSV</button></div></section>
    <input ref={picker} type="file" accept=".csv" hidden onChange={async e => { const file = e.target.files?.[0]; e.target.value = ''; if (!file) return; setCsv(null); setRows([]); setImportError(null); setBusy(true); setError(null); try { const body = new FormData(); body.set('file', file); const result = await api<{ rows: ImportRow[] }>('/admin/import/preview', { method: 'POST', body }); setCsv(file); setRows(result.rows); commitKey.current = crypto.randomUUID() } catch (err) { setError(err as Error) } finally { setBusy(false) } }} />
    <Modal open={!!csv} close={closeImport} label="CSV 导入预览" className="panel import-modal">
      {csv && <>
        <div className="section-heading"><h2 title={csv.name}>导入预览 · {csv.name}</h2>
          <button className="icon-button remove-button" title="关闭" aria-label="关闭导入预览" disabled={busy} onClick={closeImport}><X size={18} /></button>
        </div>
        <p className="import-counts">{rows.filter(r => r.status === 'new').length} 行待新增 · {rows.filter(r => r.status === 'skipped').length} 行跳过 · {rows.filter(r => r.status === 'invalid').length} 行无效</p>
        <ErrorNotice error={importError} />
        <div className="table-scroll import-table"><table><thead><tr><th>行号</th><th>{branding.identity_label}</th><th>结果</th><th>说明</th></tr></thead>
          <tbody>{rows.slice(0, 100).map(row => <tr key={row.line}><td>{row.line}</td><td>{row.student_id}</td><td>{row.status === 'new' ? '新增' : row.status === 'skipped' ? '跳过' : '无效'}</td><td>{row.reason || '校验通过'}</td></tr>)}</tbody>
        </table></div>
        {rows.length > 100 && <p className="form-note">此处展示前 100 行，确认时处理全部 {rows.length} 行。</p>}
        <div className="button-row import-actions"><button className="button" disabled={busy} onClick={closeImport}>取消</button>
          <button className="button button-primary" disabled={busy || !rows.some(r => r.status === 'new')} onClick={() => void confirmImport()}>{busy ? '导入中' : '确认导入'}</button>
        </div>
      </>}
    </Modal>
    <section className="panel members-panel"><div className="section-heading"><h2>成员列表</h2></div><div className="table-scroll"><table><thead><tr><th>{branding.identity_label}</th><th>联系方式</th><th>注册时间</th><th>注销时间</th><th>状态</th><th>操作</th></tr></thead><tbody>{members.data?.items.map(member => <tr key={member.id}><td><strong>{member.student_id}</strong>{member.admin && <small className="admin-tag">管理员</small>}</td><td className="member-contacts"><span>{member.email || '—'}</span><span>{member.phone || '—'}</span></td><td>{time(member.created_at)}</td><td>{time(member.expires_at)}</td><td><span className={'status-pill ' + (member.banned ? 'danger' : 'success')}>{member.banned ? '封禁' : '正常'}</span></td><td><div className="table-actions"><button className="icon-button member-action" title="重置密码" aria-label="重置密码" disabled={busy} onClick={() => { if (window.confirm('将密码恢复为' + branding.identity_label + '并撤销所有会话？')) void action(() => post('/admin/students/' + member.id + '/reset-password'), '密码已重置') }}><RotateCcw size={18} /></button>
      <button className="icon-button member-action" title="编辑联系方式" aria-label="编辑联系方式" disabled={busy} onClick={() => { const email = window.prompt('修改 邮箱，留空表示不填写', member.email); if (email === null) return; const phone = window.prompt('修改手机号，留空表示不填写', member.phone); if (phone !== null) void action(() => patch('/admin/students/' + member.id, validateContacts(email, phone)), '联系方式已更新') }}><PencilLine size={18} /></button>
      <button className="icon-button member-action" title="延长注销时间" aria-label="延长注销时间" disabled={busy} onClick={() => { setExpiryTarget(member); setExpiryValue(''); setExpiryError(null) }}><CalendarPlus size={18} /></button>
      {!member.admin && <><button className={'icon-button member-action ' + (member.banned ? '' : 'member-action-danger')} title={member.banned ? '解禁' : '封禁'} aria-label={member.banned ? '解禁' : '封禁'} disabled={busy} onClick={() => void action(() => patch('/admin/students/' + member.id, { banned: !member.banned }), '成员状态已更新')}>{member.banned ? <ShieldCheck size={18} /> : <Ban size={18} />}</button><button className="icon-button member-action" title="管理员交接" aria-label="管理员交接" disabled={busy || member.banned} onClick={() => setTarget(member)}><ArrowRightLeft size={18} /></button></>}</div></td></tr>)}</tbody></table></div>{!members.data?.items.length && <Empty title="暂时没有成员" description="通过 CSV 批量导入成员。" />}</section>
    <div className="pagination"><button className="button button-small" disabled={page === 1} onClick={() => setPage(p => p - 1)}>上一页</button><span>第 {page} 页</span><button className="button button-small" disabled={!members.data?.has_more} onClick={() => setPage(p => p + 1)}>下一页</button></div>
    <Modal open={!!expiryTarget} close={() => { if (!busy) setExpiryTarget(null) }} label="延长注销时间" className="panel transfer-modal">{expiryTarget && <><h2>延长注销时间</h2><p>{expiryTarget.student_id}</p><form onSubmit={async e => {
      e.preventDefault()
      const expiry = new Date(expiryValue)
      if (!Number.isFinite(expiry.getTime()) || expiry.getTime() <= Math.max(Date.now(), new Date(expiryTarget.expires_at).getTime())) { setExpiryError(new Error('新的注销时间必须晚于当前注销时间和现在')); return }
      setBusy(true); setExpiryError(null)
      try { await patch('/admin/students/' + expiryTarget.id, { expires_at: expiry.toISOString() }); setExpiryTarget(null); notify('注销时间已延长'); await members.refetch() }
      catch (err) { setExpiryError(err as Error) } finally { setBusy(false) }
    }}><label>当前注销时间<input value={time(expiryTarget.expires_at)} readOnly /></label><label>新的注销时间<input type="datetime-local" value={expiryValue} onChange={e => setExpiryValue(e.target.value)} required disabled={busy} /></label><ErrorNotice error={expiryError} /><div className="button-row"><button type="button" className="button" disabled={busy} onClick={() => setExpiryTarget(null)}>取消</button><button className="button button-primary" disabled={busy || !expiryValue}>{busy ? '保存中' : '确认延长'}</button></div></form></>}</Modal>
    <Modal open={!!target} close={() => { if (!busy) setTarget(null) }} label="管理员交接" className="panel transfer-modal">{target && <><ShieldCheck size={26} /><h2>将管理员交接给 {target.student_id}</h2><p>交接后你将成为用户，双方登录会话都会撤销。</p><form onSubmit={async e => { e.preventDefault(); const body = new FormData(e.currentTarget); setBusy(true); try { await post('/admin/transfer', { target_id: target.id, password: body.get('password') }); window.location.reload() } catch (err) { setError(err as Error) } finally { setBusy(false) } }}><label>当前管理员密码<input name="password" type="password" autoComplete="current-password" required /></label><ErrorNotice error={error} /><div className="button-row"><button type="button" className="button" disabled={busy} onClick={() => setTarget(null)}>返回</button><button className="button button-primary" disabled={busy}>确认交接</button></div></form></>}</Modal></>
}
