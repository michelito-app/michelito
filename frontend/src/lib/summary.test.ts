import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import { THIRD_PARTY } from './categories'
import type { AccountTotal, CategoryLine, Change, MonthTotal, Rate } from './api'
import { longDay, monthName, monthPhrase, shortDay } from './months'
import {
  provisionalNote,
  accountNote,
  barWidth,
  byMovement,
  categoryDiff,
  changeDetail,
  changeTitle,
  coverageText,
  oneOffsText,
  partialNote,
  parseRate,
  rateNote,
  rateText,
  netDetail,
  netText,
  netTone,
  NO_FLOW_NOTE,
  ownMovesNote,
  spendingHref,
  thirdPartyHref,
  thirdPartyNote,
  incomeThroughNote,
  savingsNote,
  savingsText,
  splitTop,
  trendIncomeNote,
  trendMonthAt,
  trendSummary,
  versusHabitual,
} from './summary'

function line(overrides: Partial<CategoryLine>): CategoryLine {
  return {
    category: 'Supermercado', // spanish-data
    amount_cents: 3420000,
    habitual_cents: 3290000,
    diff_cents: 130000,
    same: false,
    share: 0.23,
    one_offs_cents: 0,
    purchases: 10,
    habitual_purchases: 10,
    ...overrides,
  }
}

function change(overrides: Partial<Change>): Change {
  return {
    category: 'Delivery',
    diff_cents: 440000,
    one_offs_cents: 0,
    purchases: 14,
    habitual_purchases: 8,
    ...overrides,
  }
}

/** A complete month of the trend, without atypical-month flags. */
function point(month: string, label: string, totalCents: number, incomeCents: number): MonthTotal {
  return {
    month,
    label,
    total_cents: totalCents,
    income_cents: incomeCents,
    partial: false,
    spent_flag: null,
    spent_habitual_cents: null,
    income_flag: null,
    income_habitual_cents: null,
  }
}

const RATE: Rate = { value: '63.4000', month_used: '2026-09', source: 'bcrd' }

describe('categoryDiff', () => {
  it('goes up in orange and down in blue', () => {
    expect(categoryDiff(line({}))).toEqual({ tone: 'up', text: '+RD$ 1,300' })
    expect(categoryDiff(line({ diff_cents: -255000 }))).toEqual({ tone: 'down', text: '−RD$ 2,550' })
  })
  it('"same" when the API marks it as same', () => {
    expect(categoryDiff(line({ diff_cents: 20000, same: true }))).toEqual({
      tone: 'same',
      text: t('summary.diff.same'),
    })
  })
  it('"—" in an incomplete month (no usual)', () => {
    expect(categoryDiff(line({ diff_cents: null, habitual_cents: null }))).toEqual({
      tone: 'none',
      text: '—',
    })
  })
  it('"new" when there was no spending in the category before', () => {
    const fresh = line({ amount_cents: 7547600, habitual_cents: 0, diff_cents: 7547600 })
    expect(categoryDiff(fresh)).toEqual({ tone: 'up', text: t('summary.diff.new') })
    expect(categoryDiff({ ...fresh, one_offs_cents: 7547600 }).text).toBe(
      t('summary.diff.oneOff', { text: t('summary.diff.new') }),
    )
  })
  it('marks the rises that bring a one-off expense', () => {
    expect(categoryDiff(line({ diff_cents: 1150000, one_offs_cents: 1250000 })).text).toBe(
      t('summary.diff.oneOff', { text: '+RD$ 11,500' }),
    )
  })
})

describe('barWidth', () => {
  it('scales against the largest category', () => {
    expect(barWidth(500, 1000)).toBe(50)
    expect(barWidth(1000, 1000)).toBe(100)
  })
  it('stays within 0..100 even with refunds', () => {
    expect(barWidth(-300, 1000)).toBe(0)
    expect(barWidth(1500, 1000)).toBe(100)
    expect(barWidth(500, 0)).toBe(0)
  })
})

