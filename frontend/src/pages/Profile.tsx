import { useState } from 'react'
import { api, patch, post, time, type User } from '../api'
import { PageHeader, useApp } from '../ui'
import { validateContacts } from '../contacts'

export default function Profile({ force = false }: { force?: boolean }) {
  const { user, updateUser, notify } = useApp()
  const [busy, setBusy] = useState(false)
  return <><PageHeader title={force ? '确认你的密码' : '个人设置'} />
    <div className="profile-grid">{!force && <section className="panel"><h2>个人信息</h2><div className="profile-identity"><div className="profile-identity-heading"><strong>{user.student_id}</strong><span className={'status-pill ' + (user.admin ? 'info' : '')}>{user.admin ? '管理员' : '用户'}</span></div><dl className="profile-expiry"><dt>注册时间</dt><dd>{time(user.created_at)}</dd></dl></div>
      <form onSubmit={async e => { e.preventDefault(); setBusy(true); const form = new FormData(e.currentTarget); try { const changed = await patch<User>('/profile', validateContacts(String(form.get('email') ?? ''), String(form.get('phone') ?? ''))); updateUser({ ...user, ...changed }); notify('联系方式已保存') } catch (err) { notify(err as Error, true) } finally { setBusy(false) } }}>
        <label>邮箱<input type="email" name="email" autoComplete="email" defaultValue={user.email} maxLength={254} placeholder="选填" /></label><label>手机号<input type="tel" name="phone" autoComplete="tel" defaultValue={user.phone} maxLength={64} placeholder="选填" /></label><button className="button" disabled={busy}>保存联系方式</button>
      </form></section>}
      <section className="panel"><h2>{force ? '设置新密码' : '修改密码'}</h2><form onSubmit={async e => { e.preventDefault(); setBusy(true); const element = e.currentTarget; const form = new FormData(element); const password = String(form.get('new'))
        if (password !== form.get('confirm')) { notify('两次输入的新密码不一致', true); setBusy(false); return }
        try { const value = await post<User>('/auth/change-password', { ...(force ? {} : { current_password: form.get('current') }), new_password: password }); updateUser(value); element.reset(); notify('密码已更新'); void api<User>('/auth/me').then(updateUser).catch(err => notify(err as Error, true)) }
        catch (err) { notify(err as Error, true) } finally { setBusy(false) }
      }}>{!force && <label>当前密码<input type="password" name="current" autoComplete="current-password" required maxLength={128} /></label>}<label>新密码<input type="password" name="new" autoComplete="new-password" required minLength={4} maxLength={128} /></label><label>确认新密码<input type="password" name="confirm" autoComplete="new-password" required minLength={4} maxLength={128} /></label><button className="button button-primary" disabled={busy}>{busy ? '正在保存…' : '确认密码'}</button></form></section>
    </div></>
}
