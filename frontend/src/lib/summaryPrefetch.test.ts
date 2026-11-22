import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { paceOptions } from './homeQueries'
import { ONBOARDING_FRESH_MS, onboardingOptions } from './onboarding'
import { FRESH_MS, summaryOptions } from './queries'
import { prefetchSummary, summaryPrefetches } from './summaryPrefetch'

const AROUND = { older: '2026-01', newer: '2026-03' }

function paths(options: readonly { queryKey: readonly unknown[] }[]): string[] {
  return options.map((o) => o.queryKey.join('/'))
}

describe('summaryPrefetches', () => {
  it('asks for nothing without a month', () => {
    expect(summaryPrefetches(null, AROUND, null, true)).toEqual([])
  })

  it('asks for the month’s pace at once, next to the summary the screen already asks for', () => {
    expect(paths(summaryPrefetches('2026-02', AROUND, null, false))).toEqual([
      'summary/pace/2026-02/all',
    ])
  })

  it('adds the months around once this month’s summary is in', () => {
    expect(paths(summaryPrefetches('2026-02', AROUND, null, true))).toEqual([
      'summary/pace/2026-02/all',
      'summary/2026-01/all',
      'summary/pace/2026-01/all',
      'summary/2026-03/all',
      'summary/pace/2026-03/all',
    ])
  })

  it('skips the side that has no month', () => {
    const newest = { older: '2026-01', newer: null }
    expect(paths(summaryPrefetches('2026-02', newest, null, true))).toEqual([
      'summary/pace/2026-02/all',
      'summary/2026-01/all',
      'summary/pace/2026-01/all',
    ])
  })

  it('keeps the selected accounts', () => {
    const selection = ['card-1', 'bank-2']
    expect(paths(summaryPrefetches('2026-02', { older: null, newer: null }, selection, true))).toEqual(
      ['summary/pace/2026-02/card-1,bank-2'],
    )
  })
})

describe('with a query client', () => {
  let calls: string[]
  let client: QueryClient

  beforeEach(() => {
    calls = []
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        calls.push(path)
        return Promise.resolve(new Response(JSON.stringify({ path }), { status: 200 }))
      }),
    )
    vi.useFakeTimers({ toFake: ['Date'] })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    client.clear()
  })

  it('fetches the months around and the screen then uses them without asking again', async () => {
    await prefetchSummary(client, summaryPrefetches('2026-02', AROUND, null, true))
    expect(calls).toEqual([
      '/api/summary/pace?month=2026-02',
      '/api/summary?month=2026-01',
      '/api/summary/pace?month=2026-01',
      '/api/summary?month=2026-03',
      '/api/summary/pace?month=2026-03',
    ])

    await client.fetchQuery(summaryOptions('2026-01', null))
    await client.fetchQuery(paceOptions('2026-01', null))

    expect(calls).toHaveLength(5)
  })

  it('asks again once the answer is no longer fresh', async () => {
    await prefetchSummary(client, summaryPrefetches('2026-02', AROUND, null, true))
    vi.setSystemTime(Date.now() + FRESH_MS + 1)

    await client.fetchQuery(summaryOptions('2026-01', null))

    expect(calls.filter((path) => path === '/api/summary?month=2026-01')).toHaveLength(2)
  })

  it('does not fetch a month around again when it already has an answer, however old', async () => {
    await prefetchSummary(client, summaryPrefetches('2026-02', AROUND, null, true))
    vi.setSystemTime(Date.now() + 60 * FRESH_MS)
    calls.length = 0

    await prefetchSummary(client, summaryPrefetches('2026-02', AROUND, null, true))

    // Only this month's pace (the card is on screen); the screen refreshes a month around when
    // the person goes there.
    expect(calls).toEqual(['/api/summary/pace?month=2026-02'])
  })

  it('a failed prefetch stays quiet: the screen will ask and show the error itself', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('{"detail":"no"}', { status: 500 }))),
    )

    await expect(
      prefetchSummary(client, summaryPrefetches('2026-02', AROUND, null, false)),
    ).resolves.toBeUndefined()
  })

  it('stops when the month changed meanwhile', async () => {
    const controller = new AbortController()
    const wanted = summaryPrefetches('2026-02', AROUND, null, true)
    vi.stubGlobal(
      'fetch',
      vi.fn((path: string) => {
        calls.push(path)
        controller.abort()
        return Promise.resolve(new Response('{}', { status: 200 }))
      }),
    )

    await prefetchSummary(client, wanted, controller.signal)

    expect(calls).toEqual(['/api/summary/pace?month=2026-02'])
  })

  it('the onboarding state is asked once by the two parts of the screen that need it', async () => {
    await client.fetchQuery(onboardingOptions())
    await client.fetchQuery(onboardingOptions())

    expect(calls).toEqual(['/api/onboarding'])
  })

  it('and again a moment later: what was done on another screen shows on the checklist', async () => {
    await client.fetchQuery(onboardingOptions())
    vi.setSystemTime(Date.now() + ONBOARDING_FRESH_MS + 1)

    await client.fetchQuery(onboardingOptions())

    expect(calls).toEqual(['/api/onboarding', '/api/onboarding'])
    expect(ONBOARDING_FRESH_MS).toBeLessThan(FRESH_MS)
  })
})
