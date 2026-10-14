import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion, MotionConfig } from 'motion/react'
import { LogOut, Printer, Settings2, UserRound, UsersRound } from 'lucide-react'
import { SubmitPrintIcon, TaskQueueIcon } from './NavigationIcons'
import { api, post, setCsrf, type Branding, type User } from './api'
import { AppContext, ErrorNotification, NotificationProvider, useNotify } from './ui'
import Submit from './pages/Submit'
import Queue from './pages/Queue'
import Profile from './pages/Profile'
import Members from './pages/Members'
import System from './pages/System'

export default function App() {
  return <MotionConfig reducedMotion="user"><NotificationProvider>{() => <PlatformApp />}</NotificationProvider></MotionConfig>
}

function PlatformApp() {
  const notify = useNotify()
  const client = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const [user, setUser] = useState<User | null>(null)
  const [booting, setBooting] = useState(true)
  const branding = useQuery({ queryKey: ['branding'], queryFn: () => api<Branding>('/public/branding'), staleTime: Infinity })
  const setup = useQuery({ queryKey: ['setup'], queryFn: () => api<{ initialized: boolean }>('/setup/status') })
  const updateUser = (value: User) => { setCsrf(value.csrf_token); setUser(value) }
  useEffect(() => {
    let active = true
    api<User>('/auth/me').then(value => { if (active) updateUser(value) }).catch(() => {}).finally(() => { if (active) setBooting(false) })
    return () => { active = false }
  }, [])
  useEffect(() => {
    const expired = () => { setUser(null); setCsrf(''); client.clear() }
    const refreshed = (event: Event) => updateUser((event as CustomEvent<User>).detail)
    window.addEventListener('session-expired', expired)
    window.addEventListener('session-refreshed', refreshed)
    return () => {
      window.removeEventListener('session-expired', expired)
      window.removeEventListener('session-refreshed', refreshed)
    }
  }, [client])
  useEffect(() => { document.title = branding.data?.platform_name ?? '打印平台' }, [branding.data])
  useEffect(() => {
    if (!branding.data) return
    let icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
    if (!icon) { icon = document.createElement('link'); icon.rel = 'icon'; document.head.append(icon) }
    icon.href = branding.data.icon_url
  }, [branding.data])
  if (branding.isPending || booting || setup.isPending) return <div className="boot"><Printer size={32} /><p>正在连接打印平台…</p></div>
  if (!branding.data || !setup.data) return <div className="boot"><ErrorNotification error={branding.error ?? setup.error} /><button className="button" onClick={() => { void branding.refetch(); void setup.refetch() }}>重新连接</button></div>
  const brand = branding.data
  if (!user) return <Access branding={brand} initialized={setup.data.initialized} onLogin={value => { updateUser(value); navigate('/submit') }} onSetup={() => void setup.refetch()} />
  return <AppContext.Provider value={{ branding: brand, user, updateUser, notify }}>
    {user.must_change_password ? <div className="password-gate"><Profile force /></div> : <div className="app-shell">
      <aside className="sidebar"><div className="brand"><img className="brand-logo" src={brand.logo_url} alt={brand.organization_name} /><strong>{brand.platform_name}</strong></div>
        <nav>
          <NavLink draggable={false} to="/submit"><SubmitPrintIcon />提交打印</NavLink>
          <NavLink draggable={false} to="/queue"><TaskQueueIcon />任务队列</NavLink>
          <NavLink draggable={false} to="/profile"><UserRound size={19} />个人设置</NavLink>
        </nav>{user.admin && <nav className="admin-nav"><NavLink draggable={false} to="/members"><UsersRound size={19} />用户管理</NavLink><NavLink draggable={false} to="/system"><Settings2 size={19} />系统管理</NavLink></nav>}
        <div className="account"><div><strong>{user.student_id}</strong><small>{user.admin ? '管理员' : '用户'}</small></div><button title="退出登录" aria-label="退出登录" onClick={async () => { try { await post('/auth/logout'); setUser(null); setCsrf(''); client.clear(); navigate('/') } catch (e) { notify(e as Error, true) } }}><LogOut size={18} /></button></div>
      </aside><main className={'main-panel' + (location.pathname === '/submit' ? ' submit-panel' : '')}><AnimatePresence mode="wait" initial={false}><motion.div key={location.pathname} className="route-frame" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: .18 }}>
        <Routes location={location}><Route path="/submit" element={<Submit />} /><Route path="/queue" element={<Queue />} /><Route path="/profile" element={<Profile />} />
          <Route path="/members" element={user.admin ? <Members /> : <Navigate to="/submit" />} /><Route path="/system" element={user.admin ? <System /> : <Navigate to="/submit" />} /><Route path="*" element={<Navigate to="/submit" replace />} /></Routes>
        </motion.div></AnimatePresence>
        <button className="mobile-logout button button-small" onClick={async () => { try { await post('/auth/logout'); setUser(null); setCsrf(''); client.clear() } catch (e) { notify(e as Error, true) } }}>退出登录</button>
      </main></div>}
  </AppContext.Provider>
}

function Access({ branding, initialized, onLogin, onSetup }: { branding: Branding; initialized: boolean; onLogin: (user: User) => void; onSetup: () => void }) {
  const notify = useNotify()
  const [busy, setBusy] = useState(false)
  return <div className="access"><section className="access-form"><div><img className="access-logo" src={branding.logo_url} alt={branding.organization_name} /><h2>{branding.platform_name}</h2>
      <form onSubmit={async e => { e.preventDefault(); setBusy(true); const data = new FormData(e.currentTarget)
        try { if (initialized) onLogin(await post<User>('/auth/login', { student_id: data.get('identity'), password: data.get('password') }))
          else { await post('/setup', { student_id: data.get('identity'), setup_token: data.get('token') }); onSetup() } }
        catch (err) { notify(err as Error, true) } finally { setBusy(false) }
      }}><label>{initialized ? '' : '首任管理员'}{branding.identity_label}<input name="identity" required maxLength={64} autoComplete="username" placeholder={'请输入' + branding.identity_label} /></label>
        {initialized ? <label>密码<input name="password" type="password" required maxLength={128} autoComplete="current-password" placeholder="请输入密码" /></label> : <label>初始化凭证<input name="token" type="password" required autoComplete="off" placeholder="部署时设置的一次性凭证" /></label>}
        <button className="button button-primary" disabled={busy}>{busy ? '请稍候…' : initialized ? '登录' : '创建管理员'}</button>
      </form>
    </div></section></div>
}
