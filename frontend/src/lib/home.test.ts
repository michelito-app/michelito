import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import type { CategoryLine, Coverage, RecurringItem, Tx } from './api'
import type { BudgetLine } from './budget'
import {
  addDays,
  capShare,
  closestToCap,
  coveragePill,
  curvePoints,
  daysBetween,
  dueText,
  flowBar,
  fillRows,
  latest,
  OTHERS_COLOR,
  paceChange,
  parseDismissed,
  recurringSource,
  sliceHref,
  slices,
  spendingLine,
  upcoming,
  type UpcomingItem,
  visibleInvitations,
} from './home'

function coverage(key: string, complete: boolean): Coverage {
  return { key, label: key, through: complete ? null : '2026-02-10', complete }
}

describe('coverage pill', () => {
  it('counts the closed accounts', () => {
    expect(coveragePill([coverage('a', true), coverage('b', false)])).toBe(
      t('home.coverage.inProgress', { closed: 1, total: 2 }),
    )
    expect(coveragePill([coverage('a', true), coverage('b', true)])).toBe(
      t('home.coverage.allClosed', { count: 2 }),
    )
    expect(coveragePill([])).toBeNull()
  })
})

describe('month spending', () => {
  it('compares with last month at the same date', () => {
    expect(paceChange(80, 100)?.tone).toBe('less')
    expect(paceChange(80, 100)?.text).toBe(t('home.spending.less', { percent: 20 }))
    expect(paceChange(150, 100)?.text).toBe(t('home.spending.more', { percent: 50 }))
    expect(paceChange(100, 100)?.tone).toBe('same')
    expect(paceChange(100, 0)).toBeNull()
  })

  const pace = {
    through_day: 3,
    current_cents: [100, 200, 800],
    total_to_date_cents: 5800,
    previous_same_day_cents: 1000,
    previous_same_day_total_cents: 1200,
    finished: false,
  }

  it('a finished month compares month against month, not «at this date»', () => {
    expect(paceChange(80, 100, true)?.text).toBe(t('home.spending.lessWhole', { percent: 20 }))
    expect(paceChange(150, 100, true)?.text).toBe(t('home.spending.moreWhole', { percent: 50 }))
    expect(paceChange(100, 100, true)?.text).toBe(t('home.spending.sameWhole'))
    expect(spendingLine({ ...pace, finished: true }, 800, 0)).toBe(
      t('home.spending.lessWhole', { percent: 20 }),
    )
  })

  it('shows the spending without one-offs only when there were one-offs', () => {
    const line = spendingLine(pace, 5800, 5000)
    expect(line).toContain(t('home.spending.regular', { amount: 'RD$ 8' }))
    expect(line).toContain(t('home.spending.less', { percent: 20 }))
    expect(spendingLine(pace, 800, 0)).toBe(t('home.spending.less', { percent: 20 }))
  })

  it('says honestly when the month has no spending yet', () => {
    const empty = { ...pace, current_cents: [0], total_to_date_cents: 0 }
    expect(spendingLine(empty, 0, 0)).toBe(t('home.spending.empty', { amount: 'RD$ 12' }))
    expect(spendingLine({ ...empty, previous_same_day_total_cents: 0 }, 0, 0)).toBe(
      t('home.spending.emptyNoPrevious'),
    )
  })

  it('lines both curves up by day, this month only up to today', () => {
    const points = curvePoints([1, 2], [5, 6, 7], 3)
    expect(points).toEqual([
      { day: 1, current: 1, previous: 5 },
      { day: 2, current: 2, previous: 6 },
      { day: 3, current: null, previous: 7 },
    ])
  })
})

describe('flow bar', () => {
  it('splits what came in into out and kept', () => {
    expect(flowBar(100, 75)).toEqual({ out: 0.75, kept: 0.25, over: false })
  })
  it('marks spending more than what came in', () => {
    expect(flowBar(50, 100)).toEqual({ out: 1, kept: 0.5, over: true })
    expect(flowBar(0, 0)).toEqual({ out: 0, kept: 0, over: false })
  })
})

function budgetLine(category: string, spent: number, cap: number | null): BudgetLine {
  return {
    category_id: category.length,
    category,
    cap_cents: cap,
    manual: false,
    spent_cents: spent,
    one_offs_cents: 0,
    covered_cents: 0,
    without_rate: 0,
    over_cents: Math.max(0, spent - (cap ?? 0)),
    passed: false,
    refunds_cents: 0,
    habitual_cents: null,
    warning: null,
    active: true,
  }
}

describe('budget', () => {
  it('takes the three closest to their cap', () => {
    const lines = [
      budgetLine('a', 10, 100),
      budgetLine('bb', 90, 100),
      budgetLine('ccc', 120, 100),
      budgetLine('dddd', 50, 100),
      budgetLine('eeeee', 999, null),
    ]
    expect(closestToCap(lines).map((l) => l.category)).toEqual(['ccc', 'bb', 'dddd'])
    expect(capShare(lines[2])).toBe(100)
    expect(capShare(lines[0])).toBe(10)
  })
})

