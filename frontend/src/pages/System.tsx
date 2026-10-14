import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Database, Download, HardDrive, HardDriveDownload, Settings2 } from 'lucide-react'
import { api, downloadFile, patch } from '../api'
import { ErrorNotification, PageHeader, useApp } from '../ui'
import DatePicker from '../DatePicker'

interface SettingsData { values: Record<string, number>; version: number; ranges: Record<string, { min: number; max: number }> }
const settingLabels: Record<string, string> = {
  max_copies: '份数上限', storage_limit_gb: '总空间上限（GB）', cleanup_target_percent: '清理目标（%）',
  min_password_length: '密码最小长度', max_file_mib: '文件上限（MiB）', max_batch_files: '批量文件上限',
  max_source_pages: '原文页数上限', max_plan_pages: '单任务选页上限', max_image_pixels: '图片像素上限',
  temporary_budget_mib: '临时文件预算（MiB）', conversion_timeout_seconds: '转换超时（秒）',
  poll_seconds: 'worker 轮询间隔（秒）', session_days: '会话有效期（天）', temporary_hours: '临时保留期（小时）', idempotency_days: '幂等墓碑保留期（天）',
}
const gigabytes = (bytes: number) => (bytes / 1000000000).toFixed(2)
export default function System() {
  const { branding, notify } = useApp()
  const client = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [identity, setIdentity] = useState('')
  const [filter, setFilter] = useState('')
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => api<SettingsData>('/admin/settings') })
  const storage = useQuery({ queryKey: ['storage'], queryFn: () => api<{ file_bytes: number; database_bytes: number; disk_free_bytes: number; limit_bytes: number }>('/admin/storage'), refetchInterval: 30000 })
  const stats = useQuery({ queryKey: ['stats', filter], queryFn: () => api<{ items: { student_id: string; task_count: number; planned_pages: number }[] }>('/admin/stats' + filter), staleTime: 30000 })
  const data = storage.data
  const used = data ? data.file_bytes + data.database_bytes : 0
  return <><PageHeader title="系统管理" /><ErrorNotification error={settings.error ?? storage.error ?? stats.error} />
    <div className="metric-grid"><div className="metric-card"><HardDrive size={20} /><span>应用总占用</span><strong>{data ? gigabytes(used) : '—'} <small>GB</small></strong><div className="storage-track"><i style={{ width: data ? `${Math.min(100, used / data.limit_bytes * 100)}%` : '0%' }} /></div><p>上限 {data ? gigabytes(data.limit_bytes) : '—'} GB</p></div>
      <div className="metric-card"><Database size={20} /><span>文件 / 数据库</span><strong>{data ? gigabytes(data.file_bytes) : '—'} <small>GB</small></strong><p>数据库物理占用 {data ? gigabytes(data.database_bytes) : '—'} GB</p></div><div className="metric-card"><HardDriveDownload size={20} /><span>磁盘可用空间</span><strong>{data ? gigabytes(data.disk_free_bytes) : '—'} <small>GB</small></strong><p>独立于应用额度检查</p></div></div>
    <section className="panel"><div className="section-heading"><h2><Settings2 size={18} />运行配置</h2></div>{settings.data && <form key={settings.data.version} onSubmit={async e => { e.preventDefault(); setBusy(true); const values = Object.fromEntries(Array.from(new FormData(e.currentTarget).entries()).map(([key, value]) => [key, Number(value)])); try { await patch('/admin/settings', { version: settings.data!.version, values }); await settings.refetch(); notify('运行配置已更新') } catch (error) { notify(error as Error, true) } finally { setBusy(false) } }}>
      <div className="settings-grid">{Object.entries(settings.data.values).map(([key, value]) => <label key={key}>{settingLabels[key] ?? key}<input type="number" name={key} defaultValue={value} required step={1} min={settings.data!.ranges[key].min} max={settings.data!.ranges[key].max} /></label>)}</div><button className="button button-primary" disabled={busy}>{busy ? '正在保存…' : '保存运行配置'}</button></form>}</section>
    <section className="panel stats-panel"><div className="section-heading"><div><h2>成功提交统计</h2></div><button className="button" disabled={exporting} onClick={async () => { setExporting(true); try { await downloadFile('/admin/stats.csv' + filter, 'stats.csv'); notify('导出成功') } catch (err) { notify(err as Error, true) } finally { setExporting(false) } }}><Download size={16} />{exporting ? '导出中' : '导出 CSV'}</button></div>
      <form className="stats-filter" onSubmit={async e => { e.preventDefault(); const parameters = new URLSearchParams(); if (start) parameters.set('start', new Date(start + 'T00:00:00+08:00').toISOString()); if (end) parameters.set('end', new Date(new Date(end + 'T00:00:00+08:00').getTime() + 86400000).toISOString()); if (identity) parameters.set('student_id', identity); const nextFilter = parameters.size ? '?' + parameters : ''; setFilter(nextFilter); try { await client.fetchQuery({ queryKey: ['stats', nextFilter], queryFn: () => api('/admin/stats' + nextFilter), staleTime: 0 }); notify('查询完成') } catch (err) { notify(err as Error, true) } }}><DatePicker label="开始日期" value={start} onChange={setStart} /><DatePicker label="结束日期" value={end} onChange={setEnd} /><label>{branding.identity_label}<input value={identity} onChange={e => setIdentity(e.target.value)} placeholder="全部成员" /></label><button className="button">查询</button></form>
      <div className="table-scroll"><table><thead><tr><th>{branding.identity_label}</th><th>成功提交任务</th><th>计划页数</th></tr></thead><tbody>{stats.data?.items.map(row => <tr key={row.student_id}><td>{row.student_id}</td><td>{row.task_count}</td><td>{row.planned_pages}</td></tr>)}</tbody></table></div>{!stats.data?.items.length && <p className="form-note">当前筛选范围暂无成功提交记录。</p>}</section>
  </>
}
