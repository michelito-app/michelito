// Caja fuerte en la interfaz (lógica pura). Las cuentas las hace el servidor
// (src/finanzas/analysis/cash_box.py); aquí solo se arman textos y cuerpos de los pedidos.
import type {
  CashBox,
  CashCurrency,
  CashEntryBody,
  CashEntryKind,
  CashLine,
  CashLineKind,
  CurrencyAmount,
  DepositBody,
  Tx,
} from './api'
import { formatMoney, parseCents } from './links'
import { formatDop } from './money'

export const CASH_BOX_KEY = 'manual:caja-fuerte'
export const CASH_KIND = 'cash'
export const CASH_BOX_ID = 'caja-fuerte'
export const CASH_BOX_HREF = `/cuentas#${CASH_BOX_ID}`
/** Fechas de lo anotado a mano (las mismas que valida el servidor): desde aquí hasta hoy + 31. */
export const FIRST_DAY = '2000-01-01'
const DAYS_AHEAD = 31

/** Hoy como "YYYY-MM-DD" en la hora local. */
export function localToday(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** El último día que se puede anotar: `today` ("YYYY-MM-DD") + 31 días. */
export function lastDay(today: string): string {
  const [year, month, day] = today.split('-').map(Number)
  const limit = new Date(Date.UTC(year, month - 1, day + DAYS_AHEAD))
  return limit.toISOString().slice(0, 10)
}

export const LINE_LABELS: Record<CashLineKind, string> = {
  initial: 'Saldo inicial',
  income: 'Entrada',
  expense: 'Salida',
  stored: 'Retiro guardado',
  deposit: 'Depósito al banco',
}

/** Título de cada formulario de lo anotado a mano. */
export const ENTRY_TITLES: Record<CashEntryKind, string> = {
  initial: 'Saldo inicial',
  income: 'Registrar entrada',
  expense: 'Registrar salida',
}

/** «de eso, RD$ X fueron a la caja fuerte»; null sin retiros guardados en el mes. */
export function cashBoxNote(cents: number): string | null {
  if (cents <= 0) return null
  return `de eso, ${formatDop(cents)} fueron a la caja fuerte`
}

/** Saldo por moneda: "RD$ 5,000 + US$ 200.00"; vacía, "RD$ 0". */
export function balanceText(balances: readonly CurrencyAmount[]): string {
  const shown = balances.filter((b) => b.amount_cents !== 0)
  if (shown.length === 0) return formatDop(0)
  return shown.map((b) => formatMoney(b.amount_cents, b.currency)).join(' + ')
}

/** "≈ RD$ 17,620" y, si algo no tiene tasa, "+ US$ 50.00 sin tasa"; null si todo es en pesos. */
export function approxText(box: CashBox): string | null {
  const foreign = box.balances.some((b) => b.currency !== 'DOP' && b.amount_cents !== 0)
  if (!foreign) return null
  const aside = box.unconverted
    .filter((u) => u.amount_cents !== 0)
    .map((u) => `+ ${formatMoney(u.amount_cents, u.currency)} sin tasa`)
  return [`≈ ${formatDop(box.total_dop_cents)}`, ...aside].join(' ')
}

/** El saldo de `currency` tras mover `deltaCents` (negativo: sale); null si no queda negativo. */
export function balanceAfter(box: CashBox, currency: string, deltaCents: number): number | null {
  const now = box.balances.find((b) => b.currency === currency)?.amount_cents ?? 0
  const left = now + deltaCents
  return left < 0 ? left : null
}

/** «La caja quedaría en −US$ 200.00; ¿ajustar el saldo inicial?» (antes de guardar). */
export function wouldBeNegative(currency: string, cents: number): string {
  return `La caja quedaría en ${formatMoney(cents, currency)}; ¿ajustar el saldo inicial?`
}

/** «La caja está en −US$ 200.00; ¿ajustar el saldo inicial?» (ya guardado). */
export function isNegative(item: CurrencyAmount): string {
  const amount = formatMoney(item.amount_cents, item.currency)
  return `La caja está en ${amount}; ¿ajustar el saldo inicial?`
}

/** El enlace a la fila en Transacciones (su mes y la fila elegida). */
export function lineHref(line: CashLine): string {
  return `/transacciones?mes=${line.day.slice(0, 7)}&tx=${encodeURIComponent(line.fingerprint)}`
}

/** El aviso antes de borrar algo anotado a mano; si está en un grupo compartido, lo dice. */
export function deleteWarning(group: string | null): string {
  const base = '¿Borrar este movimiento de la caja? Se borran también su nota y su categoría.'
  if (group === null) return base
  const lost = 'si es su único gasto, el grupo y sus reembolsos anotados se borran'
  return `${base} También sale de «${group}»; ${lost}.`
}

/** Monto de una línea con su signo: "+RD$ 5,000", "−US$ 100.00"; sin tasa, el del crédito. */
export function lineAmount(line: CashLine): string {
  if (line.amount_cents === null) {
    return `${formatMoney(line.source_amount_cents, line.source_currency)} (sin tasa)`
  }
  const text = formatMoney(Math.abs(line.amount_cents), line.currency)
  return `${line.amount_cents < 0 ? '−' : '+'}${text}`
}

/** Lo que dice una línea debajo del tipo: la cuenta del retiro o del depósito, la categoría y la
 * nota de lo anotado; en un depósito en otra moneda, cuánto fue en el banco. */
export function lineDetail(line: CashLine): string {
  const parts: string[] = []
  if (line.kind === 'stored' || line.kind === 'deposit') parts.push(line.account_label)
  if (line.kind === 'income' || line.kind === 'expense') parts.push(line.category)
  if (line.kind === 'deposit' && line.source_currency !== line.currency) {
    parts.push(`en el banco ${formatMoney(line.source_amount_cents, line.source_currency)}`)
  }
  if (line.note) parts.push(line.note)
  return parts.join(' · ')
}

export interface EntryDraft {
  kind: CashEntryKind
  day: string
  amount: string
  currency: CashCurrency
  categoryId: number | null
  note: string
}

export function emptyDraft(kind: CashEntryKind, today: string): EntryDraft {
  return { kind, day: today, amount: '', currency: 'DOP', categoryId: null, note: '' }
}

/** El borrador de una línea anotada a mano (para editarla). */
export function draftOfLine(line: CashLine): EntryDraft {
  return {
    kind: line.kind as CashEntryKind,
    day: line.day,
    amount: (line.source_amount_cents / 100).toFixed(2),
    currency: line.currency as CashCurrency,
    categoryId: line.category_id,
    note: line.note,
  }
}

/** Cuerpo del pedido o el error que se muestra. `today`: para el rango de fechas. */
export function entryBody(draft: EntryDraft, today: string): CashEntryBody | string {
  const cents = parseCents(draft.amount)
  if (cents === null) return 'Escribe un monto mayor que 0 (hasta 2 decimales)'
  if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.day)) return 'Elige la fecha'
  if (draft.day < FIRST_DAY || draft.day > lastDay(today)) {
    return `La fecha va del ${FIRST_DAY} al ${lastDay(today)}`
  }
  const body: CashEntryBody = {
    kind: draft.kind,
    day: draft.day,
    amount_cents: cents,
    currency: draft.currency,
  }
  if (draft.kind === 'initial') return body
  return { ...body, category_id: draft.categoryId, note: draft.note.trim() || null }
}

