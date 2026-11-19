import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { monthName, monthPhrase } from './months'
import {
  afterReservesNote,
  asideNotes,
  barShare,
  bodyFromSuggestion,
  capInput,
  dueText,
  membersResultText,
  missingText,
  overviewText,
  parseDopAmount,
  scheduleMonths,
  scheduleOf,
  scheduleText,
  shiftMonth,
  spentText,
  suggestionText,
  warningText,
  yearText,
  type ReserveSuggestion,
} from './budget'

describe('budget', () => {
  it('says the spending against the cap and the width of the bar', () => {
    expect(spentText({ spent_cents: 1_200_000, cap_cents: 1_000_000 })).toBe(
      t('budget.spent.ofCap', { spent: 'RD$ 12,000', cap: 'RD$ 10,000' }),
    )
    expect(spentText({ spent_cents: 400_000, cap_cents: null })).toBe(
      t('budget.spent.noCap', { spent: 'RD$ 4,000' }),
    )
    expect(barShare({ spent_cents: 500_000, cap_cents: 1_000_000 })).toEqual({ share: 50, over: false })
    expect(barShare({ spent_cents: 1_500_000, cap_cents: 1_000_000 })).toEqual({ share: 100, over: true })
    expect(barShare({ spent_cents: 100, cap_cents: 0 })).toEqual({ share: 100, over: true })
    expect(barShare({ spent_cents: 100, cap_cents: null })).toEqual({ share: 0, over: false })
  })

  it('sets apart the one-off expenses, what is covered and what has no rate', () => {
    expect(asideNotes({ one_offs_cents: 4_500_000, covered_cents: 340_000, without_rate: 2 })).toEqual([
      t('budget.aside.oneOffs', { amount: 'RD$ 45,000' }),
      t('budget.aside.covered', { amount: 'RD$ 3,400' }),
      t('budget.aside.withoutRate', { count: 2 }),
    ])
    expect(asideNotes({ one_offs_cents: 0, covered_cents: 0, without_rate: 1 })).toEqual([
      t('budget.aside.withoutRate', { count: 1 }),
    ])
    expect(asideNotes({ one_offs_cents: 0, covered_cents: 0, without_rate: 0 })).toEqual([])
  })

  it('warns when the usual amount changed', () => {
    const warning = { habitual_cents: 2_500_000, basis_cents: 2_000_000, up: true }
    expect(warningText({ category: 'Delivery', warning, cap_cents: 2_000_000 })).toBe(
      t('budget.warning.upUpdateCap', { category: 'Delivery', amount: 'RD$ 25,000' }),
    )
    expect(warningText({ category: 'Movies', warning, cap_cents: null })).toBe(
      t('budget.warning.upSetCap', { category: 'Movies', amount: 'RD$ 25,000' }),
    )
    const down = { ...warning, up: false }
    expect(warningText({ category: 'Movies', warning: down, cap_cents: 1 })).toBe(
      t('budget.warning.downUpdateCap', { category: 'Movies', amount: 'RD$ 25,000' }),
    )
    expect(warningText({ category: 'Movies', warning: { ...down, habitual_cents: 0 }, cap_cents: 1 })).toBe(
      t('budget.warning.droppedToZero', { category: 'Movies' }),
    )
    expect(warningText({ category: 'Movies', warning: null, cap_cents: null })).toBe('')
  })

  it('reads written amounts and writes them back', () => {
    expect(parseDopAmount('16,500')).toBe(1_650_000)
    expect(parseDopAmount('RD$ 3500.5')).toBe(350_050)
    expect(parseDopAmount('')).toBeNull()
    expect(parseDopAmount('thousand')).toBeNull()
    expect(capInput(1_650_000)).toBe('16500')
    expect(capInput(null)).toBe('')
  })

  it('sums up the month for the Summary', () => {
    expect(overviewText({ over_count: 0, over_cents: 0 })).toBe(t('budget.overview.allWithin'))
    expect(overviewText({ over_count: 1, over_cents: 480_000 })).toBe(
      t('budget.overview.over', { count: 1, amount: 'RD$ 4,800' }),
    )
    expect(overviewText({ over_count: 3, over_cents: 100 })).toBe(
      t('budget.overview.over', { count: 3, amount: 'RD$ 1' }),
    )
    // With an account filter they are not counted; with partial data it does not claim "all within".
    expect(overviewText({ over_count: null, over_cents: 0 })).toBe(t('budget.overview.filtered'))
    expect(overviewText({ over_count: 0, over_cents: 0, missing: ['VISA ···4242'] })).toBe(
      t('budget.overview.noneYet'),
    )
    expect(missingText(['VISA ···4242', 'MC ···5151'])).toBe(
      t('budget.missing', { accounts: 'VISA ···4242, MC ···5151' }),
    )
    expect(missingText([])).toBeNull()
  })

  it('excess refunds go apart', () => {
    expect(
      asideNotes({ one_offs_cents: 0, covered_cents: 0, without_rate: 0, refunds_cents: 1_073_700 }),
    ).toEqual([t('budget.aside.refunds', { amount: 'RD$ 10,737' })])
  })

  it('"after setting aside" subtracts the reserves without changing the main number', () => {
    expect(afterReservesNote(1_700_000, 260_000)).toBe(
      t('budget.afterReserves', { monthly: 'RD$ 2,600', left: 'RD$ 14,400' }),
    )
    expect(afterReservesNote(100_000, 260_000)).toBe(
      t('budget.afterReserves', { monthly: 'RD$ 2,600', left: '−RD$ 1,600' }),
    )
    expect(afterReservesNote(null, 260_000)).toBeNull()
    expect(afterReservesNote(1_700_000, 0)).toBeNull()
  })
})

