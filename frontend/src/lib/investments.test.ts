import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { Investment, InvestmentEntry, InvestmentList, Tx } from './api'
import {
  chipCounts,
  entryRole,
  excessWarning,
  filterInvestments,
  investedNote,
  investmentFigures,
  investmentMeta,
  investmentParams,
  investmentStats,
  noneText,
  parseChip,
  parseOpen,
  rateText,
  roleBody,
  unconvertedWarning,
  withPinned,
} from './investments'
import {
  categoryLocked,
  linkBadges,
  linkSummaries,
  listPath,
  ROLE_LABELS,
  showInvestment,
} from './links'
import { dateRange } from './sharedList'

function entry(overrides: Partial<InvestmentEntry> = {}): InvestmentEntry {
  return {
    fingerprint: 'a1',
    day: '2025-12-02',
    merchant: 'MB A 0000000066',
    description: 'MB a 0000000066 PEDRO INVERSOR FICTICIO',
    account_label: 'Savings ···888',
    role: 'contribution',
    amount_cents: 30_000_000,
    currency: 'DOP',
    capital_cents: 0,
    return_cents: 0,
    excess_cents: 0,
    counted: true,
    ...overrides,
  }
}

function investment(overrides: Partial<Investment> = {}): Investment {
  return {
    id: 1,
    title: 'Pedro’s business',
    name: 'Pedro’s business',
    with_whom: 'Pedro',
    status: 'active',
    currency: 'DOP',
    first_fingerprint: 'a1',
    pending_cents: 25_000_000,
    written_off: false,
    first_day: '2025-12-02',
    last_activity: '2025-12-29',
    last_credit: '2025-12-29',
    contributed_cents: 30_000_000,
    capital_returned_cents: 5_000_000,
    returns_cents: 1_900_000,
    excess_cents: 0,
    annual_rate: 0.125,
    pending_dop_cents: 25_000_000,
    unconverted_count: 0,
    entries: [
      entry(),
      entry({
        fingerprint: 'm1',
        day: '2025-12-29',
        merchant: 'TRANSF PEDRO INVERSOR',
        role: 'mixed',
        amount_cents: 6_000_000,
        capital_cents: 5_000_000,
        return_cents: 1_000_000,
      }),
    ],
    ...overrides,
  }
}

const closed = investment({
  id: 2,
  title: 'Loan to Zoë',
  name: 'Loan to Zoë',
  with_whom: 'Zoë',
  status: 'closed',
  pending_cents: 0,
  contributed_cents: 5_000_000,
  capital_returned_cents: 5_000_000,
  returns_cents: 200_000,
  entries: [entry({ fingerprint: 'l1', merchant: 'MB A 0000000077', amount_cents: 5_000_000 })],
})
const lost = investment({ id: 3, title: 'Crypto', with_whom: '', status: 'written_off' })

describe('chips and search', () => {
  it('the URL picks the chip (by default "Active") and the expanded one', () => {
    expect(parseChip(null)).toBe('active')
    expect(parseChip('closed')).toBe('closed')
    expect(parseChip('all')).toBe('all')
    expect(parseChip('other')).toBe('active')
    expect(parseOpen('12')).toBe(12)
    expect(parseOpen('x')).toBeNull()
  })

  it('"Closed" gathers the closed and the written-off ones', () => {
    const all = [investment(), closed, lost]
    expect(filterInvestments(all, 'active', '').map((i) => i.id)).toEqual([1])
    expect(filterInvestments(all, 'closed', '').map((i) => i.id)).toEqual([2, 3])
    expect(chipCounts(all)).toEqual({ active: 1, closed: 2, all: 3 })
  })

  it('searches by name, with whom, merchant or amount, ignoring accents', () => {
    const all = [investment(), closed]
    expect(filterInvestments(all, 'all', 'zoe').map((i) => i.id)).toEqual([2])
    expect(filterInvestments(all, 'all', 'pedro').map((i) => i.id)).toEqual([1])
    expect(filterInvestments(all, 'all', '300,000').map((i) => i.id)).toEqual([1])
    expect(noneText('active', 'zzz')).toBe(
      t('investments.noneMatching', { none: t('investments.none.active'), query: 'zzz' }),
    )
    expect(noneText('active', 'zzz')).toBe('Ninguna inversión activa coincide con «zzz»') // spanish-ui
    expect(noneText('closed', '')).toBe(t('investments.none.closed'))
  })

  it('the expanded one stays in the list on return even if it does not match', () => {
    const all = [investment(), closed]
    expect(withPinned(all, [investment()], 2).map((i) => i.id)).toEqual([1, 2])
    expect(withPinned(all, [investment()], null).map((i) => i.id)).toEqual([1])
  })

  it('the params drop the default values and keep the accounts', () => {
    const current = new URLSearchParams('accounts=a&status=closed')
    expect(investmentParams(current, { chip: 'active', open: 2 }).toString()).toBe(
      'accounts=a&investment=2',
    )
    expect(investmentParams(current, { chip: 'all', query: 'x' }).toString()).toBe(
      'accounts=a&status=all&q=x',
    )
  })
})

