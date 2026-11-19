// Atypical months and "What happened" (pure logic). The rule lives on the server
// (src/michelito/analysis/anomalies.py); here only the texts and links are put together.
import { t } from '@/i18n'
import type { Contribution, Direction, MonthTotal } from './api'
import { type Selection, transactionsHref } from './accountFilter'
import { formatDop, formatSignedDop } from './money'
import { monthPhrase } from './months'

export interface Flag {
  side: 'expense' | 'income'
  direction: Direction
}

/** The month's flags: spending first, then income. */
export function monthFlags(point: MonthTotal): Flag[] {
  const flags: Flag[] = []
  if (point.spent_flag) flags.push({ side: 'expense', direction: point.spent_flag })
  if (point.income_flag) flags.push({ side: 'income', direction: point.income_flag })
  return flags
}

function flagWords(flag: Flag): string {
  if (flag.side === 'expense') {
    return flag.direction === 'up' ? t('summary.flag.spentHigh') : t('summary.flag.spentLow')
  }
  return flag.direction === 'up' ? t('summary.flag.incomeHigh') : t('summary.flag.incomeLow')
}

/** "high spending and low income"; null when the month is not atypical. */
export function flagText(point: MonthTotal): string | null {
  const words = monthFlags(point).map(flagWords)
  if (words.length === 0) return null
  if (words.length === 1) return words[0]
  return t('summary.list.and', { head: words[0], last: words[1] })
}

/** "Atypical months: July 2026 (high spending)"; null when there are none. */
export function atypicalNote(trend: MonthTotal[]): string | null {
  const parts = trend.flatMap((point) => {
    const text = flagText(point)
    return text ? [t('summary.atypical.month', { month: monthPhrase(point.month), flags: text })] : []
  })
  return parts.length
    ? t('summary.atypical.note', { months: parts.join(t('summary.list.separator')) })
    : null
}

/** The atypical month's sentence for the "What happened" header:
 * "Spending higher than usual: RD$ 40,000; the usual is RD$ 10,000". */
export function flagSentence(point: MonthTotal, flag: Flag): string {
  const spent = flag.side === 'expense'
  const amount = spent ? point.total_cents : point.income_cents
  const habitual = spent ? point.spent_habitual_cents : point.income_habitual_cents
  const up = flag.direction === 'up'
  const key = spent
    ? up
      ? 'summary.flag.sentence.spentUp'
      : 'summary.flag.sentence.spentDown'
    : up
      ? 'summary.flag.sentence.incomeUp'
      : 'summary.flag.sentence.incomeDown'
  const sentence = t(key, { amount: formatDop(amount) })
  if (habitual === null) return sentence
  return t('summary.flag.sentence.withHabitual', { sentence, habitual: formatDop(habitual) })
}

/** "+RD$ 30,000 against the usual". */
export function contributionDiff(item: Contribution): string {
  return t('summary.contribution.diff', { amount: formatSignedDop(item.diff_cents) })
}

/** A detail line: how much it was in the month and how much it usually is; "did not show up" when missing. */
export function contributionDetail(item: Contribution): string {
  const category = item.category ? `${item.category} · ` : ''
  if (item.count === 0) {
    return category + t('summary.contribution.missing', { habitual: formatDop(item.habitual_cents) })
  }
  const amounts = { amount: formatDop(item.amount_cents), habitual: formatDop(item.habitual_cents) }
  if (item.count === 1) return category + t('summary.contribution.once', amounts)
  return category + t('summary.contribution.times', { ...amounts, count: item.count })
}

/** The largest transaction in Transactions; when it did not show up, the merchant search in the month. */
export function contributionHref(item: Contribution, month: string, selection: Selection): string {
  if (item.fingerprint) return transactionsHref({ month, tx: item.fingerprint }, selection)
  return transactionsHref({ month, q: item.merchant }, selection)
}

/** Atypical-month thresholds: the same ANOMALY_SHARE and ANOMALY_FLOOR as the server
 * (analysis/anomalies.py), which decides the flags; tests/test_anomalies.py checks they match. */
export const ATYPICAL_SHARE = 0.3
export const ATYPICAL_FLOOR_CENTS = 1_000_000

/** Legend of the 12-month chart, under the bars. */
export const ATYPICAL_LEGEND = t('summary.atypical.legend', {
  percent: Math.round(ATYPICAL_SHARE * 100),
  floor: formatDop(ATYPICAL_FLOOR_CENTS),
})

export interface FlagMark extends Flag {
  /** "▲" when it went up, "▼" when it went down. */
  glyph: '▲' | '▼'
  /** "high spending", "low income"… */
  words: string
  /** High spending or low income are the bad part of the month (shown in terracotta). */
  worse: boolean
}

/** Flags shown over the bars of an atypical month (spending first). */
export function flagMarks(point: MonthTotal): FlagMark[] {
  return monthFlags(point).map((flag) => ({
    ...flag,
    glyph: flag.direction === 'up' ? '▲' : '▼',
    words: flagWords(flag),
    worse: (flag.side === 'expense') === (flag.direction === 'up'),
  }))
}

/** "+45%" or "−30%" of `amount` against `habitual`; null when there is nothing to compare with. */
export function deviationPercent(amount: number, habitual: number | null): string | null {
  if (habitual === null || habitual <= 0) return null
  const pct = Math.round(((amount - habitual) / habitual) * 100)
  if (pct === 0) return '0%'
  return `${pct > 0 ? '+' : '−'}${Math.abs(pct)}%`
}

/** Tooltip line of an atypical month: "Spending RD$ 40,000 · +45% vs the usual". */
export function flagDeviation(point: MonthTotal, flag: Flag): string {
  const spent = flag.side === 'expense'
  const amount = spent ? point.total_cents : point.income_cents
  const habitual = spent ? point.spent_habitual_cents : point.income_habitual_cents
  const what = spent
    ? t('summary.flag.deviation.spent', { amount: formatDop(amount) })
    : t('summary.flag.deviation.income', { amount: formatDop(amount) })
  const pct = deviationPercent(amount, habitual)
  return pct === null ? what : t('summary.flag.deviation.vs', { what, percent: pct })
}

/** Is any month of the chart atypical? */
export function hasAtypical(trend: MonthTotal[]): boolean {
  return trend.some((point) => monthFlags(point).length > 0)
}

/** Is there anything to tell in "What happened"? (an atypical month with merchants on that side). */
export function hasWhatHappened(point: MonthTotal | undefined, items: Contribution[]): boolean {
  if (!point) return false
  return monthFlags(point).some((flag) => items.some((item) => item.side === flag.side))
}
