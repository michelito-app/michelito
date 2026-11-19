import { describe, expect, it } from 'vitest'
import { errorDetail, request } from './api'

function jsonResponse(body: unknown, status = 422): Response {
  return new Response(JSON.stringify(body), { status, statusText: 'Unprocessable Entity' })
}

describe('errorDetail', () => {
  it('uses FastAPI’s text detail', async () => {
    expect(await errorDetail(jsonResponse({ detail: 'unknown category: X' }))).toBe(
      'unknown category: X',
    )
  })

  it('joins the messages of a pydantic validation', async () => {
    const body = {
      detail: [
        { loc: ['body', 'scope'], msg: 'Input should be transaction or merchant', type: 'x' },
        { loc: ['body', 'one_off'], msg: 'Input should be a valid boolean', type: 'y' },
      ],
    }
    expect(await errorDetail(jsonResponse(body))).toBe(
      'Input should be transaction or merchant; Input should be a valid boolean',
    )
  })

  it('falls back to the status text if the detail is unusable or not JSON', async () => {
    expect(await errorDetail(jsonResponse({ detail: [{ nope: 1 }] }))).toBe('Unprocessable Entity')
    expect(await errorDetail(new Response('<html>', { status: 500 }))).toBe('error 500')
  })
})

describe('request', () => {
  it('a DELETE carries the header and a 204 returns undefined', async () => {
    const calls: { method?: string; headers: Headers }[] = []
    const original = globalThis.fetch
    globalThis.fetch = async (_path, init) => {
      calls.push({ method: init?.method, headers: new Headers(init?.headers) })
      return new Response(null, { status: 204 })
    }
    try {
      expect(await request<void>('/api/categories/7', { method: 'DELETE' })).toBeUndefined()
    } finally {
      globalThis.fetch = original
    }
    expect(calls[0].method).toBe('DELETE')
    expect(calls[0].headers.get('X-Michelito')).toBe('1')
  })
})
