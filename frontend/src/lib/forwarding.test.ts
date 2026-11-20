import { afterEach, describe, expect, it, vi } from 'vitest'
import { t } from '@/i18n'
import {
  arrivalLine,
  overdueLine,
  problemLine,
  safeGmailLink,
  shortDate,
  storePassword,
  unlockWaiting,
  waitingReason,
} from './forwarding'

afterEach(() => vi.unstubAllGlobals())

describe('safeGmailLink', () => {
  it('offers only https links on Google mail settings hosts', () => {
    const good = 'https://mail-settings.google.com/mail/vf-%5Bmade-up%5D-x'
    expect(safeGmailLink(good)).toBe(good)
    expect(safeGmailLink('https://mail.google.com/mail/vf-x')).toBe('https://mail.google.com/mail/vf-x')
    expect(safeGmailLink('http://mail-settings.google.com/mail/vf-x')).toBeNull()
    expect(safeGmailLink('https://mail-settings.google.com.attacker.example/x')).toBeNull()
    expect(safeGmailLink('javascript:alert(1)')).toBeNull()
    expect(safeGmailLink('https://mail.google.com/mail/vf-x/../../evil')).toBeNull()
    expect(safeGmailLink('https://mail.google.com/mail/vf-%2e%2e/x')).toBeNull()
    expect(safeGmailLink('https://mail.google.com/mail/vf-%2Fx')).toBeNull()
    expect(safeGmailLink('https://mail.google.com/url?q=https://evil.example')).toBeNull()
    expect(safeGmailLink('https://mail.google.com:8443/mail/vf-x')).toBeNull()
    // Rebuilt: the query and fragment never come along.
    expect(safeGmailLink('https://mail.google.com/mail/vf-x?continue=https://evil.example#y')).toBe(
      'https://mail.google.com/mail/vf-x',
    )
    expect(safeGmailLink(null)).toBeNull()
  })
})

describe('lines', () => {
  it('describe arrivals, problems, late statements and waiting reasons from the catalog', () => {
    const arrival = { bank: 'bhd', kind: 'credit_card', identifier: '4242', month: '2026-01', at: '2026-02-03T10:00:00+00:00' }
    expect(arrivalLine(arrival)).toContain('BHD')
    expect(arrivalLine(arrival)).toContain('4242')
    expect(arrivalLine({ ...arrival, identifier: null })).toBe('BHD')
    expect(problemLine({ kind: 'statement', outcome: 'invalid', bank: 'popular', at: '' })).toBe(
      t('forwarding.problem.invalid', { bank: 'Popular' }),
    )
    expect(problemLine({ kind: 'statement', outcome: 'squared', bank: 'popular', at: '' })).toBeNull()
    expect(overdueLine({ bank: 'bhd', kind: 'savings', identifier: '9876', expected: '2026-03-01' })).toContain(
      shortDate('2026-03-01'),
    )
    const item = { id: 1, bank: 'bhd', state: 'password' as const, received_at: '2026-02-03' }
    expect(waitingReason({ ...item, state: 'approval', reason: 'new_account' })).toBe(
      t('forwarding.held.title'),
    )
    expect(waitingReason({ ...item, reason: 'missing' })).toBe(t('forwarding.waiting.missing'))
    expect(waitingReason({ ...item, reason: 'wrong' })).toBe(t('forwarding.waiting.wrong'))
    expect(waitingReason({ ...item, reason: '' })).toBe(t('forwarding.waiting.reading'))
  })
})

describe('calls', () => {
  it('sends passwords only in the body, never in the address', async () => {
    const calls: [string, RequestInit][] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        calls.push([url, init])
        return new Response(JSON.stringify({ opened: 0, left: 0 }), { status: 200 })
      }),
    )
    await unlockWaiting('bhd', 'made-up-secret')
    await storePassword('popular', 'made-up-secret')
    expect(calls.map(([url]) => url)).toEqual([
      '/api/forwarding/waiting/unlock',
      '/api/forwarding/passwords/popular',
    ])
    for (const [url, init] of calls) {
      expect(url).not.toContain('made-up-secret')
      expect(String(init.body)).toContain('made-up-secret')
      expect(new Headers(init.headers).get('X-Michelito')).toBe('1')
    }
  })
})
