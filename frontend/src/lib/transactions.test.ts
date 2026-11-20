import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { Tx } from './api'
import {
  activeFilterCount,
  compactDayLabel,
  isoToday,
  amountLines,
  amountTone,
  apiPath,
  clearFilters,
  dayLabel,
  editBody,
  groupByDay,
  hasNarrowing,
  historyText,
  kindBadge,
  merchantScopeNote,
  oneOffBadge,
  outOfView,
  oneOffAction,
  parseFilters,
  toParams,
  originText,
  totalsParts,
  dayGroups,
  fieldGroups,
  groupLine,
  sortItems,
  totalsOf,
} from './transactions'

function tx(overrides: Partial<Tx> = {}): Tx {
  return {
    fingerprint: 'f1',
    day: '2026-09-27',
    merchant: 'Café Ficticio', // spanish-data
    description: 'CAFE FICTICIO SRL',
    category: 'Restaurantes', // spanish-data
    category_id: 2,
    kind: 'expense',
    original_category: 'Supermercado', // spanish-data
    account: 'visa',
    account_label: 'Visa ···1234',
    amount_cents: 198_000,
    currency: 'DOP',
    amount_dop_cents: 198_000,
    one_off: false,
    corrected: false,
    merchant_year_count: 3,
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
    can_exchange: false,
    ...overrides,
  }
}

describe('parseFilters', () => {
  it('reads month, account, category, search and selection from the URL', () => {
    const params = new URLSearchParams(
      'month=2026-09&account=visa&category=Salud&q=farmacia&tx=abc', // spanish-data
    )
    expect(parseFilters(params)).toEqual({
      month: '2026-09',
      accounts: ['visa'],
      category: 'Salud', // spanish-data
      q: 'farmacia', // spanish-data
      tx: 'abc',
      kind: null,
      group: 'day',
      sort: 'date',
      shared: null,
      provisional: false,
    })
  })

  it('reads an old category name as the current name', () => {
    // spanish-data: begin
    const params = new URLSearchParams('month=2026-09&category=Efectivo+y+transferencias')
    expect(parseFilters(params).category).toBe('Efectivo')
    // spanish-data: end
  })

  it('treats empty or missing values as no filter', () => {
    expect(parseFilters(new URLSearchParams('account=&q=%20%20'))).toEqual({
      month: null,
      accounts: null,
      category: null,
      q: '',
      tx: null,
      kind: null,
      group: 'day',
      sort: 'date',
      shared: null,
      provisional: false,
    })
  })
})

describe('accounts in the URL', () => {
  it('reads several accounts from `accounts` and the older `account` as a single one', () => {
    expect(parseFilters(new URLSearchParams('accounts=visa,bhd')).accounts).toEqual(['bhd', 'visa'])
    expect(parseFilters(new URLSearchParams('account=bhd')).accounts).toEqual(['bhd'])
  })

  it('writes `accounts` even when it came from `account`', () => {
    const params = toParams(parseFilters(new URLSearchParams('month=2026-09&account=bhd')))
    expect(params.toString()).toBe('month=2026-09&accounts=bhd')
  })
})

describe('toParams', () => {
  it('omits empty filters and keeps the order month, account, category, q, tx', () => {
    const params = toParams({
      month: '2026-09',
      accounts: null,
      category: 'Salud', // spanish-data
      q: '',
      tx: 'f',
      kind: null,
      group: 'day',
      sort: 'date',
      shared: null,
      provisional: false,
    })
    expect(params.toString()).toBe('month=2026-09&category=Salud&tx=f') // spanish-data
  })

  it('is the inverse of parseFilters', () => {
    const filters = {
      month: '2026-09',
      accounts: ['bhd', 'visa'],
      category: null,
      q: 'café', // spanish-data
      tx: null,
      kind: 'income' as const,
      group: 'merchant' as const,
      sort: 'amount' as const,
      shared: 'pending' as const,
      provisional: true,
    }
    expect(parseFilters(toParams(filters))).toEqual(filters)
    expect(toParams(filters).get('shared')).toBe('pending')
    expect(toParams(filters).get('provisional')).toBe('1')
  })
})

