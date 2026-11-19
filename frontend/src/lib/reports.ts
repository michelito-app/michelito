// Reports: compare months (pure logic). The cell rule lives on the server
// (src/michelito/web/reports.py): here only classes, texts and links are chosen.
import { t } from '@/i18n'
import type { CompareCell, MonthOption } from './api'
import { type Selection, transactionsHref } from './accountFilter'
import { THIRD_PARTY } from './categories'
import { formatDop } from './money'

export const FROM_PARAM = 'from'
export const TO_PARAM = 'to'

/** Key of an income-by-category row (`reports.INCOME_PREFIX`): `income:Crypto`. */
export const INCOME_PREFIX = 'income:'

/** The top rows: they are not categories. */
export const TOTAL_KEYS = ['income', 'expenses', 'third_party', 'net'] as const

/** Background of a rise (terracotta, stronger the further it departs). The text stays dark. */
const UP_LEVELS = ['', 'bg-[#F7E9E2]', 'bg-[#EFD3C5]', 'bg-[#E4B8A3]'] as const
const DOWN = 'shadow-[inset_0_0_0_2px_var(--color-down)]'

/** A cell's classes: a rise in terracotta (intensity 1 to 3), a fall with a green border.
 * Income and "You kept" are not coloured (rising there is good, not spending). */
export function cellClass(rowKey: string, cell: CompareCell): string {
  if (rowKey === 'income' || rowKey === 'third_party' || rowKey === 'net') return ''
  if (rowKey.startsWith(INCOME_PREFIX)) return ''
  if (cell.flag === 'up') return UP_LEVELS[Math.min(3, Math.max(1, cell.level))]
  if (cell.flag === 'down') return DOWN
  return ''
}

/** A cell's help text: the usual and the deviation. */
export function cellTitle(cell: CompareCell): string {
  if (cell.habitual_cents === null) return t('reports.cell.notCompared')
  const habitual = formatDop(cell.habitual_cents)
  if (cell.flag === 'up') return t('reports.cell.higher', { habitual })
  if (cell.flag === 'down') return t('reports.cell.lower', { habitual })
  return t('reports.cell.habitual', { habitual })
}

/** Where a cell leads in Transactions (month, category and accounts); null for "You kept". */
export function cellHref(
  rowKey: string,
  month: string,
  selection: Selection,
  thirdPartyName: string = THIRD_PARTY,
): string | null {
  switch (rowKey) {
    case 'net':
      return null
    case 'income':
      return transactionsHref({ month, kind: 'income' }, selection)
    case 'expenses':
      return transactionsHref({ month, kind: 'expense' }, selection)
    case 'third_party':
      return transactionsHref({ month, category: thirdPartyName }, selection)
    default:
      if (rowKey.startsWith(INCOME_PREFIX)) {
        const category = rowKey.slice(INCOME_PREFIX.length)
        return transactionsHref({ month, kind: 'income', category }, selection)
      }
      return transactionsHref({ month, category: rowKey }, selection)
  }
}

export interface Range {
  from: string | null
  to: string | null
}

/** The URL range (`from`, `to`), only when they are months with data. */
export function parseRange(params: URLSearchParams, months: readonly MonthOption[]): Range {
  const known = new Set(months.map((m) => m.month))
  const pick = (key: string) => {
    const value = params.get(key)
    return value && known.has(value) ? value : null
  }
  return { from: pick(FROM_PARAM), to: pick(TO_PARAM) }
}

/** API parameters for the range (`from`, `to`); empty: the 12 most recent months. */
export function rangeQuery(range: Range): string {
  const query = new URLSearchParams()
  if (range.from) query.set('from', range.from)
  if (range.to) query.set('to', range.to)
  const text = query.toString()
  return text ? `?${text}` : ''
}

/** A range the server accepts: when "from" falls after "to", they are swapped. */
export function orderedRange(range: Range): Range {
  if (range.from && range.to && range.from > range.to) return { from: range.to, to: range.from }
  return range
}
