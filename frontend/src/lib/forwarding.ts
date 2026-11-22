// Email forwarding in hosted mode (src/michelito/hosted/forwarding_routes.py): the address, Gmail's
// confirmation (shown, never confirmed here), the waiting statements, the quarantine and the
// stored PDF passwords (only "stored: yes/no" ever comes back). Pure helpers apart from calls.
import { useQuery } from '@tanstack/react-query'
import { LOCALE, t } from '@/i18n'
import { request } from '@/lib/api'
import { monthPhrase } from '@/lib/months'
import { SUPPORTED_BANKS, type SupportedBank, accountMask, bankName } from '@/lib/onboarding'

export const forwardingKey = ['forwarding'] as const
export const UNLOCK_BANKS = [...SUPPORTED_BANKS, 'other'] as const
export type UnlockBank = (typeof UNLOCK_BANKS)[number]
/** The banks' statement and alert senders (the server's `config.DEFAULT_SOURCES`), for the
 * Gmail filter. */
export const BANK_SENDERS = [
  'estados@popularenlinea.com', // spanish-data
  'notificaciones@popularenlinea.com',
  'servicios@bhd.com.do',
] as const
/** The merchants' receipt senders (the server's `michelito.receipts`): an optional second
 * Gmail filter, for the detail of each purchase. */
export const RECEIPT_SENDERS = ['auto-confirm@amazon.com', 'shipment-tracking@amazon.com'] as const

export interface Confirmation {
  code: string | null
  link: string | null
  requester: string | null // the Gmail address that asked to forward here
  received_at: string
}

export interface WaitingStatement {
  id: number
  bank: string
  state: 'queued' | 'password' | 'approval'
  reason: '' | 'missing' | 'wrong' | 'new_account'
  received_at: string
}

export interface Quarantined {
  id: number
  sender_domain: string
  received_at: string
  attachments: number
  reason: 'unknown_sender' | 'unauthenticated' | 'unknown_card'
  claims_bank: boolean // it says it comes from a bank: approving it shows a warning
}

export interface Approval {
  id: number
  kind: 'statement' | 'alert'
  sender_domain: string
  approved_at: string
}

export interface Arrival {
  bank: string | null
  kind: string | null
  identifier: string | null
  month: string | null
  at: string
}

export interface Problem {
  kind: string
  outcome: string
  bank: string | null
  at: string
}

export interface Overdue {
  bank: string
  kind: string
  identifier: string
  expected: string
}

export interface Forwarding {
  address: string | null
  created: boolean
  confirmation: Confirmation | null
  waiting: WaitingStatement[]
  quarantine: Quarantined[]
  passwords: Record<SupportedBank, boolean>
  approvals: Approval[]
  arrivals: Arrival[]
  problems: Problem[]
  overdue: Overdue[]
}

export interface Unlocked {
  opened: number
  left: number
}

const DAY = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short', timeZone: 'UTC' })

/** "14 feb." from an ISO date or timestamp (the day as the server wrote it). */
export function shortDate(value: string): string {
  const day = value.slice(0, 10)
  return DAY.format(new Date(`${day}T00:00:00Z`))
}

/** Only an https link on Google's mail settings hosts is ever offered as a link. */
const LINK_HOSTS = new Set(['mail-settings.google.com', 'mail.google.com'])
const LINK_PATH = /^\/mail\/vf-[A-Za-z0-9_-]*(?:%5[BbDd][A-Za-z0-9_-]*)*$/

/** Only Gmail's confirmation link, rebuilt from its allowlisted shape (the server does the
 * same): https, a Google mail host, `/mail/vf-…`, no query, no fragment, no `..`, no encoded
 * dot or slash, no redirector. Anything else is not offered as a link. */
