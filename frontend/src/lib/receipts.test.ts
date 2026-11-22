import { describe, expect, it } from 'vitest'
import type { Receipt, Tx } from './api'
import { bankName, receiptHeading, receiptTitle, safeLink } from './receipts'

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