describe('clearFilters / hasNarrowing', () => {
  it('clears account, category and search; keeps the month and the selection', () => {
    const filters = {
      month: '2026-09',
      accounts: ['bhd'],
      category: 'Salud', // spanish-data
      q: 'x',
      tx: 'f',
      kind: 'expense' as const,
      group: 'category' as const,
      sort: 'amount' as const,
      shared: null,
      provisional: false,
    }
    expect(clearFilters(filters)).toEqual({
      month: '2026-09',
      accounts: null,
      category: null,
      q: '',
      tx: 'f',
      kind: null,
      group: 'category',
      sort: 'amount',
      shared: null,
      provisional: false,
    })
    expect(hasNarrowing(filters)).toBe(true)
    expect(hasNarrowing(clearFilters(filters))).toBe(false)
    const onlyShared = { ...clearFilters(filters), shared: 'pending' as const }
    expect(hasNarrowing(onlyShared)).toBe(true)
    expect(clearFilters(onlyShared).shared).toBeNull()
    const onlyProvisional = { ...clearFilters(filters), provisional: true }
    expect(hasNarrowing(onlyProvisional)).toBe(true)
    expect(clearFilters(onlyProvisional).provisional).toBe(false)
  })
})

describe('apiPath', () => {
  it('builds the /api/transactions query with only the filters that are set', () => {
    expect(
      apiPath('2026-09', {
        accounts: null,
        category: 'Vehículo y combustible', // spanish-data
        q: '',
        kind: null,
        shared: null,
        provisional: false,
      }),
    ).toBe('/api/transactions?month=2026-09&category=Veh%C3%ADculo+y+combustible')
    expect(
      apiPath('2026-09', { accounts: ['visa', 'bhd'], category: null, q: 'café', kind: null, shared: null, provisional: false }), // spanish-data
    ).toBe('/api/transactions?month=2026-09&accounts=visa%2Cbhd&q=caf%C3%A9')
    expect(
      apiPath('2026-09', { accounts: null, category: null, q: '', kind: null, shared: 'pending', provisional: false }),
    ).toBe('/api/transactions?month=2026-09&shared=pending')
    expect(
      apiPath('2026-09', { accounts: null, category: null, q: '', kind: null, shared: null, provisional: true }),
    ).toBe('/api/transactions?month=2026-09&provisional=true')
  })
})

describe('dayLabel', () => {
  it('gives the weekday, the day number and the month name', () => {
    expect(dayLabel('2026-09-27')).toBe('Domingo 27 de septiembre') // spanish-ui
    expect(dayLabel('2026-09-26')).toBe('Sábado 26 de septiembre') // spanish-ui
    expect(dayLabel('2026-01-05')).toBe('Lunes 5 de enero') // spanish-ui
  })
})

describe('groupByDay', () => {
  it('groups consecutive rows of the same day and keeps the order', () => {
    const a = tx({ fingerprint: 'a', day: '2026-09-29' })
    const b = tx({ fingerprint: 'b', day: '2026-09-29' })
    const c = tx({ fingerprint: 'c', day: '2026-09-27' })
    expect(groupByDay([a, b, c])).toEqual([
      { day: '2026-09-29', label: dayLabel('2026-09-29'), items: [a, b] },
      { day: '2026-09-27', label: dayLabel('2026-09-27'), items: [c] },
    ])
    expect(groupByDay([])).toEqual([])
  })
})

