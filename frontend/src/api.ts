export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message) }
}

let csrf = ''
export const setCsrf = (token: string) => { csrf = token }
let refreshingSession: Promise<void> | null = null

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  return request<T>(path, options, true)
}

async function request<T>(path: string, options: RequestInit, retryCsrf: boolean): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf)
  const response = await fetch('/api' + path, { ...options, headers, credentials: 'same-origin' })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 403 && body.code === 'csrf_rejected' && retryCsrf && !options.signal?.aborted) {
      if (!refreshingSession) {
        refreshingSession = request<User>('/auth/me', {}, false).then(user => {
          setCsrf(user.csrf_token)
          window.dispatchEvent(new CustomEvent('session-refreshed', { detail: user }))
        }).catch(error => {
          if (error instanceof ApiError && error.status === 401) window.dispatchEvent(new Event('session-expired'))
          throw error
        }).finally(() => { refreshingSession = null })
      }
      await refreshingSession
      return request<T>(path, options, false)
    }
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') {
      window.dispatchEvent(new Event('session-expired'))
    }
    throw new ApiError(body.code ?? 'network_error', body.message ?? '请求失败，请稍后重试', response.status)
  }
  return body as T
}

export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })

export interface Branding { platform_name: string; organization_name: string; identity_label: string; logo_url: string; icon_url: string }
export interface User {
  id: string; student_id: string; admin: boolean; must_change_password: boolean;
  email: string; phone: string; expires_at: string; created_at: string; csrf_token: string;
  admin_contact?: { email: string; phone: string }
}
export interface PrintFile { id: string; filename: string; status: string; page_count: number | null; error_code?: string }
export interface Plan { id: string; document_id: string; status: string; page_numbers: number[]; orientation: string; scaling: string; error_code?: string }
export interface QueueItem {
  id: string; student_id: string; state: string; total_pages: number; created_at: string;
  filename?: string; plan_id?: string; mine: boolean; can_cancel: boolean; can_download: boolean;
}
export interface QueueData {
  admin_contact?: { email: string; phone: string } | null;
  items: QueueItem[]; has_more: boolean; paused: boolean;
  device: { available: boolean; blocked: boolean; message: string; toner?: string }
}
export const time = (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
