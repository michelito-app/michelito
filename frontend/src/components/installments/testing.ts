// Test helpers for the installment components (jsdom): render with a query cache already
// filled, and drive inputs the way React listens to them. Only imported by *.test.ts files.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, createElement, type ReactElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { vi } from 'vitest'
import type { InstallmentDraft, InstallmentPlan } from '@/lib/api'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

export interface Rendered {
  container: HTMLElement
  client: QueryClient
  unmount: () => void
}

/** jsdom has no modal dialogs: opening one only sets `open`. */
function stubDialogs(): void {
  const proto = HTMLDialogElement.prototype
  proto.showModal ??= function showModal(this: HTMLDialogElement) {
    this.setAttribute('open', '')
  }
  proto.close ??= function close(this: HTMLDialogElement) {
    this.removeAttribute('open')
  }
}

/** Renders `element` with `data` in the cache (never refetched: nothing is stale). */
export function render(element: ReactElement, data: [readonly unknown[], unknown][]): Rendered {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  stubDialogs()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  for (const [key, value] of data) client.setQueryData(key, value)
  const container = document.createElement('div')
  document.body.append(container)
  let root: Root | null = null
  act(() => {
    root = createRoot(container)
    root.render(createElement(QueryClientProvider, { client }, element))
  })
  return {
    container,
    client,
    unmount: () => {
      act(() => root?.unmount())
      container.remove()
    },
  }
}

/** Every write answers `answer`; reads fail (what is shown is already in the cache, and the
 * refetch after a write must end for the write's callbacks to run). */
export function stubWrites(answer: unknown) {
  const fetch = vi.fn((_path: string, init?: RequestInit) => {
    if ((init?.method ?? 'GET') === 'GET') return Promise.reject(new Error('no reads in tests'))
    return Promise.resolve({
      ok: true,
      status: 201,
      headers: new Headers(),
      json: () => Promise.resolve(answer),
    })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

/** The JSON body of the first write `fetch` received. */
export function sentBody(fetch: ReturnType<typeof stubWrites>): unknown {
  const call = fetch.mock.calls.find(([, init]) => (init?.method ?? 'GET') !== 'GET')
  return call ? JSON.parse(String(call[1]?.body)) : null
}

export async function flush(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

export function click(element: Element | null): void {
  if (!(element instanceof HTMLElement)) throw new Error('nothing to click')
  act(() => element.click())
}

/** Types `value` into an input or picks it in a select, as the browser would. */
export function fill(element: Element | null, value: string): void {
  if (!(element instanceof HTMLInputElement || element instanceof HTMLSelectElement)) {
    throw new Error('not a field')
  }
  const proto = Object.getPrototypeOf(element) as object
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  act(() => {
    setter?.call(element, value)
    element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
  })
}

/** The field whose label starts with `label`. */
export function field(container: HTMLElement, label: string): HTMLInputElement | HTMLSelectElement | null {
  const found = [...container.querySelectorAll('label')].find((item) =>
    item.textContent?.trim().startsWith(label),
  )
  return found?.querySelector('input, select') ?? null
}

export function button(container: HTMLElement, text: string): HTMLButtonElement | null {
  return (
    [...container.querySelectorAll('button')].find((item) => item.textContent?.trim() === text) ??
    null
  )
}

export function draftOf(over: Partial<InstallmentDraft> = {}): InstallmentDraft {
  return {
    fingerprint: 'fp-feb',
    name: 'TEST STORE',
    account_label: 'VISA ···0000',
    amount_cents: 15_000,
    currency: 'USD',
    month: '2026-02',
    number: 3,
    paid_before: 2,
    earlier: [
      { fingerprint: 'fp-dec', day: '2025-12-14', description: 'STORE', amount_cents: 15_000, number: 1 },
      { fingerprint: 'fp-jan', day: '2026-01-14', description: 'STORE', amount_cents: 15_000, number: 2 },
    ],
    number_known: true,
    suggested_contact_id: null,
    ...over,
  }
}

export function planOf(over: Partial<InstallmentPlan> = {}): InstallmentPlan {
  return {
    id: 7,
    name: 'Test plan',
    account_label: 'VISA ···0000',
    amount_cents: 15_000,
    currency: 'USD',
    count: 6,
    paid: 3,
    remaining_cents: 45_000,
    first_month: '2025-12',
    last_month: '2026-05',
    group_id: null,
    contact_id: null,
    group_name: null,
    contact_name: null,
    receipt_id: null,
    missing: [],
    installments: [],
    ...over,
  }
}
