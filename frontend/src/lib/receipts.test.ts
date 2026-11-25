import { describe, expect, it } from 'vitest'
import type { Receipt, Tx } from './api'
import { formatUsd } from './money'
import { bankName, itemLine, itemLines, receiptHeading, receiptTitle, safeLink, shortName } from './receipts'

function receipt(over: Partial<Receipt> = {}): Receipt {
  return {
    id: 1,
    merchant: 'Amazon',
    kind: 'shipment',
    orders: ['ORDER-A'],
    amount_cents: 11097,
    currency: 'USD',
    day: '2026-02-14',
    summary: 'Kitchen',
    item_count: 3,
    order_link: 'https://shop.example/orders/ORDER-A',
    email_link: 'https://mail.example/m-1',
    origin: 'automatic',
    ...over,
  }
}

function tx(receipts: Receipt[] | undefined): Pick<Tx, 'merchant' | 'receipts'> {
  return { merchant: 'AMAZON MKTPL', receipts }
}

describe('receiptTitle', () => {
  it('names the merchant, the count and the summary', () => {
    expect(receiptTitle(tx([receipt()]))).toBe('Amazon: 3 artículos, Kitchen') // spanish-ui
  })

  it('says one item in the singular', () => {
    expect(receiptTitle(tx([receipt({ item_count: 1 })]))).toBe('Amazon: 1 artículo, Kitchen') // spanish-ui
  })

  it('leaves out what the email did not say', () => {
    expect(receiptTitle(tx([receipt({ item_count: null })]))).toBe('Amazon: Kitchen')
    expect(receiptTitle(tx([receipt({ summary: '' })]))).toBe('Amazon: 3 artículos') // spanish-ui
    expect(receiptTitle(tx([receipt({ item_count: null, summary: '' })]))).toBe('Amazon')
  })

  it('is null without receipts, so the bank name stays the title', () => {
    expect(receiptTitle(tx([]))).toBeNull()
    expect(receiptTitle(tx(undefined))).toBeNull()
  })

  it('prefers the shipment, which is the one that says what was charged', () => {
    const order = receipt({ id: 2, kind: 'order', summary: 'Kitchen, Tools, and more', item_count: 6 })
    expect(receiptTitle(tx([order, receipt()]))).toBe('Amazon: 3 artículos, Kitchen') // spanish-ui
  })
})

describe('receiptTitle with item names', () => {
  const item = (title: string, quantity: number | null = null) => ({ title, quantity, price_cents: null })

  it('names the only item', () => {
    expect(receiptTitle(tx([receipt({ items: [item('Synthetic kettle')] })]))).toBe('Amazon: Synthetic kettle')
  })

  it('lists short names while they fit and counts the rest', () => {
    const items = [
      item('Synthetic Kettle Electric Stainless, 1.7L'),
      item('Plain Ceramic Mug Large'),
      item('Sample Spoon Set'),
      item('Sample Fork'),
    ]
    expect(receiptTitle(tx([receipt({ items })]))).toBe(
      'Amazon: Synthetic Kettle Electric, Plain Ceramic Mug y 2 más', // spanish-ui
    )
  })

  it('lists every short name when they all fit', () => {
    const items = [item('Synthetic kettle'), item('Mug'), item('Spoon')]
    expect(receiptTitle(tx([receipt({ items })]))).toBe('Amazon: Synthetic kettle, Mug, Spoon')
  })

  it('keeps the first name even when it alone is long', () => {
    const items = [item('Extraordinarily Longwinded Supercalifragilistic Name'), item('Mug')]
    expect(receiptTitle(tx([receipt({ items })]))).toBe(
      'Amazon: Extraordinarily Longwinded Supercalifragilistic y 1 más', // spanish-ui
    )
  })

  it('joins items with the same short name', () => {
    const items = [item('Sample Jeans Relaxed'), item('Sample Jeans Relaxed (Big & Tall), Blue')]
    expect(receiptTitle(tx([receipt({ items })]))).toBe('Amazon: Sample Jeans Relaxed (2)')
  })

  it('counts a quantity as more than one', () => {
    const items = [item('Synthetic kettle', 3)]
    expect(receiptTitle(tx([receipt({ items })]))).toBe('Amazon: Synthetic kettle (3)')
  })

  it('falls back to the email summary without names', () => {
    expect(receiptTitle(tx([receipt({ items: [] })]))).toBe('Amazon: 3 artículos, Kitchen') // spanish-ui
  })
})

