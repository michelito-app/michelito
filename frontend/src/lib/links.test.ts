import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { ExchangeInfo, LinkedTx, Tx } from './api'
import {
  showDebitPayment,
  backPath,
  categoryLocked,
  exchangeLine,
  groupPath,
  linkBadges,
  linkedAmount,
  linkedLabel,
  linkPagePath,
  linkSummaries,
  listPath,
  moneyList,
  parseCents,
  showExchange,
  showReimbursement,
  showShared,
} from './links'
import type { LedgerRef } from './sharedApi'

const LEDGER: LedgerRef = {
  group_id: 4,
  group_name: 'Cena con Ana', // spanish-data
  role: 'entry',
  entry_id: 9,
  payment_id: null,
  my_share_cents: 100_000,
  pending_cents: 200_000,
  currency: 'DOP',
  paid_by_name: '',
}

function tx(overrides: Partial<Tx> = {}): Tx {
  return {
    fingerprint: 'f',
    day: '2026-02-02',
    merchant: 'RESTAURANTE',
    description: 'RESTAURANTE',
    category: 'Restaurantes', // spanish-data
    category_id: 2,
    kind: 'expense',
    original_category: 'Restaurantes', // spanish-data
    account: 'visa',
    account_label: 'Visa',
    amount_cents: 300_000,
    currency: 'DOP',
    amount_dop_cents: 300_000,
    one_off: false,
    corrected: false,
    merchant_year_count: 1,
    suggested_one_off: false,
    one_off_reasons: [],
    one_off_dismissed: false,
    note: '',
    link: '',
    gross_cents: null,
    pending_cents: 0,
    ledger: null,
    exchange: null,
    suggested_exchange_with: null,
    can_invest: false,
    can_invest_credit: false,
    investment: null,
    investment_role: '',
    investment_capital_cents: null,
    suggested_investment: null,
    can_store: false,
    can_deposit: false,
    cash_box_role: '',
    cash_box_currency: null,
    cash_box_amount_cents: null,
    cash_entry_id: null,
    provisional: false,
    link_id: null,
    can_share: false,
    can_reimburse: false,
    can_pay: false,
    can_exchange: false,
    ...overrides,
  }
}

const LINKED: LinkedTx = {
  fingerprint: 'e',
  day: '2026-02-02',
  merchant: 'RESTAURANTE',
  account_label: 'Visa',
  amount_cents: -100_000,
  currency: 'DOP',
}

describe('linkBadges', () => {
  it('shared with what you are owed, a group movement, a group payment, exchange', () => {
    expect(linkBadges(tx())).toEqual([])
    const labels = (row: Tx) => linkBadges(row).map((b) => b.label)
    expect(labels(tx({ link: 'shared', ledger: LEDGER, pending_cents: 200_000 }))).toEqual([
      t('links.badge.shared'),
      t('links.badge.owed', { amount: 'RD$ 2,000' }),
    ])
    expect(labels(tx({ link: 'shared', ledger: LEDGER, pending_cents: 0 }))).toEqual([
      t('links.badge.shared'),
    ])
    expect(labels(tx({ link: 'group', ledger: { ...LEDGER, role: 'group' } }))).toEqual([
      t('links.badge.group'),
    ])
    expect(labels(tx({ link: 'reimbursement', ledger: { ...LEDGER, role: 'payment' } }))).toEqual([
      t('links.badge.reimbursement'),
    ])
    expect(labels(tx({ suggested_exchange_with: LINKED }))).toEqual([
      t('links.badge.suggestedExchange'),
    ])
  })
})

describe('linkedLabel / linkedAmount', () => {
  it('name with the day, and a signed amount', () => {
    expect(linkedLabel(LINKED)).toBe('RESTAURANTE (2 de febrero)') // spanish-ui
    expect(linkedAmount(LINKED)).toBe('+RD$ 1,000')
    expect(linkedAmount({ ...LINKED, amount_cents: 100_000, currency: 'USD' })).toBe('US$ 1,000.00')
  })

  it("a credit in the expense's other currency carries what it is worth in it", () => {
    const dopCredit = { ...LINKED, amount_cents: -60_000, converted_currency: 'USD' }
    expect(linkedAmount({ ...dopCredit, converted_cents: 1_000 })).toBe('+RD$ 600 ≈ US$ 10.00')
    expect(linkedAmount({ ...dopCredit, converted_cents: null })).toBe(
      t('links.linkedAmount.noRate', { amount: '+RD$ 600' }),
    )
  })
})