describe('versusHabitual', () => {
  it('says how much more or less than usual', () => {
    expect(versusHabitual(14832000, 13490000)).toEqual({
      tone: 'up',
      text: t('summary.versus.more', { amount: 'RD$ 13,420' }),
    })
    expect(versusHabitual(12000000, 13490000)).toEqual({
      tone: 'down',
      text: t('summary.versus.less', { amount: 'RD$ 14,900' }),
    })
  })
  it('"about the same" within max(RD$ 500, 5 %)', () => {
    expect(versusHabitual(13582000, 13490000)).toEqual({
      tone: 'same',
      text: t('summary.versus.same', { habitual: 'RD$ 134,900' }),
    })
    expect(versusHabitual(140000, 100000)).toEqual({
      tone: 'same',
      text: t('summary.versus.same', { habitual: 'RD$ 1,000' }),
    })
  })
})

describe('changeTitle / changeDetail', () => {
  it('titles with the category and the difference in RD$', () => {
    expect(changeTitle(change({}))).toBe('Delivery +RD$ 4,400')
    expect(changeTitle(change({ category: 'Home', diff_cents: -255000 }))).toBe(
      'Home −RD$ 2,550',
    )
  })
  it('explains the one-off expense first', () => {
    expect(changeDetail(change({ one_offs_cents: 1250000 }))).toBe(
      t('summary.change.oneOff', { amount: 'RD$ 12,500' }),
    )
  })
  it('compares the number of purchases', () => {
    expect(changeDetail(change({}))).toBe(
      t('summary.change.purchasesVsHabitual', {
        purchases: t('summary.purchases', { count: 14 }),
        habitual: 8,
      }),
    )
    expect(changeDetail(change({ purchases: 1, habitual_purchases: 3 }))).toBe(
      t('summary.change.purchasesVsHabitual', {
        purchases: t('summary.purchases', { count: 1 }),
        habitual: 3,
      }),
    )
    expect(t('summary.purchases', { count: 1 })).not.toBe(t('summary.purchases', { count: 14 }).replace('14', '1'))
    expect(changeDetail(change({ purchases: 0, diff_cents: -1000 }))).toBe(
      t('summary.change.noPurchases'),
    )
  })
  it('with the same purchases it talks about the amount', () => {
    expect(changeDetail(change({ purchases: 8 }))).toBe(t('summary.change.sameMore'))
    expect(changeDetail(change({ purchases: 8, diff_cents: -1000 }))).toBe(
      t('summary.change.sameLess'),
    )
  })
})

describe('coverageText', () => {
  it('says whether the account covers the month or how far it reaches', () => {
    expect(coverageText({ key: 'a', label: 'A', through: '2026-10-31', complete: true })).toBe(
      t('summary.coverage.complete'),
    )
    expect(coverageText({ key: 'a', label: 'A', through: '2026-10-13', complete: false })).toBe(
      t('summary.coverage.through', { day: shortDay('2026-10-13') }),
    )
    expect(coverageText({ key: 'a', label: 'A', through: null, complete: false })).toBe(
      t('summary.coverage.noData'),
    )
  })
})

describe('rateText / rateNote', () => {
  it('shows the rate with 2 to 4 decimals', () => {
    expect(rateText('63.4000')).toBe('63.40')
    expect(rateText('63.4512')).toBe('63.4512')
  })
  it('warns when the rate is from another month', () => {
    expect(rateNote(RATE, '2026-09')).toBeNull()
    expect(rateNote({ ...RATE, month_used: '2026-08' }, '2026-09')).toBe(
      t('summary.rate.otherMonth', { month: monthName('2026-08') }),
    )
  })
})

describe('parseRate', () => {
  it('accepts positive numbers with up to 4 decimals', () => {
    expect(parseRate(' 63.4 ')).toBe('63.4')
    expect(parseRate('63,45')).toBe('63.45')
    expect(parseRate('64')).toBe('64')
  })
  it('rejects empty, zero, negative and text', () => {
    expect(parseRate('')).toBeNull()
    expect(parseRate('0')).toBeNull()
    expect(parseRate('0.0000')).toBeNull()
    expect(parseRate('-5')).toBeNull()
    expect(parseRate('abc')).toBeNull()
    expect(parseRate('63.12345')).toBeNull()
  })
})

