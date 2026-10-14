import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'

const dateValue = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`

export default function DatePicker({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false)
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1))
  const [position, setPosition] = useState({ left: 0, top: 0 })
  const trigger = useRef<HTMLButtonElement>(null), popup = useRef<HTMLDivElement>(null)
  const today = dateValue(new Date())
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const box = trigger.current!.getBoundingClientRect()
      const height = popup.current?.offsetHeight ?? 350
      const width = popup.current?.offsetWidth ?? 296
      setPosition({ left: Math.max(12, Math.min(box.left, window.innerWidth - width - 12)),
        top: Math.max(12, box.bottom + height + 8 < window.innerHeight ? box.bottom + 8 : box.top - height - 8) })
    }
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true) }
  }, [open, month])
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => {
      if (!trigger.current?.contains(event.target as Node) && !popup.current?.contains(event.target as Node)) setOpen(false)
    }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() } }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    const focus = popup.current?.querySelector<HTMLButtonElement>('.calendar-selected')
      ?? popup.current?.querySelector<HTMLButtonElement>('.calendar-today')
      ?? popup.current?.querySelector<HTMLButtonElement>('.calendar-day')
    focus?.focus({ preventScroll: true })
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [open])
  const choose = (date: string) => { onChange(date); setOpen(false); trigger.current?.focus() }
  const offset = (month.getDay() + 6) % 7
  return <div className="date-picker"><span className="date-picker-label">{label}</span>
    <button ref={trigger} type="button" className={'date-picker-trigger ' + (!value ? 'date-empty' : '')} aria-label={label} aria-haspopup="dialog" aria-expanded={open}
      onClick={() => { if (!open) { const selected = value ? new Date(value + 'T12:00:00') : new Date(); setMonth(new Date(selected.getFullYear(), selected.getMonth(), 1)) } setOpen(!open) }}>
      <span>{value ? value.replaceAll('-', '/') : '选择日期'}</span><CalendarDays size={17} />
    </button>
    {createPortal(<AnimatePresence>{open && <motion.div ref={popup} className="calendar-popover" role="dialog" aria-label={label + '选择'}
      style={position} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .14 }}>
      <div className="calendar-header"><button type="button" className="icon-button" aria-label="上个月" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft size={18} /></button>
        <strong>{month.getFullYear()}年 {month.getMonth() + 1}月</strong><button type="button" className="icon-button" aria-label="下个月" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight size={18} /></button></div>
      <div className="calendar-grid"><div className="calendar-weekdays">{['一', '二', '三', '四', '五', '六', '日'].map(day => <span key={day}>{day}</span>)}</div>
        <div className="calendar-days">{Array.from({ length: 42 }, (_, i) => {
          const date = new Date(month.getFullYear(), month.getMonth(), i - offset + 1), key = dateValue(date)
          return <button key={key} type="button" aria-label={key} aria-pressed={key === value} className={'calendar-day ' + (date.getMonth() !== month.getMonth() ? 'calendar-other ' : '') + (key === today ? 'calendar-today ' : '') + (key === value ? 'calendar-selected' : '')} onClick={() => choose(key)}>{date.getDate()}</button>
        })}</div></div>
      <div className="calendar-footer"><button type="button" onClick={() => choose('')}>清除</button><button type="button" onClick={() => choose(today)}>今天</button></div>
    </motion.div>}</AnimatePresence>, document.body)}
  </div>
}
