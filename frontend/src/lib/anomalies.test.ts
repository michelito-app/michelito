import { describe, expect, it } from 'vitest'
import { t } from '@/i18n'
import {
  ATYPICAL_LEGEND,
  atypicalNote,
  contributionDetail,
  contributionDiff,
  contributionHref,
  deviationPercent,
  flagDeviation,
  flagMarks,
  flagSentence,
  flagText,
  hasAtypical,
  hasWhatHappened,
  monthFlags,
} from './anomalies'
import type { Contribution, MonthTotal } from './api'
import { monthPhrase } from './months'

function point(overrides: Partial<MonthTotal> = {}): MonthTotal {
  return {
    month: '2026-07',
    label: 'jul',
    total_cents: 4_000_000,
    income_cents: 0,
    partial: false,
    spent_flag: null,
    spent_habitual_cents: 1_000_000,
    income_flag: null,
    income_habitual_cents: 5_000_000,
    ...overrides,
  }
}

const AGENCY: Contribution = {
  side: 'expense',
  merchant: 'AGENCIA FICTICIA',
  category: 'Travel',
  amount_cents: 4_200_000,
  habitual_cents: 0,
  diff_cents: 4_200_000,
  count: 2,
  fingerprint: 'fp-1',
  day: '2026-07-06',
  description: 'AGENCIA FICTICIA VIAJES',
}

describe('atypical-month flags', () => {
  it('lists spending and income in that order', () => {
    const both = point({ spent_flag: 'up', income_flag: 'down' })
    expect(monthFlags(both)).toEqual([
      { side: 'expense', direction: 'up' },
      { side: 'income', direction: 'down' },
    ])
    expect(flagText(both)).toBe(
      t('summary.list.and', { head: t('summary.flag.spentHigh'), last: t('summary.flag.incomeLow') }),
    )
    expect(flagText(point({ income_flag: 'up' }))).toBe(t('summary.flag.incomeHigh'))
    expect(flagText(point())).toBeNull()
  })

  it('the note names the atypical months', () => {
    const trend = [point({ month: '2026-06' }), point({ spent_flag: 'down' })]
    const july = t('summary.atypical.month', {
      month: monthPhrase('2026-07'),
      flags: t('summary.flag.spentLow'),
    })
    expect(atypicalNote(trend)).toBe(t('summary.atypical.note', { months: july }))
    const august = t('summary.atypical.month', {
      month: monthPhrase('2026-08'),
      flags: t('summary.flag.incomeHigh'),
    })
    expect(atypicalNote([...trend, point({ month: '2026-08', income_flag: 'up' })])).toBe(
      t('summary.atypical.note', { months: `${july}, ${august}` }),
    )
    expect(atypicalNote([point()])).toBeNull()
  })

  it('the sentence compares with the usual', () => {
    expect(flagSentence(point({ spent_flag: 'up' }), { side: 'expense', direction: 'up' })).toBe(
      t('summary.flag.sentence.withHabitual', {
        sentence: t('summary.flag.sentence.spentUp', { amount: 'RD$ 40,000' }),
        habitual: 'RD$ 10,000',
      }),
    )
    expect(
      flagSentence(point({ income_flag: 'down' }), { side: 'income', direction: 'down' }),
    ).toBe(
      t('summary.flag.sentence.withHabitual', {
        sentence: t('summary.flag.sentence.incomeDown', { amount: 'RD$ 0' }),
        habitual: 'RD$ 50,000',
      }),
    )
    const unknown = point({ spent_flag: 'down', spent_habitual_cents: null })
    expect(flagSentence(unknown, { side: 'expense', direction: 'down' })).toBe(
      t('summary.flag.sentence.spentDown', { amount: 'RD$ 40,000' }),
    )
  })
})