describe('accountNote', () => {
  const account: AccountTotal = { key: 'k', label: 'Visa', total_cents: 1978000, usd_cents: 0 }
  it('RD$ only', () => {
    expect(accountNote(account, RATE)).toBe('RD$')
  })
  it('with dollars it says at which rate, or that there is none', () => {
    expect(accountNote({ ...account, usd_cents: 31200 }, RATE)).toBe(
      t('summary.account.withRate', { usd: 'US$ 312.00', rate: '63.40' }),
    )
    expect(accountNote({ ...account, usd_cents: 31200 }, null)).toBe(
      t('summary.account.noRate', { usd: 'US$ 312.00' }),
    )
  })
})

describe('trendSummary', () => {
  const trend: MonthTotal[] = [
    point('2026-07', 'jul', 9_000_000, 0),
    point('2026-08', 'ago', 8_700_000, 0),
    point('2026-09', 'sep', 9_700_000, 15_000_000),
    point('2026-10', 'oct', 9_900_000, 0),
  ]
  const range = t('summary.trend.range', {
    from: monthPhrase('2026-07'),
    to: monthPhrase('2026-10'),
  })
  const chosen = (month: string, amount: string, rank: string) =>
    t('summary.trend.chosen', { range, month: monthName(month), amount, rank })
  it('summarises the range and the position of the chosen month', () => {
    expect(trendSummary(trend, '2026-09')).toBe(
      chosen('2026-09', 'RD$ 97,000', t('summary.trend.rank.second')),
    )
    expect(trendSummary(trend, '2026-10')).toBe(
      chosen('2026-10', 'RD$ 99,000', t('summary.trend.rank.highest')),
    )
    expect(trendSummary(trend, '2026-08')).toBe(
      chosen('2026-08', 'RD$ 87,000', t('summary.trend.rank.lowest')),
    )
    expect(trendSummary(trend, '2026-07')).toBe(
      chosen('2026-07', 'RD$ 90,000', t('summary.trend.rank.third')),
    )
  })
  it('with a single month it does not compare', () => {
    expect(trendSummary(trend.slice(0, 1), '2026-07')).toBe(
      t('summary.trend.single', { month: monthPhrase('2026-07'), amount: 'RD$ 90,000' }),
    )
  })
})

describe('oneOffsText', () => {
  const lines = [
    line({ category: 'Health', one_offs_cents: 1250000 }),
    line({ category: 'Home', one_offs_cents: 0 }),
    line({ category: 'Travel', one_offs_cents: 300000 }),
  ]
  it('names the categories with one-off expenses', () => {
    expect(oneOffsText(lines.slice(0, 2))).toBe(t('summary.oneOffs.in', { names: 'Health' }))
    expect(oneOffsText(lines)).toBe(
      t('summary.oneOffs.in', { names: t('summary.list.and', { head: 'Health', last: 'Travel' }) }),
    )
    expect(oneOffsText([...lines, line({ category: 'Clothes', one_offs_cents: 1 })])).toBe(
      t('summary.oneOffs.many', { count: 3 }),
    )
  })
  it('without one-off expenses there is no text', () => {
    expect(oneOffsText([lines[1]])).toBeNull()
  })
})