/** Cuánto cambia el saldo con lo que se va a guardar (negativo: sale). `previous`: la línea que
 * se edita, que deja de contar. */
export function draftDelta(body: CashEntryBody, previous: CashLine | null = null): number {
  const signed = body.kind === 'expense' ? -body.amount_cents : body.amount_cents
  const before = previous && previous.currency === body.currency ? (previous.amount_cents ?? 0) : 0
  return signed - before
}

/** Un depósito de `tx` que sale de la caja en `currency` (la del crédito si no se elige otra) y,
 * en otra moneda, por `amount` (vacío: a la tasa del mes). */
export function depositBody(tx: Tx, currency: CashCurrency, amount: string): DepositBody | string {
  if (currency === tx.currency) return {}
  if (amount.trim() === '') return { currency }
  const cents = parseCents(amount)
  if (cents === null) return 'Escribe un monto mayor que 0 (hasta 2 decimales)'
  return { currency, amount_cents: cents }
}

/** Lo que dice el detalle de una transacción ligada a la caja. */
export function cashBoxText(tx: Tx): string {
  if (tx.cash_box_role === 'stored') {
    return 'Guardado en la caja fuerte: no cuenta como gasto ni resta de lo que te quedó.'
  }
  if (tx.cash_box_role === 'deposit') {
    if (tx.cash_box_currency && tx.cash_box_currency !== tx.currency) {
      const taken =
        tx.cash_box_amount_cents === null
          ? 'sin tasa del mes: no baja el saldo'
          : `salieron ${formatMoney(tx.cash_box_amount_cents, tx.cash_box_currency)} de la caja`
      return `Vino de la caja fuerte (${taken}): no cuenta como ingreso.`
    }
    return 'Vino de la caja fuerte: no cuenta como ingreso.'
  }
  if (tx.can_store) return '¿Lo guardaste? Así no cuenta como gasto hasta que lo uses.'
  return '¿Era efectivo de la caja? Así no cuenta como ingreso.'
}

/** ¿El detalle muestra la sección de la caja? */
export function showCashBox(tx: Tx): boolean {
  return tx.can_store || tx.can_deposit || tx.cash_box_role !== ''
}