describe('reserves', () => {
  it('says how often it is due', () => {
    expect(scheduleText({ every_months: 12, due_month: '2027-01' })).toBe(
      t('budget.scheduleText.yearly', { month: monthName('2027-01') }),
    )
    expect(scheduleText({ every_months: 6, due_month: '2026-09' })).toBe(
      t('budget.scheduleText.halfYearly', {
        first: monthName('2026-03'),
        second: monthName('2026-09'),
      }),
    )
    expect(scheduleText({ every_months: null, due_month: '2026-12' })).toBe(
      t('budget.scheduleText.once', { month: monthPhrase('2026-12') }),
    )
    expect(scheduleText({ every_months: 3, due_month: '2026-02' })).toBe(
      t('budget.scheduleText.every', { every: 3, month: monthPhrase('2026-02') }),
    )
    expect(shiftMonth('2026-11', 3)).toBe('2027-02')
    expect(scheduleMonths('yearly')).toBe(12)
    expect(scheduleMonths('halfYearly')).toBe(6)
    expect(scheduleMonths('once')).toBeNull()
    expect(scheduleOf(6)).toBe('halfYearly')
    expect(scheduleOf(12)).toBe('yearly')
    expect(scheduleOf(null)).toBe('once')
  })

  it('says the due date and this year', () => {
    expect(dueText({ next_due: '2026-03' })).toBe(t('budget.due.in', { month: monthPhrase('2026-03') }))
    expect(dueText({ next_due: null })).toBe(t('budget.due.past'))
    expect(yearText({ year_spent_cents: 340_000, year_estimated_cents: 350_000 })).toBe(
      t('budget.year', { spent: 'RD$ 3,400', estimated: 'RD$ 3,500' }),
    )
  })

  it('builds the suggestion and the reserve it creates', () => {
    const item: ReserveSuggestion = {
      key: 'peak:Entertainment:12',
      name: 'December: Entertainment',
      amount_cents: 1_800_000,
      category_id: 7,
      category: 'Entertainment',
      due_month: '2026-12',
      every_months: 12,
      multiple: true,
      reason: 'Peak in December in 2 years (2024, 2025)',
    }
    expect(suggestionText(item)).toBe(
      t('budget.suggestion', {
        name: 'December: Entertainment',
        amount: 'RD$ 18,000',
        month: monthName('2026-12'),
      }),
    )
    expect(bodyFromSuggestion(item)).toEqual({
      name: 'December: Entertainment',
      amount_cents: 1_800_000,
      category_id: 7,
      due_month: '2026-12',
      every_months: 12,
      multiple: true,
      source: 'peak:Entertainment:12',
    })
  })

  it('says the result of linking several', () => {
    const skipped = [
      { fingerprint: 'a', reason: 'link', message: 'already in a link' },
      { fingerprint: 'b', reason: 'link', message: 'already in a link' },
    ]
    const head = t('budget.members.linked', { count: 2, name: 'Christmas' })
    expect(membersResultText({ applied: ['x', 'y'], skipped, entry_id: 3 }, 'Christmas')).toBe(
      t('budget.members.withSkipped', {
        head,
        skipped: t('budget.members.skipped', { count: 2 }),
        reasons: 'already in a link',
      }),
    )
    expect(membersResultText({ applied: ['x'], skipped: [], entry_id: 3 }, 'Christmas')).toBe(
      t('budget.members.done', { head: t('budget.members.linked', { count: 1, name: 'Christmas' }) }),
    )
    expect(membersResultText({ applied: [], skipped: [], entry_id: null }, 'Christmas')).toBe(
      t('budget.members.done', { head: t('budget.members.linked', { count: 0, name: 'Christmas' }) }),
    )
  })

  it('renders the Spanish text exactly', () => {
    expect(spentText({ spent_cents: 400_000, cap_cents: null })).toBe('RD$ 4,000 · sin presupuesto') // spanish-ui
    expect(membersResultText({ applied: ['x'], skipped: [], entry_id: 3 }, 'X')).toBe('1 vinculada a «X».') // spanish-ui
  })
})
