// @vitest-environment jsdom
// The extension's reader of Amazon's order-history pages, against small synthetic pages shaped
// like the real ones (classes only; every number and title is made up).
import { beforeAll, describe, expect, test } from 'vitest'
import '../../src/michelito/hosted/extension/reader.js'

interface ReadItem {
  title: string
  quantity: number | null
}
interface ReadOrder {
  order: string
  date: string | null
  items: ReadItem[]
}
interface Read {
  orders: ReadOrder[]
  failed: { index: number; field: string }[]
  next: string | null
}
interface Reader {
  read: (doc: Document, base?: string) => Read
  isoDate: (value: string) => string | null
}

let reader: Reader
beforeAll(() => {
  reader = (globalThis as unknown as { michelitoReader: Reader }).michelitoReader
})

function header(order: string, date: string): string {
  return `
    <div class="a-box order-header"><ul class="order-header__header-list">
      <li class="order-header__header-list-item">
        <div class="a-row"><span class="a-text-caps">Order placed</span></div>
        <div class="a-row"><span class="a-size-base a-color-secondary">${date}</span></div>
      </li>
      <li class="order-header__header-list-item">
        <div class="a-row"><span class="a-text-caps">Total</span></div>
        <div class="a-row"><span class="a-size-base a-color-secondary">$12.34</span></div>
      </li>
      <li class="order-header__header-list-item">
        <div class="yohtmlc-recipient"><span class="a-text-caps">Ship to</span>
          <a class="a-popover-trigger">Synthetic Person</a></div>
      </li>
      <li class="order-header__header-list-item">
        <div class="yohtmlc-order-id"><span class="a-text-caps">Order #</span>
          <span dir="ltr">${order}</span></div>
      </li>
    </ul></div>`
}

function rowItem(title: string, quantity?: string): string {
  return `
    <li><span class="a-list-item"><div class="a-fixed-left-grid item-box">
      <div class="product-image"><a href="/dp/B000000001"><img alt="" /></a>
        ${quantity ? `<span class="product-image__qty">${quantity}</span>` : ''}</div>
      <div class="yohtmlc-product-title"><a href="/dp/B000000001">${title}</a></div>
      <div class="yohtmlc-item-level-connections"><a href="/gp/buyagain">Buy it again</a></div>
    </div></span></li>`
}

function slide(title: string): string {
  return `
    <div class="yo-enhanced-card yo-enhanced-item-carousel__card">
      <div class="yo-enhanced-card-image"><a href="/dp/B000000002"><img alt="" /></a></div>
      <div class="yo-enhanced-title"><a href="/dp/B000000002">${title}</a></div>
    </div>`
}

function card(order: string, date: string, body: string): string {
  return `<div class="order-card js-order-card"><div class="a-box-group">${header(order, date)}
    <div class="a-box delivery-box"><ul class="a-unordered-list">${body}</ul></div></div></div>`
}

function page(cards: string, pagination = ''): Document {
  const html = `<html><body><div id="orders">${cards}</div>${pagination}</body></html>`
  return new DOMParser().parseFromString(html, 'text/html')
}

const NEXT = `<ul class="a-pagination"><li class="a-disabled">Previous</li><li class="a-selected">1</li>
  <li class="a-last"><a href="/your-orders/orders?timeFilter=year-2026&amp;page=2">Next</a></li></ul>`
const LAST = `<ul class="a-pagination"><li class="a-normal">1</li>
  <li class="a-last a-disabled">Next</li></ul>`

