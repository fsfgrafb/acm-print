import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { Download, Eye, Pause, Play, RefreshCw, RotateCcw, Printer, X } from 'lucide-react'
import { api, post, time, type QueueData, type QueueItem } from '../api'
import { ErrorNotice, PageHeader, Preview, useApp } from '../ui'

const labels: Record<string, string> = {
  queued: '排队中', submitting: '提交确认中', submitted: '已提交设备', printing: '正在打印',
  cancelling: '等待取消确认', queue_ended: '队列已结束', cancelled: '已取消', failed: '提交失败', unknown: '结果未知',
}

export default function Queue() {
  const { user, notify } = useApp()
  const [activePage, setActivePage] = useState(1)
  const [historyPage, setHistoryPage] = useState(1)
  const [preview, setPreview] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const active = useQuery({ queryKey: ['queue', 'active', activePage],
    queryFn: () => api<QueueData>(`/queue?scope=active&page=${activePage}`), refetchInterval: 5000 })
  const history = useQuery({ queryKey: ['queue', 'history', historyPage],
    queryFn: () => api<QueueData>(`/queue?scope=history&page=${historyPage}`), refetchInterval: 5000 })
  const status = active.data ?? history.data
  const deviceFault = status && !status.paused && (status.device.blocked || !status.device.available)
  const refresh = () => Promise.all([active.refetch(), history.refetch()])
  async function action(path: string, message: string) {
    setBusy(true)
    try { await post(path); notify(message); await refresh() }
    catch (error) { notify((error as Error).message, true) }
    finally { setBusy(false) }
  }
  return <>
    <PageHeader title="任务队列" action={<button className="button" onClick={() => void refresh()}><RefreshCw size={16} />刷新</button>} />
    {status && <div className="device-banner"><span className="device-icon"><Printer size={22} /></span>
      <div><strong>{status.paused ? '应用队列已暂停' : status.device.message}</strong>
        {deviceFault && <p className="device-contact"><span>请联系管理员</span>
          {status.admin_contact?.email && <span>邮箱：{status.admin_contact.email}</span>}
          {status.admin_contact?.phone && <span>手机号：{status.admin_contact.phone}</span>}
        </p>}</div>
      {user.admin && <button className="button" disabled={busy} onClick={() => void action('/admin/queue/' + (status.paused ? 'resume' : 'pause'), '队列状态已更新')}>
        {status.paused ? <Play size={15} /> : <Pause size={15} />}{status.paused ? '恢复队列' : '暂停队列'}
      </button>}
    </div>}
    <QueueSection title="当前任务" data={active.data} pending={active.isPending} error={active.error}
      page={activePage} setPage={setActivePage} busy={busy} preview={setPreview} action={action} />
    <QueueSection title="历史记录" data={history.data} pending={history.isPending} error={history.error}
      page={historyPage} setPage={setHistoryPage} busy={busy} preview={setPreview} action={action} />
    <Preview planId={preview} close={() => setPreview(null)} />
  </>
}

function QueueSection({ title, data, pending, error, page, setPage, busy, preview, action }: {
  title: string; data?: QueueData; pending: boolean; error: unknown; page: number; setPage: (page: number) => void;
  busy: boolean; preview: (plan: string) => void; action: (path: string, message: string) => Promise<void>;
}) {
  return <section className="queue-section" aria-label={title}>
    <div className="section-heading"><h2>{title}</h2></div>
    <ErrorNotice error={error} />
    {pending ? <div className="panel loading" role="status">加载中</div> : data && (
      data.items.length ? <div className="queue-list"><AnimatePresence initial={false}>
        {data.items.map(task => <TaskCard key={task.id} task={task} busy={busy} preview={preview} action={action} />)}
      </AnimatePresence></div> : <div className="queue-empty">暂无记录</div>
    )}
    {(page > 1 || data?.has_more) && <div className="pagination" aria-label={title + '分页'}>
      <button className="button button-small" disabled={page === 1 || pending} onClick={() => setPage(page - 1)}>上一页</button>
      <span>第 {page} 页</span>
      <button className="button button-small" disabled={!data?.has_more || pending} onClick={() => setPage(page + 1)}>下一页</button>
    </div>}
  </section>
}

function TaskCard({ task, busy, preview, action }: {
  task: QueueItem; busy: boolean; preview: (plan: string) => void; action: (path: string, message: string) => Promise<void>;
}) {
  const { user, branding } = useApp()
  const navigate = useNavigate()
  return <motion.article layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: -8 }} transition={{ duration: .18 }} className="task-card">
    <div className="task-main"><span className={'task-symbol ' + (task.state === 'unknown' ? 'warning' : '')}><Printer size={21} /></span>
      <div><div className="task-heading"><strong>{task.filename ?? branding.identity_label + ' ' + task.student_id}</strong>
        {task.mine && <span className="mine-tag">我的任务</span>}</div>
        <p>{user.admin && `${branding.identity_label} ${task.student_id} · `}{time(task.created_at)} · {task.total_pages} 页</p>
      </div><span className={'status-pill ' + (task.state === 'unknown' ? 'warning' : task.state === 'failed' ? 'danger' : task.state === 'queue_ended' ? 'success' : ['submitting', 'submitted', 'printing', 'cancelling'].includes(task.state) ? 'info' : '')}>
        {labels[task.state] ?? task.state}
      </span>
    </div>
    {(task.can_cancel || task.can_download || task.plan_id) && <div className="task-actions">
      {task.plan_id && <button onClick={() => preview(task.plan_id!)}><Eye size={15} />预览</button>}
      {task.can_download && <><a href={'/api/tasks/' + task.id + '/original'}><Download size={15} />原件</a>
        <a href={'/api/tasks/' + task.id + '/pdf'}><Download size={15} />打印 PDF</a>
        <button onClick={() => navigate('/submit', { state: { taskId: task.id } })}><RotateCcw size={15} />再次打印</button></>}
      {task.can_cancel && <button className="danger-text" disabled={busy} onClick={() => {
        if (task.state === 'queued' || window.confirm('已出纸的部分无法撤回，是否请求取消？'))
          void action('/tasks/' + task.id + '/cancel', '取消请求已记录，请查看任务状态')
      }}><X size={15} />取消任务</button>}
    </div>}
    {task.state === 'unknown' && <p className="unknown-note">提交结果未知，请联系管理员核对。</p>}
  </motion.article>
}