describe('exchangeLine', () => {
  const exchange: ExchangeInfo = {
    id: 1,
    rate: '62.5000',
    implied_rate: '80.0000',
    agreed_rate: '62.5000',
    closed: false,
    base: 'DOP',
    totals: [
      { currency: 'DOP', cents: 12_000_000 },
      { currency: 'USD', cents: 150_000 },
    ],
    pending_cents: 42_000,
    pending_currency: 'USD',
    pending_dop_cents: 2_625_000,
    needs_agreed_rate: false,
    legs: [],
  }

  it('sides, rate and pending', () => {
    expect(exchangeLine(exchange)).toBe(
      'Cambio: RD$ 120,000 ↔ US$ 1,500.00 · tasa 62.50 · pendiente US$ 420.00 ≈ RD$ 26,250', // spanish-ui
    )
  })

  it('closed or nothing pending', () => {
    const closed = exchangeLine({ ...exchange, closed: true, pending_cents: 0 })
    expect(closed.endsWith(` · ${t('links.exchange.closed')}`)).toBe(true)
    const settled = exchangeLine({ ...exchange, pending_cents: 0 })
    expect(settled.endsWith(` · ${t('links.exchange.noPending')}`)).toBe(true)
    expect(
      exchangeLine({ ...exchange, base: 'USD', pending_currency: 'DOP', pending_cents: 500_000 }),
    ).toBe(
      [
        t('links.exchange.line', { sides: 'US$ 1,500.00 ↔ RD$ 120,000' }),
        t('links.exchange.rate', { rate: '62.50' }),
        t('links.exchange.pending', { amount: 'RD$ 5,000' }),
      ].join(' · '),
    )
  })
})

describe('parseCents', () => {
  it('reads amounts with commas, a currency sign and up to two decimals', () => {
    expect(parseCents('1,850.50')).toBe(185_050)
    expect(parseCents('RD$ 400')).toBe(40_000)
    expect(parseCents('0')).toBeNull()
    expect(parseCents('1.234')).toBeNull()
    expect(parseCents('abc')).toBeNull()
  })

  it('lists amounts in several currencies, zeros left out', () => {
    expect(
      moneyList([
        { currency: 'DOP', cents: 300_000 },
        { currency: 'USD', cents: 12_000 },
      ]),
    ).toBe('RD$ 3,000 + US$ 120.00')
    expect(moneyList([{ currency: 'DOP', cents: 0 }])).toBe('RD$ 0')
  })
})

describe('detail sections', () => {
  it('follow the server rules and also show dormant links', () => {
    expect(showShared(tx())).toBe(false)
    expect(showShared(tx({ can_share: true }))).toBe(true)
    expect(showShared(tx({ link: 'shared', ledger: LEDGER }))).toBe(true)
    expect(showReimbursement(tx({ can_reimburse: true }))).toBe(true)
    // A credit already in a group is shown by its group, not offered again.
    expect(showReimbursement(tx({ can_reimburse: true, ledger: LEDGER }))).toBe(false)
    expect(showReimbursement(tx({ amount_cents: -100, kind: 'income' }))).toBe(false)
    expect(showDebitPayment(tx({ can_pay: true }))).toBe(true)
    // A debit already in a group is shown by its group, not offered again.
    expect(showDebitPayment(tx({ can_pay: true, ledger: LEDGER }))).toBe(false)
    expect(showDebitPayment(tx())).toBe(false)
    expect(showExchange(tx({ can_exchange: true }))).toBe(true)
    expect(showExchange(tx({ link: 'exchange' }))).toBe(true)
  })

  it('the link sets the category of a linked credit or leg', () => {
    expect(categoryLocked(tx({ link: 'reimbursement' }))).toBe(true)
    expect(categoryLocked(tx({ link: 'group' }))).toBe(true)
    expect(categoryLocked(tx({ link: 'exchange' }))).toBe(true)
    expect(categoryLocked(tx({ link: 'cash_box' }))).toBe(true)
    expect(categoryLocked(tx({ link: 'shared' }))).toBe(false)
    expect(categoryLocked(tx())).toBe(false)
  })

  it('a dormant link keeps its badge', () => {
    expect(linkBadges(tx({ link: 'reimbursement' })).map((b) => b.label)).toEqual([
      t('links.badge.reimbursement'),
    ])
    expect(linkBadges(tx({ link: 'exchange' })).map((b) => b.label)).toEqual([
      t('links.badge.exchange'),
    ])
  })
})

