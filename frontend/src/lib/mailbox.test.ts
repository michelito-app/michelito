import { afterEach, describe, expect, it, vi } from 'vitest'
import { t } from '@/i18n'
import {
  type MailboxStatus,
  OUTCOMES,
  disconnect,
  lastReadLine,
  mailboxView,
  outcomeIsGood,
  outcomeMessage,
  outcomeOf,
  safeConsentUrl,
  startConnect,
  syncNow,
  withoutOutcome,
} from './mailbox'

afterEach(() => vi.unstubAllGlobals())

const CONNECTED: MailboxStatus = {
  available: true,
  connected: true,
  address: 'alice.mailbox@example.com',
  connected_at: '2026-11-20T10:00:00+00:00',
  synced_at: '2026-11-21T09:05:00+00:00',
  problem: null,
  receipts: 2,
  syncing: false,
}

function answering(body: unknown, status = 200) {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

describe('mailboxView', () => {
  it('hides the section when the server does not offer it', () => {
    expect(mailboxView(undefined)).toBe('hidden')
    expect(mailboxView({ ...CONNECTED, available: false })).toBe('hidden')
  })

  it('tells apart not connected, connected and the two problems', () => {
    expect(mailboxView({ ...CONNECTED, connected: false })).toBe('disconnected')
    expect(mailboxView(CONNECTED)).toBe('connected')
    expect(mailboxView({ ...CONNECTED, problem: 'reconnect' })).toBe('reconnect')
    expect(mailboxView({ ...CONNECTED, problem: 'failed' })).toBe('failed')
  })
})

describe('the outcome in the address', () => {
  it('reads only the known outcomes', () => {
    expect(outcomeOf('?gmail=connected')).toBe('connected')
    expect(outcomeOf('?x=1&gmail=scope')).toBe('scope')
    expect(outcomeOf('?gmail=<script>')).toBeNull()
    expect(outcomeOf('')).toBeNull()
  })

  it('removes it and keeps the rest', () => {
    expect(withoutOutcome('?gmail=denied')).toBe('')
    expect(withoutOutcome('?a=1&gmail=denied&b=2')).toBe('?a=1&b=2')
    expect(withoutOutcome('')).toBe('')
  })

  it('has a message for every outcome, only "connected" being good news', () => {
    for (const outcome of OUTCOMES) expect(outcomeMessage(outcome)).toBe(t(`mailbox.outcome.${outcome}`))
    expect(OUTCOMES.filter(outcomeIsGood)).toEqual(['connected'])
  })
})

describe('lastReadLine', () => {
  it('says when it was read, that it is reading, or that it never was', () => {
    expect(lastReadLine(CONNECTED)).toContain(t('mailbox.lastRead', { date: '' }).trim())
    expect(lastReadLine({ ...CONNECTED, syncing: true })).toBe(t('mailbox.reading'))
    expect(lastReadLine({ ...CONNECTED, synced_at: null })).toBe(t('mailbox.neverRead'))
    expect(lastReadLine({ ...CONNECTED, synced_at: 'not a date' })).toBe(t('mailbox.neverRead'))
  })
})

describe('safeConsentUrl', () => {
  it('opens only Google consent page over https', () => {
    const good = 'https://accounts.google.com/o/oauth2/auth?client_id=x&state=y'
    expect(safeConsentUrl(good)).toBe(good)
    expect(safeConsentUrl('http://accounts.google.com/o/oauth2/auth')).toBeNull()
    expect(safeConsentUrl('https://accounts.google.com.attacker.example/auth')).toBeNull()
    expect(safeConsentUrl('https://accounts.google.com:8443/auth')).toBeNull()
    expect(safeConsentUrl('javascript:alert(1)')).toBeNull()
    expect(safeConsentUrl('/relative')).toBeNull()
  })
})

describe('calls', () => {
  it('starts with a write and returns only a Google address', async () => {
    const fetch = answering({ url: 'https://accounts.google.com/o/oauth2/auth?state=s' })

    await expect(startConnect()).resolves.toBe('https://accounts.google.com/o/oauth2/auth?state=s')

    const [path, init] = fetch.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/mailbox/google/start')
    expect(init.method).toBe('POST')
    expect(new Headers(init.headers).get('X-Michelito')).toBe('1')
  })

  it('refuses a consent address that is not Google', async () => {
    answering({ url: 'https://attacker.example/auth' })

    await expect(startConnect()).rejects.toThrow(t('mailbox.outcome.failed'))
  })

  it('disconnects with DELETE and reads now with POST', async () => {
    const fetch = answering({ ...CONNECTED, connected: false, revoked: true })

    await expect(disconnect()).resolves.toMatchObject({ connected: false, revoked: true })
    answering({ started: true }, 202)
    await syncNow()

    expect(fetch.mock.calls[0][0]).toBe('/api/mailbox')
    expect((fetch.mock.calls[0][1] as RequestInit).method).toBe('DELETE')
  })
})