describe('partialNote', () => {
  it('says how far each account that does not cover the month reaches', () => {
    expect(
      partialNote('October 2026', [
        { key: 'a', label: 'Visa ···1234', through: '2026-10-31', complete: true },
        { key: 'b', label: 'MC ···5151', through: '2026-10-13', complete: false },
        { key: 'c', label: 'Savings ···1', through: null, complete: false },
      ]),
    ).toBe(
      t('summary.partial.noteWithDetail', {
        label: 'October 2026',
        detail: t('summary.list.and', {
          head: t('summary.partial.through', { account: 'MC ···5151', day: longDay('2026-10-13') }),
          last: t('summary.partial.noData', { account: 'Savings ···1' }),
        }),
      }),
    )
  })
  it('without accounts missing it is the bare notice', () => {
    expect(partialNote('October 2026', [])).toBe(
      t('summary.partial.note', { label: 'October 2026' }),
    )
  })
})

describe('trendMonthAt', () => {
  const trend: MonthTotal[] = [
    point('2026-08', 'ago', 8_700_000, 0),
    point('2026-09', 'sep', 9_700_000, 0),
  ]
  it('returns the month of the clicked bar', () => {
    expect(trendMonthAt(trend, 1)).toBe('2026-09')
    expect(trendMonthAt(trend, '0')).toBe('2026-08')
  })
  it('ignores clicks outside the bars', () => {
    expect(trendMonthAt(trend, undefined)).toBeNull()
    expect(trendMonthAt(trend, 5)).toBeNull()
    expect(trendMonthAt(trend, 'x')).toBeNull()
  })
})

describe('savingsText', () => {
  it('rounds to a whole percentage', () => {
    expect(savingsText(0.8375)).toBe('84 %')
    expect(savingsText(0)).toBe('0 %')
  })
  it('a month in the red gives a negative percentage', () => {
    expect(savingsText(-0.25)).toBe('−25 %')
  })
  it('without income: "—"', () => {
    expect(savingsText(null)).toBe('—')
  })
})

describe('incomeThroughNote', () => {
  it('says through which day the income is known', () => {
    expect(incomeThroughNote('2026-01-15')).toBe(
      t('summary.income.through', { day: shortDay('2026-01-15') }),
    )
  })
  it('without a cut-off, nothing', () => {
    expect(incomeThroughNote(null)).toBeNull()
  })
})

describe('savingsNote', () => {
  it('with complete income it explains the percentage', () => {
    expect(savingsNote(0.5, null)).toBe(t('summary.savings.note'))
  })
  it('without income it is not computed', () => {
    expect(savingsNote(null, null)).toBe(t('summary.savings.noIncome'))
  })
  it('with incomplete income neither, and it says through when', () => {
    expect(savingsNote(null, '2026-01-15')).toBe(
      t('summary.savings.incomeThrough', { day: shortDay('2026-01-15') }),
    )
  })
})

describe('netTone / netDetail', () => {
  it('what was left is good when not negative', () => {
    expect(netTone(0)).toBe('good')
    expect(netTone(100)).toBe('good')
    expect(netTone(-1)).toBe('up')
  })
  it('explains the figure', () => {
    expect(netDetail(500_000)).toBe(t('summary.net.incomeLessSpending'))
    expect(netDetail(-500_000)).toBe(t('summary.net.overspent', { amount: 'RD$ 5,000' }))
  })
  it('names the third-party transfers when there were any', () => {
    expect(netDetail(500_000, 120_000)).toBe(t('summary.net.lessThirdParty'))
    expect(netDetail(500_000, 0)).toBe(t('summary.net.incomeLessSpending'))
    expect(netDetail(-500_000, 120_000)).toBe(t('summary.net.overSent', { amount: 'RD$ 5,000' }))
  })
})

describe('spendingHref', () => {
  it('goes to the month\'s expenses in Transactions, grouped by category', () => {
    const href = spendingHref('2026-09')
    expect(href.startsWith('/transactions?')).toBe(true)
    const params = new URLSearchParams(href.split('?')[1])
    expect(params.get('month')).toBe('2026-09')
    expect(params.get('kind')).toBe('expense')
    expect(params.get('group')).toBe('category')
    expect(params.has('accounts')).toBe(false)
  })
  it('keeps the chosen accounts', () => {
    const params = new URLSearchParams(spendingHref('2026-09', ['bhd:1']).split('?')[1])
    expect(params.get('accounts')).toBe('bhd:1')
  })
})

