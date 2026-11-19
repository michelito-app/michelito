// Sugerencias de gastos únicos (lógica pura de la tarjeta del Resumen y del detalle).
import type { OneOffSuggestion } from './api'
import { type Selection, transactionsHref } from './accountFilter'
import { shortAccountLabel } from './accounts'
import { formatDop, formatUsd } from './money'
import { shortDay } from './months'

/** "Posibles gastos únicos (3)". */
export function cardTitle(count: number): string {
  return `Posibles gastos únicos (${count})`
}

/** Monto en RD$; si fue en dólares, también el original. */
export function amountText(item: OneOffSuggestion): string {
  const dop = formatDop(item.amount_dop_cents)
  return item.currency === 'DOP' ? dop : `${dop} · ${formatUsd(item.amount_cents)}`
}

/** "6 feb · VISA DEMO ···4242"; una cuenta bancaria va corta ("6 feb · Ahorro ···0300"). */
export function metaText(item: OneOffSuggestion): string {
  return `${shortDay(item.day)} · ${shortAccountLabel(item.account_label)}`
}

/** Transacciones del mes de la compra, con su detalle abierto y las cuentas elegidas. */
export function transactionHref(item: OneOffSuggestion, selection: Selection = null): string {
  return transactionsHref({ mes: item.day.slice(0, 7), tx: item.fingerprint }, selection)
}

/** Nombre accesible del enlace que abre la compra en Transacciones (con la cuenta completa). */
export function openLabel(item: OneOffSuggestion): string {
  const when = `${shortDay(item.day)} · ${item.account_label}`
  return `Ver en Transacciones: ${item.merchant}, ${amountText(item)}, ${when}`
}

/** Ruta del PUT que descarta (o devuelve) una sugerencia. */
export function dismissPath(fingerprint: string): string {
  return `/api/one-off-suggestions/${encodeURIComponent(fingerprint)}`
}

/** Nombre accesible de "Es único" en la fila de un comercio. */
export function confirmLabel(item: OneOffSuggestion): string {
  return `Es único: ${item.merchant}`
}

/** Nombre accesible de "No es único" en la fila de un comercio. */
export function dismissLabel(item: OneOffSuggestion): string {
  return `No es único: ${item.merchant}`
}
