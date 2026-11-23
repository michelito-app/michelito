// The Amazon browser extension in hosted mode (src/michelito/hosted/extension_routes.py):
// Settings makes a one-time code, shows whether an extension is linked and revokes it. The
// extension's token never reaches the interface. Pure helpers apart from the calls.
import { useQuery } from '@tanstack/react-query'
import { LOCALE, t } from '@/i18n'
import { request } from '@/lib/api'

export const extensionKey = ['extension'] as const
export const DOWNLOAD_PATH = '/api/extension/download'

export interface ExtensionStatus {
  linked: boolean
  linked_at: string | null
  last_used_at: string | null
  orders: number // orders with item names
}

export interface ExtensionCode {
  code: string
  expires_at: string
}

const DAY = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
const TIME = new Intl.DateTimeFormat(LOCALE, { hour: 'numeric', minute: '2-digit' })

function when(value: string | null, format: Intl.DateTimeFormat): string | null {
  if (!value) return null
  const found = new Date(value)
  return Number.isNaN(found.getTime()) ? null : format.format(found)
}

/** "Linked on 20 nov., 11:00. Last sent: … · 42 orders with names." ('' when not linked). */
export function linkedLine(status: ExtensionStatus): string {
  if (!status.linked) return ''
  const linked = t('extension.linkedOn', { date: when(status.linked_at, DAY) ?? '' })
  const used = when(status.last_used_at, DAY)
  if (!used) return `${linked} ${t('extension.neverUsed')}`
  const orders = t('extension.orders', { count: status.orders })
  return `${linked} ${t('extension.lastUsed', { date: used, orders })}`
}

/** "Expires at 11:10." (local time), or '' for a time that cannot be read. */
export function codeExpiry(expiresAt: string): string {
  const found = when(expiresAt, TIME)
  return found ? t('extension.expires', { time: found }) : ''
}

export function useExtension() {
  return useQuery({ queryKey: extensionKey, queryFn: fetchExtension })
}

export function fetchExtension(): Promise<ExtensionStatus> {
  return request<ExtensionStatus>('/api/extension')
}

export function makeCode(): Promise<ExtensionCode> {
  return request<ExtensionCode>('/api/extension/code', { method: 'POST' })
}

export function revoke(): Promise<ExtensionStatus> {
  return request<ExtensionStatus>('/api/extension', { method: 'DELETE' })
}
