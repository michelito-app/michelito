import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { SharedList, SharedListExpense, SharedListGroup } from './api'
import {
  chipCounts,
  dateRange,
  emptyText,
  excessText,
  expenseState,
  filterGroups,
  groupMatches,
  groupMeta,
  moneyLine,
  noneText,
  parseChip,
  parseGroup,
  refundLabel,
  sharedFigures,
  sharedParams,
  statusText,
  withPinned,
} from './sharedList'
import { expenseCount } from './links'
import { shortDay } from './months'

const RANGE = `${shortDay('2026-02-03')} – ${shortDay('2026-02-07')} 2026`

function expense(patch: Partial<SharedListExpense> = {}): SharedListExpense {
  return {
    fingerprint: 'e1',
    day: '2026-02-03',
    merchant: 'HOTEL INVENTADO',
    account_label: 'VISA ···4242',
    amount_cents: 5950,
    currency: 'USD',
    people: 2,
    my_share_cents: null,
    for_other: false,
    share_cents: 2975,
    reimbursed_cents: 0,
    pending_cents: 2975,
    written_off_cents: 0,
    ...patch,
  }
}

function group(patch: Partial<SharedListGroup> = {}): SharedListGroup {
  return {
    id: 1,
    title: 'Trip to a made-up island',
    name: 'Trip to a made-up island',
    with_whom: 'Carola',
    status: 'pending',
    first_fingerprint: 'e1',
    first_day: '2026-02-03',
    last_day: '2026-02-07',
    last_activity: '2026-02-07',
    expenses: [expense(), expense({ fingerprint: 'e2', merchant: 'CINE FICTICIO' })],
    refunds: [],
    paid: [{ currency: 'USD', cents: 11900 }],
    reimbursed: [],
    pending: [{ currency: 'USD', cents: 2975 }],
    pending_dop_cents: 189508,
    unconverted_usd_cents: 0,
    excess: [],
    ...patch,
  }
}

const SETTLED = group({ id: 2, title: 'Luis', name: '', with_whom: 'Luis', status: 'settled' })
const LOST = group({ id: 3, title: 'Rosa', name: '', with_whom: 'Rosa', status: 'written_off' })

describe('status texts', () => {
  it('owed to you in its currency and, with US$, ≈ RD$ like Pending', () => {
    expect(statusText(group())).toEqual({
      main: t('shared.status.owed', { amount: 'US$ 29.75' }),
      approx: t('shared.approx', { amount: 'RD$ 1,895' }),
    })
    expect(statusText(group()).main).toBe('Te deben US$ 29.75') // spanish-ui
  })

  it('in RD$ there is no ≈; without a rate neither', () => {
    const dop = group({ pending: [{ currency: 'DOP', cents: 200000 }], pending_dop_cents: 200000 })
    expect(statusText(dop)).toEqual({
      main: t('shared.status.owed', { amount: 'RD$ 2,000' }),
      approx: null,
    })
    expect(statusText(group({ pending_dop_cents: null })).approx).toBeNull()
  })

  it('pending US$ without any rate: the note instead of ≈ RD$', () => {
    const none = group({ pending_dop_cents: null, unconverted_usd_cents: 2975 })
    expect(statusText(none)).toEqual({
      main: t('shared.status.owed', { amount: 'US$ 29.75' }),
      approx: t('pending.unconverted', { amount: 'US$ 29.75' }),
    })
  })

  it('without groups: no shared groups yet or none in the chosen accounts', () => {
    expect(emptyText(false)).toBe(t('shared.empty'))
    expect(emptyText(true)).toBe(t('shared.emptyChosen'))
  })

  it('settled and written off', () => {
    expect(statusText(SETTLED).main).toBe(t('shared.status.settled'))
    expect(statusText(LOST).main).toBe(t('shared.status.lost'))
  })

  it('what was paid back in excess is flagged', () => {
    expect(excessText(group())).toBeNull()
    const over = group({ excess: [{ currency: 'DOP', cents: 30000 }] })
    expect(excessText(over)).toBe(t('shared.excess', { amount: 'RD$ 300' }))
  })

  it('each expense: settled, pending or written off', () => {
    expect(expenseState(expense())).toBe(t('shared.expensePending', { amount: 'US$ 29.75' }))
    expect(expenseState(expense({ pending_cents: 0 }))).toBe(t('shared.status.settled'))
    expect(expenseState(expense({ pending_cents: 0, written_off_cents: 2975 }))).toBe(
      t('shared.status.lost'),
    )
  })

  it('the row: with whom, how many expenses, dates and what was paid', () => {
    expect(groupMeta(group())).toBe(`Carola · ${expenseCount(2)} · ${RANGE}`)
    expect(groupMeta(group())).toBe('Carola · 2 gastos · 3 feb – 7 feb 2026') // spanish-ui
    expect(groupMeta(SETTLED)).toBe(`${expenseCount(2)} · ${RANGE}`) // the title already is "Luis"
    expect(moneyLine(group())).toBe(
      t('shared.moneyLine', { paid: 'US$ 119.00', back: t('shared.moneyLine.nothingBack') }),
    )
    const back = group({ reimbursed: [{ currency: 'DOP', cents: 217500 }] })
    expect(moneyLine(back)).toBe(
      t('shared.moneyLine', {
        paid: 'US$ 119.00',
        back: t('shared.moneyLine.paidBack', { amount: 'RD$ 2,175' }),
      }),
    )
  })

  it('dates of one day, of the same year and across years', () => {
    expect(dateRange('2025-12-20', '2025-12-20')).toBe(`${shortDay('2025-12-20')} 2025`)
    expect(dateRange('2025-12-18', '2026-01-09')).toBe(
      `${shortDay('2025-12-18')} 2025 – ${shortDay('2026-01-09')} 2026`,
    )
    expect(dateRange('2025-12-18', '2026-01-09')).toBe('18 dic 2025 – 9 ene 2026') // spanish-ui
  })

  it('refunds: the credit and its account, or "By hand"', () => {
    const base = { key: 'c1', day: '2026-02-04', amount_cents: 100000, currency: 'DOP' }
    const credit = { ...base, manual: false, description: 'TOKE DE ANA', account_label: 'Acct ···2' }
    expect(refundLabel(credit)).toBe('TOKE DE ANA · Acct ···2')
    const cash = { ...base, manual: true, description: 'Marta', account_label: '' }
    expect(refundLabel(cash)).toBe(`${t('shared.refund.manual')} · Marta · ${t('shared.refund.cash')}`)
    expect(refundLabel({ ...cash, description: '', account_label: 'Bank X' })).toBe(
      `${t('shared.refund.manual')} · Bank X`,
    )
  })
})