describe('what happened', () => {
  it('detail with amount, transactions and the usual', () => {
    const amounts = { amount: 'RD$ 42,000', habitual: 'RD$ 0' }
    expect(contributionDiff(AGENCY)).toBe(t('summary.contribution.diff', { amount: '+RD$ 42,000' }))
    expect(contributionDetail(AGENCY)).toBe(
      `Travel · ${t('summary.contribution.times', { ...amounts, count: 2 })}`,
    )
    expect(contributionDetail({ ...AGENCY, count: 1 })).toBe(
      `Travel · ${t('summary.contribution.once', amounts)}`,
    )
    expect(contributionDetail({ ...AGENCY, category: '', count: 1 })).toBe(
      t('summary.contribution.once', amounts),
    )
  })

  it('says so when something did not show up', () => {
    const missing = { ...AGENCY, count: 0, amount_cents: 0, habitual_cents: 5_000_000, fingerprint: '' }
    expect(contributionDetail(missing)).toBe(
      `Travel · ${t('summary.contribution.missing', { habitual: 'RD$ 50,000' })}`,
    )
  })

  it('links the transaction, or searches the merchant when it did not show up', () => {
    expect(contributionHref(AGENCY, '2026-07', ['b'])).toBe('/transactions?month=2026-07&tx=fp-1&accounts=b')
    expect(contributionHref({ ...AGENCY, fingerprint: '' }, '2026-07', null)).toBe(
      '/transactions?month=2026-07&q=AGENCIA+FICTICIA',
    )
  })
})

describe('flags over the bars', () => {
  it('each side carries its arrow and its words; the bad part is set apart', () => {
    expect(flagMarks(point({ spent_flag: 'up', income_flag: 'down' }))).toEqual([
      { side: 'expense', direction: 'up', glyph: '▲', words: t('summary.flag.spentHigh'), worse: true },
      { side: 'income', direction: 'down', glyph: '▼', words: t('summary.flag.incomeLow'), worse: true },
    ])
    expect(flagMarks(point({ spent_flag: 'down', income_flag: 'up' }))).toEqual([
      { side: 'expense', direction: 'down', glyph: '▼', words: t('summary.flag.spentLow'), worse: false },
      { side: 'income', direction: 'up', glyph: '▲', words: t('summary.flag.incomeHigh'), worse: false },
    ])
    expect(flagMarks(point())).toEqual([])
  })

  it('the legend comes from the thresholds', () => {
    expect(ATYPICAL_LEGEND).toBe(t('summary.atypical.legend', { percent: 30, floor: 'RD$ 10,000' }))
  })

  it('the percentage is signed and rounded; without a usual there is none', () => {
    expect(deviationPercent(14_500, 10_000)).toBe('+45%')
    expect(deviationPercent(7_000, 10_000)).toBe('−30%')
    expect(deviationPercent(10_000, 10_000)).toBe('0%')
    expect(deviationPercent(10_000, null)).toBeNull()
    expect(deviationPercent(10_000, 0)).toBeNull()
  })

  it('the tooltip line says the amount and how far it departs', () => {
    const spent = point({ spent_flag: 'up' })
    const spentWhat = t('summary.flag.deviation.spent', { amount: 'RD$ 40,000' })
    expect(flagDeviation(spent, { side: 'expense', direction: 'up' })).toBe(
      t('summary.flag.deviation.vs', { what: spentWhat, percent: '+300%' }),
    )
    const income = point({ income_cents: 2_500_000, income_flag: 'down' })
    expect(flagDeviation(income, { side: 'income', direction: 'down' })).toBe(
      t('summary.flag.deviation.vs', {
        what: t('summary.flag.deviation.income', { amount: 'RD$ 25,000' }),
        percent: '−50%',
      }),
    )
    const unknown = point({ spent_flag: 'up', spent_habitual_cents: null })
    expect(flagDeviation(unknown, { side: 'expense', direction: 'up' })).toBe(spentWhat)
  })

  it('knows whether the chart has any atypical month', () => {
    expect(hasAtypical([point(), point({ income_flag: 'up' })])).toBe(true)
    expect(hasAtypical([point()])).toBe(false)
  })

  it('"What happened" only with a flagged side that has merchants', () => {
    expect(hasWhatHappened(point({ spent_flag: 'up' }), [AGENCY])).toBe(true)
    expect(hasWhatHappened(point({ income_flag: 'up' }), [AGENCY])).toBe(false)
    expect(hasWhatHappened(point(), [AGENCY])).toBe(false)
    expect(hasWhatHappened(point({ spent_flag: 'up' }), [])).toBe(false)
    expect(hasWhatHappened(undefined, [AGENCY])).toBe(false)
  })
})
