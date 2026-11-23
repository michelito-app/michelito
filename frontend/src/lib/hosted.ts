// Hosted mode (src/michelito/hosted/routes.py): sign-in by email code, devices and step-up. The
// pure logic is kept apart from the calls. The session lives in an HttpOnly cookie: this code
// never sees its token, and it never stores the code anywhere.
import { t } from '@/i18n'
import { ApiError, request } from '@/lib/api'

export const CODE_LENGTH = 6
/** Seconds before "resend the code" is offered again. */
export const RESEND_COOLDOWN = 60
const EMAIL = /^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$/
const CODE = /^\d{6}$/
const LINK = /^#link=([A-Za-z0-9_-]{20,128})$/

export interface Device {
  id: number
  browser: string
  os: string
  last_seen: string // YYYY-MM-DD
  created: string
  current: boolean
}

export interface Me {
  email: string
  step_up_fresh: boolean
}

export function validEmail(email: string): boolean {
  const value = email.trim()
  return value.length <= 254 && EMAIL.test(value)
}

/** Only the digits the person typed (a pasted "123 456" too), at most six. */
export function cleanCode(text: string): string {
  return text.replace(/\D/g, '').slice(0, CODE_LENGTH)
}

export function validCode(code: string): boolean {
  return CODE.test(code)
}

/** Whole seconds left before resending is allowed (0: now). */
export function cooldownLeft(sentAt: number, now: number, cooldown = RESEND_COOLDOWN): number {
  return Math.max(0, Math.ceil(cooldown - (now - sentAt) / 1000))
}

/** The desktop link's token in the URL fragment (`#link=…`), if it has the right shape. */
export function linkToken(hash: string): string | null {
  return LINK.exec(hash)?.[1] ?? null
}

/** "Chrome en Android", naming what is unknown. */
export function deviceLabel(device: Pick<Device, 'browser' | 'os'>): string {
  return t('auth.devices.label', {
    browser: device.browser || t('auth.devices.unknownBrowser'),
    os: device.os || t('auth.devices.unknownOs'),
  })
}

const STEP_UP_REQUIRED = 'step_up_required'

/** The step-up was demanded: a 403 whose reason is exactly `step_up_required` (any other 403,
 * e.g. a missing header, is just an error). */
export function needsStepUp(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.code === STEP_UP_REQUIRED
}

/** Takes the desktop link out of the address at once, in every mode and whether or not someone
 * is signed in (it must not stay in the history), and returns its token if well formed. */
export function takeLinkToken(): string | null {
  const { hash, pathname, search } = window.location
  if (!hash.startsWith('#link=')) return null
  window.history.replaceState(window.history.state, '', pathname + search)
  return linkToken(hash)
}

export async function requestCode(email: string): Promise<void> {
  await request('/api/auth/code', { method: 'POST', body: JSON.stringify({ email: email.trim() }) })
}

export async function verifyCode(email: string, code: string): Promise<void> {
  await request('/api/auth/verify', {
    method: 'POST',
    body: JSON.stringify({ email: email.trim(), code }),
  })
}

/** The masked email a link is for, without using it. */
export async function peekLink(token: string): Promise<string> {
  const found = await request<{ email: string }>('/api/auth/link/peek', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
  return found.email
}

export async function verifyLink(token: string): Promise<void> {
  await request('/api/auth/link', { method: 'POST', body: JSON.stringify({ token }) })
}

export function fetchMe(): Promise<Me> {
  return request<Me>('/api/auth/me')
}

export function fetchDevices(): Promise<Device[]> {
  return request<Device[]>('/api/auth/devices')
}

export async function signOut(): Promise<void> {
  await request('/api/auth/sign-out', { method: 'POST' })
}

export async function signOutEverywhere(): Promise<void> {
  await request('/api/auth/sign-out-everywhere', { method: 'POST' })
}

export async function requestStepUp(): Promise<void> {
  await request('/api/auth/step-up/code', { method: 'POST' })
}

export async function verifyStepUp(code: string): Promise<void> {
  await request('/api/auth/step-up/verify', { method: 'POST', body: JSON.stringify({ code }) })
}

/** Deleting the account is confirmed by typing its email: the same address, whatever the case
 * (a phone keyboard may capitalize the first letter) and without surrounding spaces. */
export function confirmsEmail(typed: string, email: string): boolean {
  const value = typed.trim().toLowerCase()
  return value !== '' && value === email.trim().toLowerCase()
}

/** `DELETE /api/account`: the account's key is destroyed at once, its Gmail grant revoked and
 * every session ended. Needs a fresh verification (a 403 `step_up_required` otherwise). */
export async function deleteAccount(): Promise<void> {
  await request('/api/account', { method: 'DELETE' })
}

/** Where the "your account was deleted" notice waits for the signed-out page (this tab only). */
export type NoticeStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
const DELETED_KEY = 'michelito:account-deleted'

function sessionStore(): NoticeStorage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

/** Leaves the notice for the signed-out page; without storage it is simply not shown. */
export function rememberAccountDeleted(storage: NoticeStorage | null = sessionStore()): void {
  try {
    storage?.setItem(DELETED_KEY, '1')
  } catch {
    // Storage blocked (private window, previews): the notice is a convenience, the deletion
    // already happened.
  }
}

/** Whether the notice is waiting (reading only: safe during render). */
export function accountDeleted(storage: NoticeStorage | null = sessionStore()): boolean {
  try {
    return storage?.getItem(DELETED_KEY) === '1'
  } catch {
    return false
  }
}

/** Takes the notice away once shown (it shows once). */
export function forgetAccountDeleted(storage: NoticeStorage | null = sessionStore()): void {
  try {
    storage?.removeItem(DELETED_KEY)
  } catch {
    // Storage blocked: there was no notice to take away.
  }
}
