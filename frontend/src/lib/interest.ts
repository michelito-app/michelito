// Interest texts: what to pay so none accrues, the verdict of each statement and the year.
import { t } from '@/i18n'
import type { CurrencyCents, DuePayment, Interest, NextDue, StatementLine } from './api'
import { amountText } from './accounts'
import { formatDop } from './money'
import { shortDay } from './months'

const KNOWN = new Set(['DOP', 'USD'])

export type VerdictTone = 'paid' | 'owed'

export interface Verdict {
  text: string | null // "Paid in full", "Paid late" or "Left RD$ X"; null when the statement has no verdict
  tone: VerdictTone
  interest: string | null // "+RD$ N of interest" from the next statement
}

/** "RD$ 45,123 and US$ 31.97"; null when some currency cannot be shown. */
function amountsText(values: readonly CurrencyCents[]): string | null {
  if (values.length === 0 || values.some((v) => !KNOWN.has(v.currency))) return null
  return values
    .map((v) => amountText(v.cents, v.currency))
    .join(t('summary.interest.amountsSeparator'))
}

/** The due date has passed (ISO dates "YYYY-MM-DD"). */
export function isOverdue(due: string, today: string): boolean {
  return due < today
}

/** The card's strip: "To pay no interest: RD$ X and US$ Y before 14 Dec"; when the date has
 * passed, "· due on 14 Dec". With unknown currencies, the server's sentence. */
export function payText(payment: DuePayment, today: string): string {
  const amounts = amountsText(payment.amounts)
  if (amounts === null) return payment.text
  const day = shortDay(payment.due_date)
  return isOverdue(payment.due_date, today)
    ? t('summary.interest.payOverdue', { amounts, day })
    : t('summary.interest.pay', { amounts, day })
}

/** Short line of the account list. */
export function payNote(payment: DuePayment, today: string): string {
  const amounts = amountsText(payment.amounts)
  if (amounts === null) return payment.text
  const day = shortDay(payment.due_date)
  return isOverdue(payment.due_date, today)
    ? t('summary.interest.noteOverdue', { amounts, day })
    : t('summary.interest.note', { amounts, day })
}

/** "Minimum: RD$ 2,250 and US$ 25.00"; null when the statement prints no minimums. */
export function minimumText(payment: DuePayment): string | null {
  const amounts = amountsText(payment.minimums)
  return amounts === null ? null : t('summary.interest.minimum', { amounts })
}

/** Verdict of a statement in the statements table; null when there is nothing to say. */
export function verdictText(line: StatementLine): Verdict | null {
  const interest =
    line.next_interest_cents > 0
      ? t('summary.interest.charged', { amount: amountText(line.next_interest_cents, line.currency) })
      : null
  if (line.paid_late) return { text: t('summary.interest.paidLate'), tone: 'owed', interest }
  if (line.paid_full === true) return { text: t('summary.interest.paidFull'), tone: 'paid', interest }
  if (line.paid_full === false) {
    return {
      text: t('summary.interest.leftOver', { amount: amountText(line.left_over_cents ?? 0, line.currency) }),
      tone: 'owed',
      interest,
    }
  }
  return interest === null ? null : { text: null, tone: 'owed', interest }
}

/** Calendar year of the "YYYY-MM" month being viewed. */
export function interestYear(month: string): number {
  return Number(month.slice(0, 4))
}

/** "RD$ 23,507" (the year is already in the card title). */
export function yearTotalText(data: Interest): string {
  return formatDop(data.total_dop_cents)
}

/** "Next: pay RD$ X and US$ Y before 14 Dec". */
export function nextDueText(next: NextDue): string {
  const amounts = amountsText(next.amounts)
  if (amounts === null) return t('summary.interest.nextServer', { text: next.text })
  return t('summary.interest.next', { amounts, day: shortDay(next.due_date) })
}