describe('shortName', () => {
  it('cuts at the first comma, parenthesis, bracket or dash', () => {
    expect(shortName('Sample Kettle, 1.7L, Steel', 5)).toBe('Sample Kettle')
    expect(shortName('Sample Jeans (Big & Tall)', 5)).toBe('Sample Jeans')
    expect(shortName('Sample Lamp [2 Pack]', 5)).toBe('Sample Lamp')
    expect(shortName('Sample Mug - Large | Blue', 5)).toBe('Sample Mug')
  })

  it('keeps at most the given number of words', () => {
    expect(shortName('One Two Three Four Five Six Seven', 5)).toBe('One Two Three Four Five')
    expect(shortName('One Two Three Four', 3)).toBe('One Two Three')
  })

  it('drops trailing punctuation and keeps hyphenated words', () => {
    expect(shortName('Sample Wi-Fi Plug.', 5)).toBe('Sample Wi-Fi Plug')
    expect(shortName('Sample Plug: Smart Outdoor', 2)).toBe('Sample Plug')
  })

  it('falls back to the first words when the cut leaves nothing', () => {
    expect(shortName('(New) Sample Hat Wool', 3)).toBe('(New) Sample Hat')
  })
})

describe('itemLines', () => {
  it('shortens each name to five words and keeps quantity and price', () => {
    const items = [{ title: 'One Two Three Four Five Six, Seven', quantity: 2, price_cents: 1250 }]
    expect(itemLines(items)).toEqual([`2 × One Two Three Four Five · ${formatUsd(1250)}`])
  })

  it('joins items with the same short name, adding their quantities', () => {
    const items = [
      { title: 'Sample Jeans Relaxed, Blue', quantity: null, price_cents: 4000 },
      { title: 'Sample Jeans Relaxed (Big & Tall)', quantity: 2, price_cents: 4000 },
      { title: 'Mug', quantity: null, price_cents: null },
    ]
    expect(itemLines(items)).toEqual([`3 × Sample Jeans Relaxed · ${formatUsd(4000)}`, 'Mug'])
  })

  it('drops the price when the joined items cost differently', () => {
    const items = [
      { title: 'Sample Jeans, Blue', quantity: null, price_cents: 4000 },
      { title: 'Sample Jeans, Black', quantity: null, price_cents: 4500 },
    ]
    expect(itemLines(items)).toEqual(['2 × Sample Jeans'])
  })
})

describe('itemLine', () => {
  it('shows the quantity and the unit price when known', () => {
    expect(itemLine({ title: 'Mug', quantity: 2, price_cents: 1250 })).toBe(`2 × Mug · ${formatUsd(1250)}`)
    expect(itemLine({ title: 'Mug', quantity: null, price_cents: null })).toBe('Mug')
  })
})

describe('bankName', () => {
  it('is the statement merchant only when a receipt took the title', () => {
    expect(bankName(tx([receipt()]))).toBe('AMAZON MKTPL')
    expect(bankName(tx([]))).toBeNull()
  })
})

describe('receiptHeading', () => {
  it('says what kind of email it was and when it arrived', () => {
    expect(receiptHeading(receipt())).toBe('Envío · 14 feb') // spanish-ui
    expect(receiptHeading(receipt({ kind: 'order' }))).toBe('Pedido · 14 feb') // spanish-ui
  })
})

describe('safeLink', () => {
  it('lets only https addresses through', () => {
    expect(safeLink('https://mail.example/m-1')).toBe('https://mail.example/m-1')
    expect(safeLink('javascript:alert(1)')).toBeNull()
    expect(safeLink('http://mail.example/m-1')).toBeNull()
    expect(safeLink('')).toBeNull()
  })
})