describe('editBody', () => {
  const row = tx()
  const unchanged = {
    category: 'Restaurantes', // spanish-data
    oneOff: false,
    scope: 'transaction',
    note: '',
  } as const

  it('sends nothing when nothing changed', () => {
    expect(editBody(row, unchanged)).toBeNull()
  })

  it('sends only the category when only the category changed', () => {
    // spanish-data: begin
    expect(editBody(row, { ...unchanged, category: 'Salud' })).toEqual({
      category: 'Salud',
      // spanish-data: end
      scope: 'transaction',
    })
  })

  it('sends only the one-off flag when only that changed', () => {
    expect(editBody(row, { ...unchanged, oneOff: true })).toEqual({
      one_off: true,
      scope: 'transaction',
    })
  })

  it('sends both with the merchant scope', () => {
    // spanish-data: begin
    expect(editBody(row, { category: 'Salud', oneOff: true, scope: 'merchant', note: '' })).toEqual({
      category: 'Salud',
      // spanish-data: end
      one_off: true,
      scope: 'merchant',
    })
  })

  it('sends the trimmed note when it changes; an empty one clears it', () => {
    // spanish-data: begin
    expect(editBody(row, { ...unchanged, note: '  con Ana ' })).toEqual({
      note: 'con Ana',
      // spanish-data: end
      scope: 'transaction',
    })
    expect(editBody(tx({ note: 'x' }), { ...unchanged, note: '' })).toEqual({
      note: '',
      scope: 'transaction',
    })
    expect(editBody(tx({ note: 'x' }), { ...unchanged, note: ' x ' })).toBeNull()
  })

  it('with the merchant scope applies the current category to the whole merchant', () => {
    expect(editBody(row, { ...unchanged, scope: 'merchant' })).toEqual({
      category: 'Restaurantes', // spanish-data
      scope: 'merchant',
    })
  })
})

describe('historyText', () => {
  it("counts the merchant's purchases in the transaction's year", () => {
    expect(historyText(tx())).toBe(t('transactions.history', { count: 3, year: '2026' }))
    expect(historyText(tx({ merchant_year_count: 1, day: '2025-12-30' }))).toBe(
      t('transactions.history', { count: 1, year: '2025' }),
    )
    expect(historyText(tx())).toBe('3 compras en 2026') // spanish-ui
  })
})

describe('merchantScopeNote', () => {
  it('a purchase says how many there were in the year', () => {
    expect(merchantScopeNote(tx())).toBe(
      t('transactions.merchantScope.withHistory', { history: historyText(tx()) }),
    )
  })

  it('a credit does not count purchases', () => {
    expect(merchantScopeNote(tx({ amount_cents: -50_000, amount_dop_cents: -50_000 }))).toBe(
      t('transactions.merchantScope.future'),
    )
  })
})

describe('oneOffBadge', () => {
  it('marks the one-off and the suggested ones, and nothing else', () => {
    expect(oneOffBadge(tx({ one_off: true }))).toBe(t('transactions.badge.oneOff'))
    expect(oneOffBadge(tx({ suggested_one_off: true, one_off_reasons: ['new merchant'] }))).toBe(
      t('transactions.badge.suggestedOneOff'),
    )
    expect(oneOffBadge(tx({ one_off: true, suggested_one_off: true }))).toBe(
      t('transactions.badge.oneOff'),
    )
    expect(oneOffBadge(tx())).toBeNull()
  })
})

describe('oneOffAction', () => {
  it('dismiss the suggested, suggest again the dismissed, nothing if already one-off', () => {
    expect(oneOffAction(tx({ suggested_one_off: true, one_off_reasons: ['new merchant'] }))).toBe(
      'dismiss',
    )
    expect(oneOffAction(tx({ one_off_dismissed: true }))).toBe('restore')
    expect(oneOffAction(tx({ one_off: true, one_off_dismissed: true }))).toBeNull()
    expect(oneOffAction(tx())).toBeNull()
  })
})

describe('totalsParts', () => {
  it('count, RD$ total and, if any, the US$ without a rate', () => {
    expect(
      totalsParts({
        items: [],
        count: 9,
        total_cents: 3_074_500,
        income_cents: 0,
        unconverted_usd_cents: 0,
      }),
    ).toEqual({
      count: t('transactions.count', { count: 9 }),
      total: 'RD$ 30,745',
      income: null,
      unconverted: null,
    })
    expect(
      totalsParts({
        items: [],
        count: 1,
        total_cents: 0,
        income_cents: 0,
        unconverted_usd_cents: 1_199,
      }),
    ).toEqual({
      count: t('transactions.count', { count: 1 }),
      total: 'RD$ 0',
      income: null,
      unconverted: t('transactions.totals.unconverted', { amount: 'US$ 11.99' }),
    })
  })
})