describe('texts', () => {
  it('the figures are in the investment currency and the % with one decimal', () => {
    const stats = Object.fromEntries(investmentStats(investment()).map((s) => [s.key, s.value]))
    expect(stats).toEqual({
      contributed: 'RD$ 300,000',
      returned: 'RD$ 50,000',
      pending: 'RD$ 250,000',
      returns: 'RD$ 19,000',
      rate: '12.5 %',
    })
    expect(rateText(null)).toBe('—')
    expect(rateText(0)).toBe('0.0 %')
  })

  it('the dates line says with whom, since when and the last payment', () => {
    const last = t('investments.meta.lastCredit', { day: dateRange('2025-12-29', '2025-12-29') })
    expect(investmentMeta(investment())).toBe(
      `Pedro · ${dateRange('2025-12-02', '2025-12-29')} · ${last}`,
    )
    expect(investmentMeta(investment())).toBe(
      'Pedro · 2 dic – 29 dic 2025 · último cobro 29 dic 2025', // spanish-ui
    )
    expect(investmentMeta(investment({ last_credit: null }))).toBe(
      `Pedro · ${dateRange('2025-12-02', '2025-12-29')} · ${t('investments.meta.noCredits')}`,
    )
  })

  it('a mixed one says how much is capital and how much return', () => {
    expect(entryRole(investment().entries[1])).toBe(
      t('investments.entry.mixed', { capital: 'RD$ 50,000', returns: 'RD$ 10,000', extra: '' }),
    )
    expect(entryRole(entry({ role: 'return' }))).toBe(ROLE_LABELS.return)
  })

  it('warns about capital returned in excess: it counts as a return', () => {
    expect(excessWarning(investment())).toBeNull()
    expect(excessWarning(investment({ excess_cents: 5_000_000 }))).toBe(
      t('investments.excessWarning', { amount: 'RD$ 50,000' }),
    )
    expect(entryRole(entry({ role: 'capital', excess_cents: 5_000_000 }))).toBe(
      ROLE_LABELS.capital + t('investments.entry.excess', { amount: 'RD$ 50,000' }),
    )
  })

  it('warns about what does not add up for lack of a rate', () => {
    expect(unconvertedWarning(investment())).toBeNull()
    expect(unconvertedWarning(investment({ unconverted_count: 2 }))).toBe(
      t('investments.unconvertedWarning', { count: 2 }),
    )
    expect(unconvertedWarning(investment({ unconverted_count: 1 }))).toBe(
      t('investments.unconvertedWarning', { count: 1 }),
    )
  })

  it('the figures on top are in ≈ RD$ and US$ without a rate apart', () => {
    const list: InvestmentList = {
      pending_dop_cents: 25_000_000,
      returns_year_dop_cents: 2_100_000,
      year: 2026,
      active_count: 1,
      unconverted: { pending_usd_cents: 0, returns_usd_cents: 1_000 },
      rate: null,
      investments: [investment()],
    }
    expect(investmentFigures(list).map((f) => [f.value, f.extra])).toEqual([
      [t('investments.figure.approx', { amount: 'RD$ 250,000' }), null],
      [
        t('investments.figure.approx', { amount: 'RD$ 21,000' }),
        t('pending.unconverted', { amount: 'US$ 10.00' }),
      ],
      [t('investments.figure.activeCount', { count: 1 }), null],
    ])
  })

  it('the Summary line only shows with contributions in the month', () => {
    expect(investedNote(0)).toBeNull()
    expect(investedNote(30_000_000)).toBe(t('investments.investedNote', { amount: 'RD$ 300,000' }))
  })
})

describe('credit role', () => {
  it('a mixed one needs 0 < capital < credit', () => {
    expect(roleBody('return', '', 6_000_000)).toEqual({ body: { role: 'return' } })
    expect(roleBody('mixed', '50,000', 6_000_000)).toEqual({
      body: { role: 'mixed', capital_cents: 5_000_000 },
    })
    expect(roleBody('mixed', '60000', 6_000_000)).toEqual({
      error: t('investments.role.capitalTooBig'),
    })
    expect(roleBody('mixed', '0', 6_000_000)).toEqual({ error: t('investments.role.capitalMissing') })
    expect(roleBody('mixed', 'abc', 6_000_000)).toEqual({
      error: t('investments.role.capitalMissing'),
    })
  })
})

function tx(overrides: Partial<Tx>): Tx {
  return {
    link: '',
    can_share: false,
    can_reimburse: false,
    can_exchange: false,
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
    shared: null,
    exchange: null,
    suggested_group: null,
    suggested_exchange_with: null,
    pending_cents: 0,
    ...overrides,
  } as Tx
}

describe('the row and the detail', () => {
  it('a debit offers "It is an investment…" and a credit "It is from an investment…"', () => {
    const [debit] = linkSummaries(tx({ can_invest: true }))
    expect([debit.kind, debit.action]).toEqual(['investment', 'Es una inversión…']) // spanish-ui
    const [credit] = linkSummaries(tx({ can_invest_credit: true }))
    expect(credit.action).toBe('Es de una inversión…') // spanish-ui
    expect(showInvestment(tx({}))).toBe(false)
  })

  it('a linked one says its role, is managed and its category is set by the link', () => {
    const ref = { ...investment(), kind: 'possible_return' as const }
    const linked = tx({ link: 'investment', investment: ref, investment_role: 'mixed' })
    const [summary] = linkSummaries(linked)
    expect([summary.text, summary.action]).toEqual(['Mixto de Pedro’s business', 'Gestionar…']) // spanish-ui
    expect(categoryLocked(linked)).toBe(true)
    expect(linkBadges(linked).map((b) => b.label)).toEqual(['Inversión']) // spanish-ui
    expect(linkBadges(tx({ suggested_investment: ref })).map((b) => b.label)).toEqual([
      '¿Inversión?', // spanish-ui
    ])
  })

  it('"Back" returns to Investments as it was', () => {
    expect(listPath('/investments?status=closed&investment=2')).toBe(
      '/investments?status=closed&investment=2',
    )
  })
})
