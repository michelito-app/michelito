// Textos de intereses: qué pagar para no generarlos, el veredicto de cada corte y el año.
import type { CurrencyCents, DuePayment, Interest, NextDue, StatementLine } from './api'
import { amountText } from './accounts'
import { formatDop } from './money'
import { shortDay } from './months'

const KNOWN = new Set(['DOP', 'USD'])

export type VerdictTone = 'paid' | 'owed'

export interface Verdict {
  text: string | null // "Completo", "Pagado tarde" o "Quedó RD$ X"; null si el corte no tiene veredicto
  tone: VerdictTone
  interest: string | null // "+RD$ N de intereses" del estado siguiente
}

/** "RD$ 45,123 y US$ 31.97"; null si alguna moneda no se sabe mostrar. */
function amountsText(values: readonly CurrencyCents[]): string | null {
  if (values.length === 0 || values.some((v) => !KNOWN.has(v.currency))) return null
  return values.map((v) => amountText(v.cents, v.currency)).join(' y ')
}

/** La fecha límite ya pasó (fechas ISO "YYYY-MM-DD"). */
export function isOverdue(due: string, today: string): boolean {
  return due < today
}

/** Franja de la tarjeta: "Para no pagar intereses: RD$ X y US$ Y antes del 14 dic"; si la fecha
 * ya pasó, "· venció el 14 dic". Con monedas desconocidas, la frase del servidor. */
export function payText(payment: DuePayment, today: string): string {
  const amounts = amountsText(payment.amounts)
  if (amounts === null) return payment.text
  const day = shortDay(payment.due_date)
  const when = isOverdue(payment.due_date, today) ? `· venció el ${day}` : `antes del ${day}`
  return `Para no pagar intereses: ${amounts} ${when}`
}

/** Línea corta de la lista de cuentas. */
export function payNote(payment: DuePayment, today: string): string {
  const amounts = amountsText(payment.amounts)
  if (amounts === null) return payment.text
  const day = shortDay(payment.due_date)
  return isOverdue(payment.due_date, today)
    ? `${amounts} · venció el ${day}`
    : `Paga ${amounts} antes del ${day}`
}

/** "Mínimo: RD$ 2,250 y US$ 25.00"; null si el estado no trae mínimos. */
export function minimumText(payment: DuePayment): string | null {
  const amounts = amountsText(payment.minimums)
  return amounts === null ? null : `Mínimo: ${amounts}`
}

/** Veredicto de un corte en la tabla de estados; null si no hay nada que decir. */
export function verdictText(line: StatementLine): Verdict | null {
  const interest =
    line.next_interest_cents > 0
      ? `+${amountText(line.next_interest_cents, line.currency)} de intereses`
      : null
  if (line.paid_late) return { text: 'Pagado tarde', tone: 'owed', interest }
  if (line.paid_full === true) return { text: 'Completo', tone: 'paid', interest }
  if (line.paid_full === false) {
    return {
      text: `Quedó ${amountText(line.left_over_cents ?? 0, line.currency)}`,
      tone: 'owed',
      interest,
    }
  }
  return interest === null ? null : { text: null, tone: 'owed', interest }
}

/** Año calendario del mes "YYYY-MM" que se está viendo. */
export function interestYear(month: string): number {
  return Number(month.slice(0, 4))
}

/** "RD$ 23,507" (el año ya está en el título de la tarjeta). */
export function yearTotalText(data: Interest): string {
  return formatDop(data.total_dop_cents)
}

/** "Próximo: paga RD$ X y US$ Y antes del 14 dic". */
export function nextDueText(next: NextDue): string {
  const amounts = amountsText(next.amounts)
  if (amounts === null) return `Próximo: ${next.text}`
  return `Próximo: paga ${amounts} antes del ${shortDay(next.due_date)}`
}
