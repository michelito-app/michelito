// Gmail connected read-only in hosted mode (src/michelito/hosted/mailbox_routes.py): only the
// merchants' receipt senders are read. The token never reaches the interface: only whether the
// mailbox is connected, its address and how the last read went. Pure helpers apart from calls.
import { useQuery } from '@tanstack/react-query'
import { LOCALE, t } from '@/i18n'
import { request } from '@/lib/api'

export const mailboxKey = ['mailbox'] as const
/** The query parameter Google's callback leaves on Settings (`/settings?gmail=…#mailbox`). */
export const OUTCOME_PARAM = 'gmail'
export const SYNC_POLL_MS = 3000
const GOOGLE_CONSENT_HOST = 'accounts.google.com'

export interface MailboxStatus {
  available: boolean
  connected: boolean
  address: string | null
  connected_at: string | null
  synced_at: string | null
  problem: 'reconnect' | 'failed' | null
  receipts: number
  syncing: boolean
  revoked?: boolean | null // only after disconnecting: whether Google confirmed it
}

export const OUTCOMES = ['connected', 'denied', 'scope', 'failed', 'expired'] as const
export type Outcome = (typeof OUTCOMES)[number]

/** What Settings shows. */
export type MailboxView = 'hidden' | 'disconnected' | 'connected' | 'reconnect' | 'failed'

export function mailboxView(status: MailboxStatus | undefined): MailboxView {
  if (!status?.available) return 'hidden'
  if (!status.connected) return 'disconnected'
  if (status.problem === 'reconnect') return 'reconnect'
  if (status.problem === 'failed') return 'failed'
  return 'connected'
}

/** The outcome in a search string (`?gmail=connected`), or null for none or an unknown one. */
export function outcomeOf(search: string): Outcome | null {
  const found = new URLSearchParams(search).get(OUTCOME_PARAM)
  return OUTCOMES.find((outcome) => outcome === found) ?? null
}

/** The search string without the outcome (other parameters kept), with its `?` or empty. */
export function withoutOutcome(search: string): string {
  const params = new URLSearchParams(search)
  params.delete(OUTCOME_PARAM)
  const rest = params.toString()
  return rest ? `?${rest}` : ''
}

export function outcomeMessage(outcome: Outcome): string {
  return t(`mailbox.outcome.${outcome}`)
}

/** Whether the outcome is good news (shown as a status) or not (shown as an alert). */
export function outcomeIsGood(outcome: Outcome): boolean {
  return outcome === 'connected'
}

const DAY = new Intl.DateTimeFormat(LOCALE, {
  day: 'numeric',
  month: 'short',
  hour: 'numeric',
  minute: '2-digit',
})

/** "Last read: 14 feb., 9:05" (local time), or that it was never read. */
export function lastReadLine(status: MailboxStatus): string {
  if (status.syncing) return t('mailbox.reading')
  if (!status.synced_at) return t('mailbox.neverRead')
  const when = new Date(status.synced_at)
  if (Number.isNaN(when.getTime())) return t('mailbox.neverRead')
  return t('mailbox.lastRead', { date: DAY.format(when) })
}

/** Only Google's own consent page is ever opened (the server builds it; this checks it). */
export function safeConsentUrl(url: string): string | null {
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'https:' || parsed.hostname !== GOOGLE_CONSENT_HOST || parsed.port) {
      return null
    }
    return parsed.toString()
  } catch {
    return null
  }
}

export function useMailbox() {
  return useQuery({
    queryKey: mailboxKey,
    queryFn: fetchMailbox,
    refetchInterval: (query) => (query.state.data?.syncing ? SYNC_POLL_MS : false),
  })
}

export function fetchMailbox(): Promise<MailboxStatus> {
  return request<MailboxStatus>('/api/mailbox')
}

/** Google's consent page for this session (single use, 10 minutes). */
export async function startConnect(): Promise<string> {
  const found = await request<{ url: string }>('/api/mailbox/google/start', { method: 'POST' })
  const url = safeConsentUrl(found.url)
  if (!url) throw new Error(t('mailbox.outcome.failed'))
  return url
}

export function disconnect(): Promise<MailboxStatus> {
  return request<MailboxStatus>('/api/mailbox', { method: 'DELETE' })
}

export async function syncNow(): Promise<void> {
  await request('/api/mailbox/sync', { method: 'POST' })
}