export function safeGmailLink(link: string | null): string | null {
  if (!link) return null
  let url: URL
  try {
    url = new URL(link)
  } catch {
    return null
  }
  const raw = link.slice(link.indexOf(url.host) + url.host.length).split(/[?#]/)[0]
  const lowered = raw.toLowerCase()
  if (url.protocol !== 'https:' || !LINK_HOSTS.has(url.hostname) || url.port) return null
  if (raw.includes('..') || lowered.includes('%2e') || lowered.includes('%2f')) return null
  if (lowered.startsWith('/url') || !LINK_PATH.test(raw)) return null
  return `https://${url.hostname}${raw}`
}

export function waitingReason(item: WaitingStatement): string {
  if (item.reason === 'wrong') return t('forwarding.waiting.wrong')
  if (item.reason === 'missing') return t('forwarding.waiting.missing')
  if (item.reason === 'new_account') return t('forwarding.held.title')
  return t('forwarding.waiting.reading')
}

/** One arrival of the statements card: bank · account · month (card or account unknown:
 * only the bank). */
export function arrivalLine(arrival: Arrival): string {
  const bank = bankName(arrival.bank ?? 'other')
  if (!arrival.identifier || !arrival.month) return bank
  return t('forwarding.card.arrival', {
    bank,
    account: accountMask(arrival.kind ?? '', arrival.identifier),
    month: monthPhrase(arrival.month),
  })
}

const PROBLEM_KEYS = {
  invalid: 'forwarding.problem.invalid',
  unsupported: 'forwarding.problem.unsupported',
  unreadable: 'forwarding.problem.unreadable',
  too_complex: 'forwarding.problem.too_complex',
  full: 'forwarding.problem.full',
  failed: 'forwarding.problem.failed',
  password_wrong: 'forwarding.problem.password_wrong',
} as const

/** A problem in words (null for an outcome that is not one). */
export function problemLine(problem: Problem): string | null {
  const key = PROBLEM_KEYS[problem.outcome as keyof typeof PROBLEM_KEYS]
  if (!key) return null
  return t(key, { bank: bankName(problem.bank ?? 'other') })
}

export function overdueLine(item: Overdue): string {
  return t('forwarding.card.overdue', {
    bank: bankName(item.bank),
    account: accountMask(item.kind, item.identifier),
    date: shortDate(item.expected),
  })
}

export function useForwarding(enabled = true) {
  return useQuery({
    queryKey: forwardingKey,
    queryFn: () => request<Forwarding>('/api/forwarding'),
    enabled,
  })
}

export function createAddress(): Promise<Forwarding> {
  return request<Forwarding>('/api/forwarding/address', { method: 'POST' })
}

export function rotateAddress(): Promise<Forwarding> {
  return request<Forwarding>('/api/forwarding/address/rotate', { method: 'POST' })
}

export async function dismissConfirmation(): Promise<void> {
  await request('/api/forwarding/confirmation/dismiss', { method: 'POST' })
}

/** The password goes only in the POST body; nothing keeps it after the call. */
export function unlockWaiting(bank: UnlockBank, password: string): Promise<Unlocked> {
  return request<Unlocked>('/api/forwarding/waiting/unlock', {
    method: 'POST',
    body: JSON.stringify({ bank, password }),
  })
}

const CONFIRMED = JSON.stringify({ confirmed: true })

/** Only after the person confirmed (the interface asks first; the server refuses otherwise). */
export function approveQuarantined(id: number): Promise<Forwarding> {
  return request<Forwarding>(`/api/forwarding/quarantine/${id}/approve`, {
    method: 'POST',
    body: CONFIRMED,
  })
}

export function approveHeld(id: number): Promise<Forwarding> {
  return request<Forwarding>(`/api/forwarding/waiting/${id}/approve`, {
    method: 'POST',
    body: CONFIRMED,
  })
}

export async function discardHeld(id: number): Promise<void> {
  await request(`/api/forwarding/waiting/${id}`, { method: 'DELETE' })
}

export function undoApproval(id: number): Promise<Forwarding> {
  return request<Forwarding>(`/api/forwarding/approvals/${id}/undo`, { method: 'POST' })
}

export async function discardQuarantined(id: number): Promise<void> {
  await request(`/api/forwarding/quarantine/${id}`, { method: 'DELETE' })
}

export function storePassword(bank: SupportedBank, password: string): Promise<Unlocked> {
  return request<Unlocked>(`/api/forwarding/passwords/${bank}`, {
    method: 'PUT',
    body: JSON.stringify({ password }),
  })
}

export async function forgetPassword(bank: SupportedBank): Promise<void> {
  await request(`/api/forwarding/passwords/${bank}`, { method: 'DELETE' })
}
