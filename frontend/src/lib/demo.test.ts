import { afterEach, describe, expect, it, vi } from 'vitest'
import { t } from '@/i18n'
import {
  LOCAL,
  countVisit,
  fetchMode,
  opinionBody,
  opinionProblem,
  productName,
  refFrom,
} from '@/lib/demo'

describe('productName', () => {
  it("uses the demo's name only in the demo", () => {
    expect(productName(LOCAL)).toBe('Michelito')
    expect(productName({ mode: 'demo', session: true, name: 'Demo' })).toBe('Demo')
  })
})

describe('refFrom', () => {
  it('accepts a short, clean ref', () => {
    expect(refFrom('?ref=forum-1')).toBe('forum-1')
    expect(refFrom('?month=2026-01&ref=a.b_c')).toBe('a.b_c')
  })
  it('ignores a missing or odd one', () => {
    expect(refFrom('')).toBeNull()
    expect(refFrom('?ref=<script>')).toBeNull()
    expect(refFrom(`?ref=${'x'.repeat(65)}`)).toBeNull()
  })
})

describe('opinionProblem', () => {
  it('asks for text and an email shaped like one', () => {
    expect(opinionProblem('  ', '')).toBe(t('demo.opinion.empty'))
    expect(opinionProblem('hello', 'no')).toBe(t('demo.opinion.badEmail'))
    expect(opinionProblem('x'.repeat(2001), '')).toBe(t('demo.opinion.tooLong', { max: '2,000' }))
    expect(opinionProblem('x'.repeat(2001), '')).toBe('Máximo 2,000 letras.') // spanish-ui
    expect(opinionProblem('hello', '')).toBeNull()
    expect(opinionProblem('hello', 'a@example.com')).toBeNull()
  })
})

describe('opinionBody', () => {
  it('adds the context and leaves an empty email as null', () => {
    const body = opinionBody(' good ', ' ', { path: '/', width: 390.4, ref: null })
    expect(body).toEqual({
      text: 'good',
      email: null,
      page: '/',
      width: 390,
      version: null,
      ref: null,
    })
  })
})

describe('fetchMode', () => {
  const answer = (status: number, body: unknown) =>
    vi.fn(async () => new Response(JSON.stringify(body), { status }))

  afterEach(() => vi.unstubAllGlobals())

  it('a server without /api/mode (404) is local', async () => {
    vi.stubGlobal('fetch', answer(404, { detail: 'not found' }))
    expect(await fetchMode()).toEqual(LOCAL)
  })

  it('another error is not disguised as local', async () => {
    vi.stubGlobal('fetch', answer(503, { detail: 'the demo is full' }))
    await expect(fetchMode()).rejects.toThrow('the demo is full')
  })
})

describe('countVisit', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends the SPA route as the screen key the usage counter expects', () => {
    const fetch = vi.fn(() => Promise.resolve(new Response('{}', { status: 200 })))
    vi.stubGlobal('fetch', fetch)
    countVisit('/transactions')
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/usage')
    expect(JSON.parse(init.body as string)).toEqual({ screen: '/transactions' })
  })
})