describe('chips', () => {
  const all = [group(), SETTLED, LOST]

  it('filter by status; starts at All', () => {
    expect(parseChip(null)).toBe('all')
    expect(parseChip('something-else')).toBe('all')
    expect(parseChip('lost')).toBe('lost')
    expect(filterGroups(all, 'all', '').map((g) => g.id)).toEqual([1, 2, 3])
    expect(filterGroups(all, 'pending', '').map((g) => g.id)).toEqual([1])
    expect(filterGroups(all, 'settled', '').map((g) => g.id)).toEqual([2])
    expect(filterGroups(all, 'lost', '').map((g) => g.id)).toEqual([3])
    expect(chipCounts(all)).toEqual({ all: 3, pending: 1, settled: 1, lost: 1 })
  })

  it('the group expanded on return stays in the list even if it no longer matches, in its place', () => {
    const shown = filterGroups(all, 'settled', '')
    expect(withPinned(all, shown, 1).map((g) => g.id)).toEqual([1, 2])
    expect(withPinned(all, shown, 2).map((g) => g.id)).toEqual([2])
    expect(withPinned(all, shown, null).map((g) => g.id)).toEqual([2])
    expect(withPinned(all, shown, 99).map((g) => g.id)).toEqual([2]) // no longer exists
  })

  it('without results: "No <status> group"', () => {
    expect(noneText('settled', '')).toBe(t('shared.none.settled'))
    expect(noneText('lost', '')).toBe(t('shared.none.lost'))
    expect(noneText('pending', ' ana ')).toBe(
      t('shared.noneMatching', { none: t('shared.none.pending'), query: 'ana' }),
    )
    expect(noneText('pending', ' ana ')).toBe('Ningún grupo con pendiente coincide con «ana»') // spanish-ui
  })

  it('the chip, the search and the group go in the URL without touching the accounts', () => {
    const current = new URLSearchParams('accounts=visa')
    const next = sharedParams(current, { chip: 'settled', query: 'ana', group: 4 })
    expect(next.toString()).toBe('accounts=visa&status=settled&q=ana&group=4')
    expect(sharedParams(next, { chip: 'all', query: '', group: null }).toString()).toBe(
      'accounts=visa',
    )
    expect(parseGroup('4')).toBe(4)
    expect(parseGroup('x')).toBeNull()
  })
})

describe('search', () => {
  it('by name, "With whom" or the merchant of any expense, ignoring accents', () => {
    expect(groupMatches(group(), 'island')).toBe(true)
    expect(groupMatches(group(), 'CAROLA')).toBe(true)
    expect(groupMatches(group(), 'cine')).toBe(true)
    expect(groupMatches(group({ with_whom: 'Zoë' }), 'zoe')).toBe(true)
    expect(groupMatches(group(), 'pharmacy')).toBe(false)
  })

  it('by amount, with the picker rules', () => {
    expect(groupMatches(group(), '59.5')).toBe(true) // an expense
    expect(groupMatches(group(), 'US$ 29.75')).toBe(true) // what is pending
    expect(groupMatches(group(), '119')).toBe(true) // what was paid
    expect(groupMatches(group(), '1,000')).toBe(false)
  })

  it('combines with the chip', () => {
    expect(filterGroups([group(), SETTLED], 'settled', 'island')).toEqual([])
    expect(filterGroups([group(), SETTLED], 'all', 'luis').map((g) => g.id)).toEqual([2])
  })
})

describe('totals', () => {
  it('owed to you, what was paid back this year and the open ones; US$ without a rate apart', () => {
    const list: SharedList = {
      owed_dop_cents: 400000,
      reimbursed_year_dop_cents: 217500,
      year: 2026,
      open_count: 1,
      unconverted: { owed_usd_cents: 2975, reimbursed_usd_cents: 0 },
      rate: null,
      groups: [],
    }
    expect(sharedFigures(list)).toEqual([
      {
        key: 'owed',
        label: t('shared.figure.owed'),
        value: t('shared.approx', { amount: 'RD$ 4,000' }),
        extra: t('pending.unconverted', { amount: 'US$ 29.75' }),
      },
      {
        key: 'year',
        label: t('shared.figure.year'),
        value: t('shared.approx', { amount: 'RD$ 2,175' }),
        extra: null,
      },
      {
        key: 'open',
        label: t('shared.figure.open'),
        value: t('shared.figure.openCount', { count: 1 }),
        extra: null,
      },
    ])
    expect(sharedFigures({ ...list, open_count: 3 })[2].value).toBe(
      t('shared.figure.openCount', { count: 3 }),
    )
    expect(sharedFigures({ ...list, open_count: 1 })[2].value).toBe('1 grupo abierto') // spanish-ui
  })
})
