import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion, MotionConfig } from 'motion/react'
import { AlertCircle, CheckCircle2, LoaderCircle, X } from 'lucide-react'
import { api, ApiError, type Branding, type User } from './api'
import { adminContactText } from './contacts'

type Notify = (message: string | Error, error?: boolean, needsAdmin?: boolean) => void

export const AppContext = createContext<{
  branding: Branding; user: User; updateUser: (user: User) => void;
  notify: Notify;
}>({} as never)
export const useApp = () => useContext(AppContext)
const NotificationContext = createContext<Notify>(() => {})
export const useNotify = () => useContext(NotificationContext)

export function NotificationProvider({ children }: { children: (notify: Notify) => ReactNode }) {
  const [message, setMessage] = useState<{ id: number; text: string; error: boolean } | null>(null)
  const nextId = useRef(0)
  const invalidBatch = useRef(false)
  const notify = useCallback<Notify>((value, error = false, needsAdmin = false) => {
    const text = typeof value === 'string' ? value : value.message
    const id = ++nextId.current
    const contactRequired = error && (needsAdmin || (value instanceof ApiError && (value.status >= 500 || value.code === 'converter_unavailable')))
    const reason = text.replace(/(?:[，。\s]*)请联系管理员.*$/, '').replace(/[。！？\s]+$/, '')
    setMessage({ id, text: contactRequired ? `${reason}，请联系管理员。` : text, error })
    if (contactRequired) void api<User>('/auth/me').then(user => {
      setMessage(current => current?.id === id ? { ...current, text: `${reason}，${adminContactText(user.admin_contact)}` } : current)
    }).catch(() => {})
  }, [])
  useEffect(() => {
    if (!message) return
    const id = message.id
    const timer = window.setTimeout(() => setMessage(current => current?.id === id ? null : current), 5000)
    return () => window.clearTimeout(timer)
  }, [message?.id])
  return <NotificationContext.Provider value={notify}><div style={{ display: 'contents' }} onInvalidCapture={event => {
    event.preventDefault()
    if (invalidBatch.current) return
    invalidBatch.current = true
    queueMicrotask(() => { invalidBatch.current = false })
    const field = event.target as HTMLInputElement
    field.focus()
    notify(field.validationMessage || '请检查输入内容', true)
  }}>{children(notify)}</div><AnimatePresence>{message && <motion.div key={message.id}
    initial={{ opacity: 0, x: 100 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 100 }}
    transition={{ duration: .28, ease: [.22, 1, .36, 1] }} className={'toast ' + (message.error ? 'toast-error' : '')}
    role={message.error ? 'alert' : 'status'}>
    {message.error ? <AlertCircle size={20} /> : <CheckCircle2 size={20} />}<span className="toast-message">{message.text}</span>
    <button className="toast-close" aria-label="关闭通知" title="关闭" onClick={() => setMessage(null)}><X size={18} /></button>
    <div className="toast-progress" aria-hidden="true"><motion.div className="toast-progress-fill"
      initial={{ width: '100%' }} animate={{ width: '0%' }} transition={{ duration: 5, ease: 'linear' }} /></div>
  </motion.div>}</AnimatePresence></NotificationContext.Provider>
}

export function PageHeader({ title, action, subtitle }: { title: string; action?: ReactNode; subtitle?: ReactNode }) {
  return <header className="page-header"><div><h1>{title}</h1>{subtitle && <p className="page-subtitle">{subtitle}</p>}</div>{action}</header>
}
export function ErrorNotification({ error, needsAdmin = false }: { error: unknown; needsAdmin?: boolean }) {
  const notify = useNotify()
  const text = error ? error instanceof Error ? error.message : '暂时无法加载' : ''
  useEffect(() => { if (text) notify(error instanceof Error ? error : text, true, needsAdmin) }, [text, notify, needsAdmin])
  return null
}
export function Empty({ title, description, children }: { title: string; description: string; children?: ReactNode }) {
  return <div className="empty-state"><div className="empty-symbol">↳</div><h3>{title}</h3><p>{description}</p>{children}</div>
}
export function Modal({ open, close, label, className = '', children }: { open: boolean; close: () => void; label: string; className?: string; children: ReactNode }) {
  const dialog = useRef<HTMLElement>(null)
  const closeRef = useRef(close); closeRef.current = close
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog.current?.focus()
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeRef.current()
      if (event.key === 'Tab') {
        const controls = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input, select, a[href], iframe')
        if (!controls?.length) { event.preventDefault(); return }
        const first = controls[0], last = controls[controls.length - 1]
        if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', key)
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', key); previous?.focus() }
  }, [open])
  return <MotionConfig reducedMotion="user"><AnimatePresence>{open && <motion.div className="modal-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .18 }} onClick={close}>
    <motion.section ref={dialog} tabIndex={-1} className={className} role="dialog" aria-modal="true" aria-label={label} initial={{ opacity: 0, scale: .96, y: 14 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: .96, y: 12 }} transition={{ duration: .2 }} onClick={e => e.stopPropagation()}>{children}</motion.section>
  </motion.div>}</AnimatePresence></MotionConfig>
}
export function Preview({ planId, open = !!planId, close }: { planId: string | null; open?: boolean; close: () => void }) {
  return <Modal open={open} close={close} label="打印预览" className="preview-modal">
    <header><strong>打印预览</strong><button className="icon-button remove-button" title="关闭" onClick={close} aria-label="关闭预览"><X /></button></header>
    {planId ? <iframe key={planId} title="打印 PDF" src={'/api/render-plans/' + planId + '/pdf'} /> : <div className="preview-loading"><LoaderCircle className="spin" size={26} /></div>}
  </Modal>
}
