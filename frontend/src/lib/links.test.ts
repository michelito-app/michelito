import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { ExchangeInfo, GroupExpense, GroupRef, LinkedTx, SharedInfo, Tx } from './api'
import {
  backPath,
  categoryLocked,
  exchangeLine,
  expenseStatus,
  groupLabel,
  linkBadges,
  linkedAmount,
  linkedLabel,
  linkPagePath,
  linkSummaries,
  listPath,
  moneyList,
  overWarning,
  parseCents,
  sharedBody,
  sharedStats,
  showExchange,
  showReimbursement,
  showShared,
  splitDraftOf,
  splitText,
  unconvertedWarning,
} from './links'

function expense(overrides: Partial<GroupExpense> = {}): GroupExpense {
  return {
    fingerprint: 'e',
    day: '2026-02-02',
    merchant: 'RESTAURANTE',
    account_label: 'Visa',
    amount_cents: 185_000,
    currency: 'DOP',
    people: 3,
    my_share_cents: null,
    for_other: false,
    share_cents: 61_667,
    counted_cents: 61_667,
    reimbursed_cents: 61_667,
    pending_cents: 61_666,
    written_off_cents: 0,
    ...overrides,
  }
}

function shared(overrides: Partial<SharedInfo> = {}): SharedInfo {
  return {
    id: 1,
    title: 'Ana y Luis', // spanish-data
    name: '',
    with_whom: 'Ana y Luis', // spanish-data
    first_fingerprint: 'e',
    expense_count: 1,
    pending: [{ currency: 'DOP', cents: 61_666 }],
    last_split: { people: 3, my_share_cents: null, for_other: false },
    written_off: false,
    expenses: [expense()],
    totals: [
      {
        currency: 'DOP',
        share_cents: 61_667,
        reimbursed_cents: 61_667,
        pending_cents: 61_666,
        written_off_cents: 0,
      },
    ],
    excess: [],
    unconverted: [],
    reimbursements: [],
    manual: [],
    ...overrides,
  }
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
    shared: null,
    reimbursement_of: null,
    suggested_group: null,
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
    link_id: null,
    can_share: false,
    can_reimburse: false,
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

describe('splitText / sharedStats', () => {
  it('says how each expense was split', () => {
    expect(splitText(expense(), 'DOP')).toBe(t('links.split.people', { people: 3 }))
    expect(splitText(expense({ people: null, my_share_cents: 40_000 }), 'DOP')).toBe(
      t('links.split.myShare', { amount: 'RD$ 400' }),
    )
    expect(splitText(expense({ people: null, for_other: true }), 'USD')).toBe(
      t('links.split.forOther'),
    )
  })

  it("the group's share, reimbursed and pending amounts", () => {
    expect(sharedStats(shared())).toEqual([
      { label: t('links.stat.yourShare'), value: 'RD$ 617' },
      { label: t('links.stat.reimbursed'), value: 'RD$ 617' },
      { label: t('links.stat.owed'), value: 'RD$ 617' },
    ])
    const lost = shared({
      written_off: true,
      totals: [
        {
          currency: 'DOP',
          share_cents: 61_667,
          reimbursed_cents: 61_667,
          pending_cents: 0,
          written_off_cents: 61_666,
        },
      ],
    })
    expect(sharedStats(lost)[2]).toEqual({ label: t('links.stat.writtenOff'), value: 'RD$ 617' })
  })

  it('by currency when the group has expenses in RD$ and US$', () => {
    const both = shared({
      totals: [
        {
          currency: 'DOP',
          share_cents: 600_000,
          reimbursed_cents: 300_000,
          pending_cents: 300_000,
          written_off_cents: 0,
        },
        {
          currency: 'USD',
          share_cents: 0,
          reimbursed_cents: 10_000,
          pending_cents: 12_000,
          written_off_cents: 0,
        },
      ],
    })
    expect(sharedStats(both)).toEqual([
      { label: t('links.stat.yourShare'), value: 'RD$ 6,000' },
      { label: t('links.stat.reimbursed'), value: 'RD$ 3,000 + US$ 100.00' },
      { label: t('links.stat.owed'), value: 'RD$ 3,000 + US$ 120.00' },
    ])
    expect(moneyList([{ currency: 'USD', cents: 0 }])).toBe('US$ 0.00')
  })

  it('the status of each expense after applying the reimbursements', () => {
    expect(expenseStatus(expense())).toBe(t('links.expense.pending', { amount: 'RD$ 617' }))
    expect(expenseStatus(expense({ pending_cents: 0 }))).toBe(t('links.expense.settled'))
    expect(expenseStatus(expense({ pending_cents: 0, written_off_cents: 50_000 }))).toBe(
      t('links.expense.writtenOff', { amount: 'RD$ 500' }),
    )
  })

  it('warns about an over-reimbursement or a missing rate', () => {
    expect(overWarning(shared())).toBeNull()
    expect(overWarning(shared({ excess: [{ currency: 'DOP', cents: 10_000 }] }))).toBe(
      t('links.warning.over', { amount: 'RD$ 100' }),
    )
    expect(unconvertedWarning(shared())).toBeNull()
    expect(unconvertedWarning(shared({ unconverted: ['c'] }))).toBe(
      t('links.warning.unconverted', { count: 1 }),
    )
    expect(unconvertedWarning(shared({ unconverted: ['c', 'd'] }))).toBe(
      t('links.warning.unconverted', { count: 2 }),
    )
  })

  it('a group in a list: title and what you are owed', () => {
    const ref: GroupRef = {
      ...shared(),
      title: 'Carola y Rafael', // spanish-data
      pending: [{ currency: 'USD', cents: 91_237 }],
    }
    expect(groupLabel(ref)).toBe(
      t('links.group.label', {
        title: ref.title,
        status: t('links.group.owed', { amount: 'US$ 912.37' }),
      }),
    )
    expect(groupLabel({ ...ref, pending: [] })).toBe(
      t('links.group.label', { title: ref.title, status: t('links.group.settled') }),
    )
  })
})

describe('linkBadges', () => {
  it('shared with what you are owed, reimbursement, exchange and suggestions', () => {
    expect(linkBadges(tx())).toEqual([])
    const labels = (row: Tx) => linkBadges(row).map((b) => b.label)
    expect(labels(tx({ link: 'shared', shared: shared(), pending_cents: 200_000 }))).toEqual([
      t('links.badge.shared'),
      t('links.badge.owed', { amount: 'RD$ 2,000' }),
    ])
    expect(labels(tx({ link: 'shared', shared: shared(), pending_cents: 0 }))).toEqual([
      t('links.badge.shared'),
    ])
    // A reimbursement carries its group, but it is not "shared".
    const reimbursement = [t('links.badge.reimbursement')]
    expect(labels(tx({ link: 'reimbursement', shared: shared() }))).toEqual(reimbursement)
    expect(labels(tx({ link: 'reimbursement', reimbursement_of: LINKED }))).toEqual(reimbursement)
    expect(labels(tx({ suggested_group: shared() }))).toEqual([
      t('links.badge.suggestedReimbursement'),
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

describe('parseCents / sharedBody', () => {
  it('reads amounts with commas, a currency sign and up to two decimals', () => {
    expect(parseCents('1,850.50')).toBe(185_050)
    expect(parseCents('RD$ 400')).toBe(40_000)
    expect(parseCents('0')).toBeNull()
    expect(parseCents('1.234')).toBeNull()
    expect(parseCents('abc')).toBeNull()
  })

  it('builds the split or says what is missing', () => {
    const draft = splitDraftOf(null)
    expect(sharedBody({ ...draft, people: '3' }, 300_000)).toEqual({ body: { people: 3 } })
    expect(sharedBody({ ...draft, people: '1' }, 300_000)).toEqual({
      error: t('links.splitError.people'),
    })
    expect(sharedBody({ ...draft, mode: 'share', share: '400' }, 300_000)).toEqual({
      body: { my_share_cents: 40_000 },
    })
    expect(sharedBody({ ...draft, mode: 'share', share: '4000' }, 300_000)).toEqual({
      error: t('links.splitError.shareTooBig'),
    })
    expect(sharedBody({ ...draft, mode: 'share', share: 'x' }, 300_000)).toEqual({
      error: t('links.splitError.share'),
    })
    expect(sharedBody({ ...draft, mode: 'other' }, 300_000)).toEqual({
      body: { for_other: true },
    })
  })

  it('the form starts from what was saved', () => {
    expect(splitDraftOf(expense({ people: null, my_share_cents: 40_000 }))).toEqual({
      mode: 'share',
      people: '2',
      share: '400.00',
    })
  })
})

describe('detail sections', () => {
  it('follow the server rules and also show dormant links', () => {
    expect(showShared(tx())).toBe(false)
    expect(showShared(tx({ can_share: true }))).toBe(true)
    expect(showShared(tx({ link: 'shared' }))).toBe(true) // dormant: it can be unshared
    expect(showReimbursement(tx({ can_reimburse: true }))).toBe(true)
    expect(showReimbursement(tx({ link: 'reimbursement' }))).toBe(true)
    expect(showReimbursement(tx({ amount_cents: -100, kind: 'income' }))).toBe(false)
    expect(showExchange(tx({ can_exchange: true }))).toBe(true)
    expect(showExchange(tx({ link: 'exchange' }))).toBe(true)
  })

  it('the link sets the category of a linked credit or leg', () => {
    expect(categoryLocked(tx({ link: 'reimbursement' }))).toBe(true)
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
  const sharedText = (status: string, refunds: number) =>
    t('links.summary.sharedText', {
      title: 'Ana y Luis', // spanish-data
      status,
      refunds: t('links.summary.refundCount', { count: refunds }),
    })

  it('an expense that can be shared offers to share it', () => {
    expect(texts(tx({ can_share: true }))).toEqual([
      `${t('links.summary.sharedOffer')} [${t('links.action.share')}]`,
    ])
  })

  it('a shared expense: its group, what you are owed and how many reimbursements', () => {
    const row = tx({ link: 'shared', shared: shared({ reimbursements: [LINKED] }) })
    expect(texts(row)).toEqual([
      'Parte de Ana y Luis · te deben RD$ 617 · 1 reembolso [Gestionar…]', // spanish-ui
    ])
    const both = shared({
      pending: [
        { currency: 'DOP', cents: 300_000 },
        { currency: 'USD', cents: 12_000 },
      ],
    })
    const owed = (amount: string) => t('links.group.owed', { amount })
    expect(texts(tx({ link: 'shared', shared: both }))).toEqual([
      `${sharedText(owed('RD$ 3,000 + US$ 120.00'), 0)} [${manage}]`,
    ])
    expect(texts(tx({ link: 'shared', shared: shared({ pending: [] }) }))).toEqual([
      `${sharedText(t('links.group.settled'), 0)} [${manage}]`,
    ])
  })

  it('a credit: linked or to be linked; and whether it can be an exchange', () => {
    const of = (what: string) => t('links.summary.reimbursementOf', { what })
    expect(texts(tx({ link: 'reimbursement', reimbursement_of: LINKED }))).toEqual([
      `${of(linkedLabel(LINKED))} [${manage}]`,
    ])
    expect(texts(tx({ link: 'reimbursement', shared: shared() }))).toEqual([
      `${of(groupLabel(shared()))} [${manage}]`,
    ])
    expect(texts(tx({ can_reimburse: true, can_exchange: true }))).toEqual([
      `${t('links.summary.reimbursementOffer')} [${manage}]`,
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

  it('returns to Shared with the chip, the search and the expanded group', () => {
    const from = '/shared?status=settled&q=clothes&group=2'
    expect(backPath(row, from)).toBe(from)
    expect(listPath('/shared')).toBe('/shared')
  })

  it('without the transaction, to the list it came from or to Transactions', () => {
    expect(listPath('/transactions?month=2026-02')).toBe('/transactions?month=2026-02')
    expect(listPath('//other.site/transactions')).toBe('/transactions')
    expect(listPath(undefined)).toBe('/transactions')
  })
})