describe('linkSummaries', () => {
  const texts = (row: Tx) => linkSummaries(row).map((s) => `${s.text} [${s.action}]`)
  const manage = t('links.action.manage')

  it('an expense that can be shared offers to share it', () => {
    expect(texts(tx({ can_share: true }))).toEqual([
      `${t('shared.tx.offer')} [${t('shared.tx.share')}]`,
    ])
  })

  it('a row in a group: its part, what you are owed, and «Open group»', () => {
    const [entry] = linkSummaries(tx({ link: 'shared', ledger: LEDGER }))
    expect(entry.text).toBe(
      t('shared.tx.entryPending', {
        group: 'Cena con Ana', // spanish-data
        share: 'RD$ 1,000',
        pending: 'RD$ 2,000',
      }),
    )
    expect(entry.action).toBe(t('shared.tx.openGroup'))
    expect(entry.href).toBe(groupPath(4))
    const settled = linkSummaries(tx({ link: 'shared', ledger: { ...LEDGER, pending_cents: 0 } }))
    expect(settled[0].text).toBe(
      t('shared.tx.entry', { group: 'Cena con Ana', share: 'RD$ 1,000' }), // spanish-data
    )
    const movement = { ...LEDGER, role: 'group' as const, paid_by_name: 'Ana' }
    expect(linkSummaries(tx({ link: 'group', ledger: movement }))[0].text).toBe(
      t('shared.tx.group', { payer: 'Ana', group: 'Cena con Ana' }), // spanish-data
    )
  })

  it('a credit: a payment in a group, or offered as one; and whether it can be an exchange', () => {
    const payment = { ...LEDGER, role: 'payment' as const }
    expect(texts(tx({ link: 'reimbursement', ledger: payment }))).toEqual([
      `${t('shared.tx.payment', { group: 'Cena con Ana' })} [${t('shared.tx.openGroup')}]`, // spanish-data
    ])
    expect(texts(tx({ can_reimburse: true, can_exchange: true }))).toEqual([
      `${t('shared.tx.creditOffer')} [${t('shared.tx.record')}]`,
      `${t('links.summary.exchangeOffer')} [${manage}]`,
    ])
  })

  it('an exchange: pending, nothing pending, closed or incomplete', () => {
    const exchange: ExchangeInfo = {
      id: 1,
      rate: '63.7000',
      implied_rate: '63.7000',
      agreed_rate: null,
      closed: false,
      base: 'DOP',
      totals: [],
      pending_cents: 100_000,
      pending_currency: 'USD',
      pending_dop_cents: 6_370_000,
      needs_agreed_rate: false,
      legs: [],
    }
    const row = (e: Partial<ExchangeInfo>) =>
      linkSummaries(tx({ link: 'exchange', exchange: { ...exchange, ...e } }))[0].text
    expect(row({})).toBe(t('links.summary.exchangePending', { amount: 'US$ 1,000.00' }))
    expect(row({ pending_cents: 0 })).toBe(t('links.summary.exchangeNoPending'))
    expect(row({ closed: true, pending_cents: 0 })).toBe(t('links.summary.exchangeClosed'))
    expect(linkSummaries(tx({ link: 'exchange' }))[0].text).toBe(
      t('links.summary.exchangeIncomplete'),
    )
  })
})

describe('backPath', () => {
  const row = { fingerprint: 'f 1', day: '2026-02-02' }

  it('returns to the list it came from', () => {
    expect(backPath(row, '/transactions?month=2026-02&q=cafe&tx=f')).toBe(
      '/transactions?month=2026-02&q=cafe&tx=f',
    )
  })

  it("when entered directly, to the transaction's month with it selected", () => {
    expect(backPath(row, undefined)).toBe('/transactions?month=2026-02&tx=f+1')
    expect(backPath(row, 'https://other.site/')).toBe('/transactions?month=2026-02&tx=f+1')
    expect(linkPagePath('f 1')).toBe('/transactions/f%201')
  })

  it('returns to Pending when it came from there', () => {
    expect(backPath(row, '/pending')).toBe('/pending')
    expect(backPath(row, '/pending?accounts=a')).toBe('/pending?accounts=a')
    expect(backPath(row, '/pending-fake')).toBe('/transactions?month=2026-02&tx=f+1')
    expect(listPath('/pending')).toBe('/pending')
  })

  it('returns to Shared with its view', () => {
    const from = '/shared?view=groups'
    expect(backPath(row, from)).toBe(from)
    expect(listPath('/shared')).toBe('/shared')
  })

  it('without the transaction, to the list it came from or to Transactions', () => {
    expect(listPath('/transactions?month=2026-02')).toBe('/transactions?month=2026-02')
    expect(listPath('//other.site/transactions')).toBe('/transactions')
    expect(listPath(undefined)).toBe('/transactions')
  })
})