describe('reading an order-history page', () => {
  test('reads each order number, date and item names with quantities', () => {
    const doc = page(
      card('111-1111111-1111111', 'November 9, 2026', rowItem('Synthetic headphones', '2') + rowItem('Desk  lamp\n')) +
        card('222-2222222-2222222', 'October 30, 2026', slide('Notebook') + slide('Pencil set')),
      NEXT,
    )

    const found = reader.read(doc)

    expect(found.orders).toEqual([
      {
        order: '111-1111111-1111111',
        date: '2026-11-09',
        items: [
          { title: 'Synthetic headphones', quantity: 2 },
          { title: 'Desk lamp', quantity: null },
        ],
      },
      {
        order: '222-2222222-2222222',
        date: '2026-10-30',
        items: [
          { title: 'Notebook', quantity: null },
          { title: 'Pencil set', quantity: null },
        ],
      },
    ])
    expect(found.failed).toEqual([])
    expect(found.next).toBe('https://www.amazon.com/your-orders/orders?timeFilter=year-2026&page=2')
  })

  test('never returns the address, the total or anything but the order fields', () => {
    const found = reader.read(page(card('111-1111111-1111111', 'May 1, 2026', rowItem('Lamp'))))

    const text = JSON.stringify(found)
    expect(text).not.toContain('Synthetic Person')
    expect(text).not.toContain('12.34')
    expect(Object.keys(found.orders[0]).sort()).toEqual(['date', 'items', 'order'])
  })

  test('reports a card that cannot be read by its field, never its content', () => {
    const doc = page(
      card('not-an-order', 'May 1, 2026', rowItem('Secret title')) +
        card('111-1111111-1111111', 'May 1, 2026', '') +
        card('222-2222222-2222222', 'May 2, 2026', rowItem('Lamp')),
    )

    const found = reader.read(doc)

    expect(found.failed).toEqual([
      { index: 0, field: 'order' },
      { index: 1, field: 'items' },
    ])
    expect(JSON.stringify(found.failed)).not.toContain('Secret')
    expect(found.orders.map((o) => o.order)).toEqual(['222-2222222-2222222'])
  })

  test('a digital order number is read too', () => {
    const found = reader.read(page(card('D01-1111111-1111111', 'May 1, 2026', rowItem('E-book'))))

    expect(found.orders[0].order).toBe('D01-1111111-1111111')
  })

  test('an unreadable date is kept as null and a strange quantity is dropped', () => {
    const found = reader.read(page(card('111-1111111-1111111', 'Yesterday', rowItem('Lamp', 'x'))))

    expect(found.orders[0].date).toBeNull()
    expect(found.orders[0].items).toEqual([{ title: 'Lamp', quantity: null }])
  })

  test('the last page has no next page', () => {
    expect(reader.read(page('', LAST)).next).toBeNull()
    expect(reader.read(page('')).next).toBeNull()
  })

  test('a next link keeps only the parameters that choose the page', () => {
    const noisy = `<ul class="a-pagination"><li class="a-last">
      <a href="/your-orders/orders?timeFilter=year-2025&amp;page=3&amp;ref_=ppx&amp;redirect=https://x.example">Next</a></li></ul>`

    expect(reader.read(page('', noisy)).next).toBe(
      'https://www.amazon.com/your-orders/orders?timeFilter=year-2025&page=3',
    )
  })

  test('a next link to anywhere else is not followed', () => {
    const elsewhere = `<ul class="a-pagination"><li class="a-last">
      <a href="https://attacker.example/your-orders/orders?page=2">Next</a></li></ul>`
    const otherPage = `<ul class="a-pagination"><li class="a-last">
      <a href="/gp/css/order-details?page=2">Next</a></li></ul>`

    expect(reader.read(page('', elsewhere)).next).toBeNull()
    expect(reader.read(page('', otherPage)).next).toBeNull()
  })

  test('titles are cut to the server limit and invisible characters removed', () => {
    const long = 'x'.repeat(400)
    const found = reader.read(page(card('111-1111111-1111111', 'May 1, 2026', rowItem(`A​B ${long}`))))

    const title = found.orders[0].items[0].title
    expect(title.startsWith('AB x')).toBe(true)
    expect(title.length).toBe(300)
  })

  test('dates in the page language are read as ISO days', () => {
    expect(reader.isoDate('January 2, 2026')).toBe('2026-01-02')
    expect(reader.isoDate('December 31, 2025')).toBe('2025-12-31')
    expect(reader.isoDate('Smarch 1, 2026')).toBeNull()
    expect(reader.isoDate('May 40, 2026')).toBeNull()
  })
})