describe('thirdPartyHref / thirdPartyNote', () => {
  it('goes to Transactions filtered by the category and the month', () => {
    const href = thirdPartyHref('2026-09')
    expect(href.startsWith('/transactions?')).toBe(true)
    const params = new URLSearchParams(href.split('?')[1])
    expect(params.get('month')).toBe('2026-09')
    expect(params.get('category')).toBe(THIRD_PARTY)
  })
  it('explains it is not spending, or that there was none', () => {
    expect(thirdPartyNote(120_000)).toBe(t('summary.thirdParty.note'))
    expect(thirdPartyNote(0)).toBe(t('summary.thirdParty.none'))
  })
})

describe('trendIncomeNote', () => {
  const trend: MonthTotal[] = [
    point('2026-08', 'ago', 8_700_000, 0),
    point('2026-09', 'sep', 9_700_000, 15_000_000),
  ]
  it('says how much came in during the chosen month', () => {
    expect(trendIncomeNote(trend, '2026-09')).toBe(
      t('summary.trend.income', { month: monthName('2026-09'), amount: 'RD$ 150,000' }),
    )
    expect(trendIncomeNote(trend, '2026-08')).toBe(
      t('summary.trend.noIncome', { month: monthName('2026-08') }),
    )
  })
  it('without the month it says nothing', () => {
    expect(trendIncomeNote(trend, '2026-01')).toBeNull()
  })
})

describe('chosen accounts', () => {
  it('the third-party link carries the selection', () => {
    expect(thirdPartyHref('2026-01', ['a', 'b'])).toBe(
      `/transactions?${new URLSearchParams({ month: '2026-01', category: THIRD_PARTY })}&accounts=a%2Cb`,
    )
  })

  it('without a flow, "You kept" is a dash and the note asks for an account with income', () => {
    expect(netText(null)).toBe('—')
    expect(netText(150_000)).toBe('RD$ 1,500')
    expect(NO_FLOW_NOTE).toBe(t('summary.noFlow'))
  })

  it('what left for other accounts of yours; nothing when both are zero', () => {
    const cards = t('summary.ownMoves.toCards', { amount: 'RD$ 8,000' })
    const own = t('summary.ownMoves.toOwn', { amount: 'RD$ 400' })
    expect(ownMovesNote(800_000, 40_000)).toBe(`${cards} · ${own}`)
    expect(ownMovesNote(800_000, 0)).toBe(cards)
    expect(ownMovesNote(0, 40_000)).toBe(own)
    expect(ownMovesNote(0, 0)).toBeNull()
  })
})

describe('splitTop', () => {
  const items = ['a', 'b', 'c', 'd', 'e']
  it('splits into the first N and the rest', () => {
    expect(splitTop(items, 3)).toEqual({ shown: ['a', 'b', 'c'], rest: ['d', 'e'] })
  })
  it('with few rows there is no rest', () => {
    expect(splitTop(items, 5)).toEqual({ shown: items, rest: [] })
    expect(splitTop([], 8)).toEqual({ shown: [], rest: [] })
  })
  it('open, everything is shown', () => {
    expect(splitTop(items, 3, true)).toEqual({ shown: items, rest: [] })
  })
})

describe('byMovement', () => {
  it('sorts the accounts from most to least spending without touching the list', () => {
    const list: AccountTotal[] = [
      { key: 'a', label: 'A', total_cents: 100, usd_cents: 0 },
      { key: 'b', label: 'B', total_cents: 900, usd_cents: 0 },
    ]
    expect(byMovement(list).map((a) => a.key)).toEqual(['b', 'a'])
    expect(list[0].key).toBe('a')
  })
})

describe('provisionalNote', () => {
  it('says how much of the month is still without a statement, only when there is some', () => {
    expect(provisionalNote(0)).toBeNull()
    expect(provisionalNote(175000)).toBe('RD$ 1,750 aún sin estado') // spanish-ui
  })
})