describe('amountLines / originText', () => {
  it('DOP: a single amount', () => {
    expect(amountLines(tx())).toEqual({ main: 'RD$ 1,980', original: null, credit: false })
    expect(originText(tx())).toBe(t('transactions.origin.dop'))
  })

  it('shared expense: your share and, below, the statement amount', () => {
    const shared = tx({ amount_cents: 61_667, amount_dop_cents: 61_667, gross_cents: 185_000 })
    expect(amountLines(shared)).toEqual({
      main: 'RD$ 617',
      original: t('transactions.amount.gross', { amount: 'RD$ 1,850' }),
      credit: false,
    })
  })

  it('converted dollars: RD$ on top and the original US$ below', () => {
    const usd = tx({ currency: 'USD', amount_cents: 1_199, amount_dop_cents: 76_017 })
    expect(amountLines(usd)).toEqual({ main: 'RD$ 760', original: 'US$ 11.99', credit: false })
    expect(originText(usd)).toBe(t('transactions.origin.converted', { amount: 'US$ 11.99' }))
  })

  it('dollars without a rate: the US$ amount and the notice', () => {
    const usd = tx({ currency: 'USD', amount_cents: 4_850, amount_dop_cents: null })
    expect(amountLines(usd)).toEqual({
      main: 'US$ 48.50',
      original: t('transactions.amount.noRate'),
      credit: false,
    })
    expect(originText(usd)).toBe(t('transactions.origin.noRate'))
  })

  it('refunds get "−" and are marked as credit', () => {
    const refund = tx({ amount_cents: -120_000, amount_dop_cents: -120_000 })
    expect(amountLines(refund)).toEqual({ main: '−RD$ 1,200', original: null, credit: true })
  })
})

describe('kind filter', () => {
  it('reads `kind` from the URL and passes it to the API', () => {
    const filters = parseFilters(new URLSearchParams('month=2026-01&kind=income'))
    expect(filters.kind).toBe('income')
    expect(toParams(filters).toString()).toBe('month=2026-01&kind=income')
    expect(apiPath('2026-01', filters)).toBe('/api/transactions?month=2026-01&kind=income')
  })

  it('ignores an unknown kind', () => {
    expect(parseFilters(new URLSearchParams('kind=other')).kind).toBeNull()
  })

  it('counts as a filter and is cleared with the others', () => {
    const filters = parseFilters(new URLSearchParams('month=2026-01&kind=transfer'))
    expect(hasNarrowing(filters)).toBe(true)
    expect(clearFilters(filters).kind).toBeNull()
  })
})

describe('totalsParts with income', () => {
  it("adds the list's income when there is some", () => {
    expect(
      totalsParts({
        items: [],
        count: 3,
        total_cents: 500_000,
        income_cents: 9_700_000,
        unconverted_usd_cents: 0,
      }).income,
    ).toBe(t('transactions.totals.income', { amount: 'RD$ 97,000' }))
  })
})

describe('kindBadge', () => {
  it('marks only what is not an expense', () => {
    expect(kindBadge(tx())).toBeNull()
    expect(kindBadge(tx({ kind: 'income' }))).toBe(t('transactions.badge.income'))
    expect(kindBadge(tx({ kind: 'transfer' }))).toBe(t('transactions.badge.transfer'))
  })
})

