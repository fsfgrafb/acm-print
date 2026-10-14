import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion, MotionConfig } from 'motion/react'
import { AlertCircle, CheckCircle2, LoaderCircle, X } from 'lucide-react'
import type { Branding, User } from './api'

export const AppContext = createContext<{
  branding: Branding; user: User; updateUser: (user: User) => void;
  notify: (message: string, error?: boolean) => void;
}>({} as never)
export const useApp = () => useContext(AppContext)

export function NotificationProvider({ children }: { children: (notify: (message: string, error?: boolean) => void) => ReactNode }) {
  const [message, setMessage] = useState<{ id: number; text: string; error: boolean } | null>(null)
  const nextId = useRef(0)
  const notify = useCallback((text: string, error = false) => setMessage({ id: ++nextId.current, text, error }), [])
  useEffect(() => {
    if (!message) return
    const id = message.id
    const timer = window.setTimeout(() => setMessage(current => current?.id === id ? null : current), 5000)
    return () => window.clearTimeout(timer)
  }, [message?.id])
  return <>{children(notify)}<AnimatePresence>{message && <motion.div key={message.id}
    initial={{ opacity: 0, x: 100 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 100 }}
    transition={{ duration: .28, ease: [.22, 1, .36, 1] }} className={'toast ' + (message.error ? 'toast-error' : '')}
    role={message.error ? 'alert' : 'status'}>
    {message.error ? <AlertCircle size={20} /> : <CheckCircle2 size={20} />}<span className="toast-message">{message.text}</span>
    <button className="toast-close" aria-label="关闭通知" title="关闭" onClick={() => setMessage(null)}><X size={18} /></button>
    <div className="toast-progress" aria-hidden="true"><motion.div className="toast-progress-fill"
      initial={{ width: '100%' }} animate={{ width: '0%' }} transition={{ duration: 5, ease: 'linear' }} /></div>
  </motion.div>}</AnimatePresence></>
}

export function PageHeader({ title, action }: { title: string; action?: ReactNode }) {
  return <header className="page-header"><h1>{title}</h1>{action}</header>
}
export function ErrorNotice({ error }: { error: unknown }) {
  return error ? <div className="error-notice" role="alert"><AlertCircle size={18} />{error instanceof Error ? error.message : '暂时无法加载'}</div> : null
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