function recurring(overrides: Partial<RecurringItem>): RecurringItem {
  return {
    merchant: 'STREAMING FICTICIO',
    currency: 'DOP',
    category: 'Subscriptions',
    group: 'Subscriptions',
    cadence: 'monthly',
    status: 'active',
    typical_cents: 50000,
    variable: false,
    monthly_cents: 50000,
    yearly_cents: 600000,
    first_day: '2025-12-05',
    last_day: '2026-02-05',
    charges: 3,
    price_change: null,
    installments_left: null,
    mark: null,
    charged_after_cancel: false,
    name: 'Streaming',
    members: ['STREAMING FICTICIO'],
    provider: false,
    extras_year_cents: 0,
    group_key: 'subscriptions',
    ...overrides,
  }
}

describe('upcoming', () => {
  it('adds and counts days', () => {
    expect(addDays('2026-02-26', 7)).toBe('2026-03-05')
    expect(daysBetween('2026-02-26', '2026-03-01')).toBe(3)
    expect(dueText('2026-02-26', '2026-02-26')).toBe(t('home.upcoming.today'))
    expect(dueText('2026-02-26', '2026-02-27')).toBe(t('home.upcoming.tomorrow'))
    expect(dueText('2026-02-26', '2026-03-01')).toBe(t('home.upcoming.inDays', { count: 3 }))
  })

  it('keeps what is due within 7 days, from every source, nearest first', () => {
    const items = [
      recurring({ name: 'Soon', merchant: 'A', last_day: '2026-02-03' }),
      recurring({ name: 'Later', merchant: 'B', last_day: '2026-02-25' }),
      recurring({ name: 'Paused', merchant: 'C', last_day: '2026-02-01', status: 'cancelled' }),
    ]
    const extra: UpcomingItem = {
      key: 'other',
      name: 'Other source',
      day: '2026-03-02',
      amount: 'RD$ 1',
      href: '/x',
    }
    const found = upcoming([recurringSource(items, '/recurring'), () => [extra]], '2026-02-28')
    expect(found.map((i) => [i.name, i.day])).toEqual([
      ['Other source', '2026-03-02'],
      ['Soon', '2026-03-03'],
    ])
  })
})

describe('latest transactions', () => {
  it('takes the newest five', () => {
    const txs = ['2026-02-01', '2026-02-09', '2026-02-03', '2026-02-07', '2026-02-05', '2026-02-02'].map(
      (day) => ({ day, fingerprint: day }) as Tx,
    )
    expect(latest(txs).map((tx) => tx.day)).toEqual([
      '2026-02-09',
      '2026-02-07',
      '2026-02-05',
      '2026-02-03',
      '2026-02-02',
    ])
  })
})

function category(name: string, cents: number): CategoryLine {
  return {
    category: name,
    amount_cents: cents,
    habitual_cents: null,
    diff_cents: null,
    same: false,
    share: 0,
    one_offs_cents: 0,
    purchases: 1,
    habitual_purchases: null,
  }
}

describe('categories donut', () => {
  it('shows the top five and the rest as «Others»', () => {
    const lines = ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map((name, i) => category(name, 700 - i * 100))
    lines.push(category('refund', -50))
    const found = slices(lines)
    expect(found.map((s) => s.label)).toEqual(['a', 'b', 'c', 'd', 'e', t('home.categories.others')])
    expect(found[5]).toMatchObject({ cents: 300, color: OTHERS_COLOR, category: null })
    expect(found.reduce((sum, s) => sum + s.share, 0)).toBeCloseTo(1)
  })

  it('leads each slice to its category in the month', () => {
    const [first, others] = slices([...['a', 'b', 'c', 'd', 'e'].map((n) => category(n, 10)), category('f', 1)]).filter(
      (s, i) => i === 0 || s.category === null,
    )
    expect(sliceHref(first, '2026-02', ['k1'])).toBe(
      '/transactions?month=2026-02&category=a&kind=expense&accounts=k1',
    )
    expect(sliceHref(others, '2026-02', null)).toBe('/transactions?month=2026-02&kind=expense&group=category')
  })

  it('is empty without spending', () => {
    expect(slices([category('a', 0)])).toEqual([])
  })
})

describe('the grid', () => {
  it('stretches a card over what its row leaves empty, so no row has a hole', () => {
    // spending (2) + flow | invitations (row) | review, upcoming, latest | shared, categories
    const spans = [2, 1, Infinity, 1, 1, 1, 1, 1]
    expect(fillRows(spans, 3)).toEqual([2, 1, 3, 1, 1, 1, 1, 2])
    // Two columns: flow is alone before the invitations' row, and so is the last card.
    expect(fillRows(spans, 2)).toEqual([2, 2, 2, 1, 1, 1, 1, 2])
    expect(fillRows([2, 1, 1, 1], 3)).toEqual([2, 1, 1, 2])
    expect(fillRows([1, 1, 1], 3)).toEqual([1, 1, 1])
    expect(fillRows([2, 1], 1)).toEqual([1, 1])
  })
})

describe('invitations', () => {
  it('shows at most two, by usefulness, skipping the dismissed ones', () => {
    const all = new Set(['budget', 'recurring', 'shared'] as const)
    expect(visibleInvitations(all, [])).toEqual(['budget', 'recurring'])
    expect(visibleInvitations(all, ['budget'])).toEqual(['recurring', 'shared'])
    expect(visibleInvitations(new Set(['shared'] as const), [])).toEqual(['shared'])
  })

  it('reads only known dismissed invitations', () => {
    expect(parseDismissed('["budget","nope",3]')).toEqual(['budget'])
    expect(parseDismissed('not json')).toEqual([])
    expect(parseDismissed('{}')).toEqual([])
    expect(parseDismissed(null)).toEqual([])
  })
})