describe('amounts by kind', () => {
  it('income gets "+" and the income tone', () => {
    const deposit = tx({ kind: 'income', amount_cents: -1_200_000, amount_dop_cents: -1_200_000 })
    expect(amountLines(deposit)).toEqual({ main: '+RD$ 12,000', original: null, credit: false })
    expect(amountTone(deposit)).toBe('income')
  })

  it('dollar income gets "+" in the original too', () => {
    const usd = tx({
      kind: 'income',
      currency: 'USD',
      amount_cents: -10_000,
      amount_dop_cents: -634_000,
    })
    expect(amountLines(usd)).toEqual({ main: '+RD$ 6,340', original: '+US$ 100.00', credit: false })
  })

  it('dollar income without a rate: "+US$" and the notice', () => {
    const usd = tx({ kind: 'income', currency: 'USD', amount_cents: -10_000, amount_dop_cents: null })
    expect(amountLines(usd)).toEqual({
      main: '+US$ 100.00',
      original: t('transactions.amount.noRate'),
      credit: false,
    })
  })

  it('a refund keeps the credit tone and a transfer stays neutral', () => {
    const refund = tx({ amount_cents: -120_000, amount_dop_cents: -120_000 })
    expect(amountTone(refund)).toBe('credit')
    expect(amountTone(tx())).toBe('plain')
    const payment = tx({ kind: 'transfer', amount_cents: -600_000, amount_dop_cents: -600_000 })
    expect(amountLines(payment)).toEqual({ main: '−RD$ 6,000', original: null, credit: false })
    expect(amountTone(payment)).toBe('plain')
  })
})

describe('totalsParts without expenses in the list', () => {
  it('omits the expense total when there is only income', () => {
    const parts = totalsParts({
      items: [tx({ kind: 'income', amount_cents: -100, amount_dop_cents: -100 })],
      count: 1,
      total_cents: 0,
      income_cents: 100,
      unconverted_usd_cents: 0,
    })
    expect(parts.total).toBeNull()
    expect(parts.income).toBe(t('transactions.totals.income', { amount: 'RD$ 1' }))
  })

  it('with expenses in the list shows it even when zero', () => {
    const parts = totalsParts({
      items: [tx({ amount_cents: 0, amount_dop_cents: 0 })],
      count: 1,
      total_cents: 0,
      income_cents: 0,
      unconverted_usd_cents: 0,
    })
    expect(parts.total).toBe('RD$ 0')
  })
})

describe('grouping and sorting in the URL', () => {
  it('reads `group` and `sort`; missing or unknown means by day and by date', () => {
    const view = parseFilters(new URLSearchParams('group=category&sort=amount'))
    expect([view.group, view.sort]).toEqual(['category', 'amount'])
    expect(parseFilters(new URLSearchParams('group=merchant')).group).toBe('merchant')
    const unknown = parseFilters(new URLSearchParams('group=other&sort=odd'))
    expect([unknown.group, unknown.sort]).toEqual(['day', 'date'])
  })

  it('writes only what is not the default', () => {
    const base = parseFilters(new URLSearchParams('month=2026-01'))
    expect(toParams(base).toString()).toBe('month=2026-01')
    expect(toParams({ ...base, group: 'category', sort: 'amount' }).toString()).toBe(
      'month=2026-01&group=category&sort=amount',
    )
    expect(toParams({ ...base, group: 'merchant' }).toString()).toBe('month=2026-01&group=merchant')
  })

  it('does not narrow the list: not a filter and not sent to the API', () => {
    const filters = parseFilters(new URLSearchParams('month=2026-01&group=merchant&sort=amount'))
    expect(hasNarrowing(filters)).toBe(false)
    expect(apiPath('2026-01', filters)).toBe('/api/transactions?month=2026-01')
  })
})

describe('sortItems', () => {
  const small = tx({ fingerprint: 's', amount_cents: 50_000, amount_dop_cents: 50_000 })
  const big = tx({ fingerprint: 'b', amount_cents: 900_000, amount_dop_cents: 900_000 })
  const refund = tx({ fingerprint: 'r', amount_cents: -300_000, amount_dop_cents: -300_000 })
  const noRate = tx({ fingerprint: 'n', currency: 'USD', amount_cents: 99_999, amount_dop_cents: null })

  it("by date keeps the API's order", () => {
    const items = [small, big, refund]
    expect(sortItems(items, 'date')).toBe(items)
  })

  it('by amount: largest absolute RD$ value first; without a rate last', () => {
    const items = [noRate, small, refund, big]
    expect(sortItems(items, 'amount').map((t) => t.fingerprint)).toEqual(['b', 'r', 's', 'n'])
    expect(items.map((t) => t.fingerprint)).toEqual(['n', 's', 'r', 'b'])
  })

  it("for equal amounts keeps the API's order", () => {
    const a = tx({ fingerprint: 'a' })
    const b = tx({ fingerprint: 'b' })
    expect(sortItems([a, b], 'amount')).toEqual([a, b])
  })
})

