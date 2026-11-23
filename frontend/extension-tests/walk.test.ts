// The pure parts of the extension's 12-month walk (made-up order numbers and titles).
import { beforeAll, describe, expect, test } from 'vitest'
import '../../src/michelito/hosted/extension/walk.js'

interface Order {
  order: string
  date: string | null
  items: { title: string; quantity: number | null }[]
}
interface Walk {
  cutoff: (today: Date) => string
  startPages: (today: Date) => string[]
  isOrdersPage: (address: string) => boolean
  recent: (orders: Order[], since: string) => { kept: Order[]; older: boolean }
  payload: (orders: Order[]) => { order: string; items: { title: string; quantity?: number }[] }[]
  batches: <T>(list: T[], size?: number) => T[][]
  pause: (random?: () => number) => number
}

let walk: Walk
beforeAll(() => {
  walk = (globalThis as unknown as { michelitoWalk: Walk }).michelitoWalk
})

const order = (number: string, date: string | null, ...titles: string[]): Order => ({
  order: number,
  date,
  items: titles.map((title) => ({ title, quantity: null })),
})

describe('the 12-month walk', () => {
  test('starts 365 days back and walks this year and the last', () => {
    const today = new Date(2026, 10, 23)

    expect(walk.cutoff(today)).toBe('2025-11-23')
    expect(walk.startPages(today)).toEqual([
      'https://www.amazon.com/your-orders/orders?timeFilter=year-2026',
      'https://www.amazon.com/your-orders/orders?timeFilter=year-2025',
    ])
  })

  test('on the last day of a leap year only that year is needed', () => {
    expect(walk.startPages(new Date(2028, 11, 31))).toEqual([
      'https://www.amazon.com/your-orders/orders?timeFilter=year-2028',
    ])
  })

  test('only order-history pages may be read', () => {
    expect(walk.isOrdersPage('https://www.amazon.com/your-orders/orders?page=2')).toBe(true)
    expect(walk.isOrdersPage('https://www.amazon.com/ap/signin?x=1')).toBe(false)
    expect(walk.isOrdersPage('https://www.amazon.com/gp/css/summary/print.html')).toBe(false)
    expect(walk.isOrdersPage('https://amazon.com.attacker.example/your-orders/orders')).toBe(false)
    expect(walk.isOrdersPage('not a url')).toBe(false)
  })

  test('keeps the orders inside the 12 months and says when older ones appear', () => {
    const page = [
      order('111-1111111-1111111', '2026-01-02', 'A'),
      order('222-2222222-2222222', null, 'B'),
      order('333-3333333-3333333', '2025-11-01', 'C'),
    ]

    const { kept, older } = walk.recent(page, '2025-11-23')

    expect(kept.map((o) => o.order)).toEqual(['111-1111111-1111111', '222-2222222-2222222'])
    expect(older).toBe(true)
    expect(walk.recent(page.slice(0, 2), '2025-11-23').older).toBe(false)
  })

  test('sends only the order number and item titles and quantities', () => {
    const found = walk.payload([
      { order: '111-1111111-1111111', date: '2026-01-02', items: [{ title: 'Lamp', quantity: 2 }, { title: 'Cable', quantity: null }] },
      order('bad', '2026-01-02', 'Lamp'),
      order('222-2222222-2222222', '2026-01-02'),
      { order: '333-3333333-3333333', date: null, items: [{ title: 'x'.repeat(400), quantity: 5000 }] },
    ])

    expect(found).toEqual([
      { order: '111-1111111-1111111', items: [{ title: 'Lamp', quantity: 2 }, { title: 'Cable' }] },
      { order: '333-3333333-3333333', items: [{ title: 'x'.repeat(300) }] },
    ])
  })

  test('sends at most 20 orders per request', () => {
    const list = Array.from({ length: 45 }, (_, index) => index)

    expect(walk.batches(list).map((batch) => batch.length)).toEqual([20, 20, 5])
    expect(walk.batches([])).toEqual([])
  })

  test('waits between 2.5 and 4 seconds between pages', () => {
    expect(walk.pause(() => 0)).toBe(2500)
    expect(walk.pause(() => 1)).toBe(4000)
  })
})