describe('dayGroups', () => {
  it('by date is the same as groupByDay', () => {
    const items = [tx({ fingerprint: 'a', day: '2026-09-29' }), tx({ fingerprint: 'b' })]
    expect(dayGroups(items, 'date')).toEqual(groupByDay(items))
  })

  it('by amount sorts inside each day without mixing days', () => {
    const items = [
      tx({ fingerprint: 'a', day: '2026-09-29', amount_dop_cents: 10_000 }),
      tx({ fingerprint: 'b', day: '2026-09-29', amount_dop_cents: 70_000 }),
      tx({ fingerprint: 'c', day: '2026-09-27', amount_dop_cents: 5_000 }),
    ]
    const groups = dayGroups(items, 'amount')
    expect(groups.map((g) => g.day)).toEqual(['2026-09-29', '2026-09-27'])
    expect(groups[0].items.map((t) => t.fingerprint)).toEqual(['b', 'a'])
  })
})

describe('totalsOf', () => {
  it('sums like the header: converted expenses, positive income and US$ without a rate', () => {
    const items = [
      tx({ amount_dop_cents: 100_000 }),
      tx({ amount_cents: -20_000, amount_dop_cents: -20_000 }),
      tx({ kind: 'income', amount_cents: -500_000, amount_dop_cents: -500_000 }),
      tx({ kind: 'transfer', amount_dop_cents: 900_000 }),
      tx({ currency: 'USD', amount_cents: 1_199, amount_dop_cents: null }),
    ]
    expect(totalsOf(items)).toEqual({
      items,
      count: 5,
      total_cents: 80_000,
      income_cents: 500_000,
      unconverted_usd_cents: 1_199,
    })
  })
})

describe('fieldGroups', () => {
  // spanish-data: begin
  const lunch = tx({ fingerprint: 'l', merchant: 'Café', category: 'Restaurantes', amount_dop_cents: 30_000 })
  const dinner = tx({ fingerprint: 'd', merchant: 'Bistró', category: 'Restaurantes', amount_dop_cents: 60_000 })
  const fuel = tx({ fingerprint: 'f', merchant: 'Gasolinera', category: 'Vehículo', amount_dop_cents: 200_000 })
  const salary = tx({
    fingerprint: 's',
    merchant: 'Nómina',
    category: 'Salario',
    kind: 'income',
    amount_cents: -8_000_000,
    amount_dop_cents: -8_000_000,
  })
  const card = tx({ fingerprint: 'c', merchant: 'Pago', category: 'Pago de tarjeta', kind: 'transfer', amount_dop_cents: 999_000 })
  // spanish-data: end

  it('by category: name, count and total; largest spending first', () => {
    const groups = fieldGroups([lunch, fuel, dinner], 'category', 'date')
    expect(groups.map((g) => [g.key, g.items.map((t) => t.fingerprint)])).toEqual([
      ['Vehículo', ['f']], // spanish-data
      ['Restaurantes', ['l', 'd']], // spanish-data
    ])
    expect(groupLine(groups[1])).toBe(`${t('transactions.count', { count: 2 })} · RD$ 900`)
    expect(groupLine(groups[0])).toBe(`${t('transactions.count', { count: 1 })} · RD$ 2,000`)
    expect(groupLine(groups[1])).toBe('2 transacciones · RD$ 900') // spanish-ui
  })

  it('by merchant groups by the merchant name', () => {
    const again = tx({ fingerprint: 'l2', merchant: 'Café', amount_dop_cents: 10_000 }) // spanish-data
    const groups = fieldGroups([lunch, dinner, again], 'merchant', 'date')
    expect(groups.map((g) => g.key)).toEqual(['Bistró', 'Café']) // spanish-data
    expect(groups[1].items.map((t) => t.fingerprint)).toEqual(['l', 'l2'])
  })

  it('groups without expenses go after, by income and then by money moved', () => {
    const groups = fieldGroups([card, salary, lunch], 'category', 'date')
    expect(groups.map((g) => g.key)).toEqual(['Restaurantes', 'Salario', 'Pago de tarjeta']) // spanish-data
    const one = t('transactions.count', { count: 1 })
    expect(groupLine(groups[1])).toBe(
      `${one} · ${t('transactions.totals.income', { amount: 'RD$ 80,000' })}`,
    )
    expect(groupLine(groups[2])).toBe(one)
  })

  it('for equal RD$ spending, the group with US$ without a rate goes first', () => {
    const usd = tx({ merchant: 'App', category: 'Apps', currency: 'USD', amount_cents: 1_199, amount_dop_cents: null })
    const groups = fieldGroups([salary, usd], 'category', 'date')
    expect(groups.map((g) => g.key)).toEqual(['Apps', 'Salario']) // spanish-data
  })

  it('sorts by amount inside each group', () => {
    const groups = fieldGroups([lunch, dinner], 'category', 'amount')
    expect(groups[0].items.map((t) => t.fingerprint)).toEqual(['d', 'l'])
  })

  it('a group with US$ without a rate says so like the header', () => {
    const usd = tx({ merchant: 'App', currency: 'USD', amount_cents: 1_199, amount_dop_cents: null })
    expect(groupLine(fieldGroups([usd], 'merchant', 'date')[0])).toBe(
      [
        t('transactions.count', { count: 1 }),
        'RD$ 0',
        t('transactions.totals.unconverted', { amount: 'US$ 11.99' }),
      ].join(' · '),
    )
  })
})

describe('outOfView', () => {
  it('a row fully in view does not move; a cut or outside one does', () => {
    expect(outOfView({ top: 200, bottom: 244 }, 800)).toBe(false)
    expect(outOfView({ top: 780, bottom: 824 }, 800)).toBe(true)
    expect(outOfView({ top: 1500, bottom: 1544 }, 800)).toBe(true)
    expect(outOfView({ top: 20, bottom: 64 }, 800)).toBe(true) // under the sticky header
  })
})

describe('compactDayLabel', () => {
  it('says today and yesterday, also across a month boundary', () => {
    expect(compactDayLabel('2026-03-01', '2026-03-01')).toBe(t('transactions.day.today'))
    expect(compactDayLabel('2026-02-28', '2026-03-01')).toBe(t('transactions.day.yesterday'))
  })

  it('otherwise a short weekday, the day and a short month', () => {
    // 2024-11-12 was a Tuesday.
    const label = compactDayLabel('2024-11-12', '2026-03-01')
    expect(label).toBe(
      t('transactions.day.short', { weekday: 'mar', day: 12, month: 'nov' }),
    )
  })

  it('isoToday uses the local date', () => {
    expect(isoToday(new Date(2026, 0, 5, 23, 30))).toBe('2026-01-05')
  })
})

describe('activeFilterCount', () => {
  const base = parseFilters(new URLSearchParams())

  it('is zero with the defaults', () => {
    expect(activeFilterCount(base)).toBe(0)
  })

  it('counts kind, category, shared, grouping and sort', () => {
    expect(
      activeFilterCount({
        ...base,
        kind: 'income',
        category: 'Comida',
        shared: 'pending',
        group: 'merchant',
        sort: 'amount',
      }),
    ).toBe(5)
    // The search, the month and the accounts live outside the sheet.
    expect(activeFilterCount({ ...base, q: 'x', month: '2026-01', accounts: ['a'] })).toBe(0)
  })

  it('counts the provisional filter and reads it from the URL', () => {
    expect(base.provisional).toBe(false)
    const on = parseFilters(new URLSearchParams('provisional=1'))
    expect(on.provisional).toBe(true)
    expect(activeFilterCount(on)).toBe(1)
    expect(parseFilters(new URLSearchParams('provisional=yes')).provisional).toBe(false)
  })
})
