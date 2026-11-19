// «Para revisar» (lógica pura de la tarjeta del Resumen y del historial en Reportes).
// Las reglas viven en el servidor (src/finanzas/analysis/review.py).
import type { ReviewItem, ReviewKind } from './api'
import { type Selection, transactionsHref } from './accountFilter'
import { shortAccountLabel } from './accounts'
import { formatDop, formatUsd } from './money'
import { shortDay } from './months'

/** Etiqueta de cada tipo, en el orden de los filtros. */
export const KIND_LABELS: Record<ReviewKind, string> = {
  unico: '¿Gasto único?',
  ingreso_inusual: 'Ingreso inusual',
  tercero_grande: 'Transferencia grande',
  duplicado: '¿Cargo duplicado?',
  subio: 'Subió de precio',
  aporte_posible: '¿Otro aporte?',
  cobro_posible: '¿Cobro de una inversión?',
  regla_posible: '¿Regla para el comercio?',
  reserva_posible: '¿De una reserva?',
}

export const REVIEW_KINDS = Object.keys(KIND_LABELS) as ReviewKind[]

/** "Para revisar (3)". */
export function cardTitle(count: number): string {
  return `Para revisar (${count})`
}

/** Monto en RD$; si fue en dólares, también el original (o solo los US$ si no hay tasa). */
export function amountText(item: ReviewItem): string {
  if (item.currency === 'DOP') return formatDop(item.amount_cents)
  const usd = formatUsd(item.amount_cents)
  return item.amount_dop_cents === null ? usd : `${formatDop(item.amount_dop_cents)} · ${usd}`
}

/** Monto corto de la fila del Resumen: en RD$ (o solo los US$ si no hay tasa). */
export function mainAmountText(item: ReviewItem): string {
  if (item.currency === 'DOP') return formatDop(item.amount_cents)
  return item.amount_dop_cents === null ? formatUsd(item.amount_cents) : formatDop(item.amount_dop_cents)
}

/** Los US$ originales cuando la fila los muestra convertidos; null si no hace falta. */
export function originalAmountText(item: ReviewItem): string | null {
  if (item.currency === 'DOP' || item.amount_dop_cents === null) return null
  return formatUsd(item.amount_cents)
}

/** "6 feb · VISA DEMO ···4242"; una cuenta bancaria va corta ("6 feb · Corriente ···7770"). */
export function metaText(item: ReviewItem): string {
  return `${shortDay(item.day)} · ${shortAccountLabel(item.account_label)}`
}

/** Transacciones del mes del movimiento, con su detalle abierto y las cuentas elegidas. */
export function itemHref(item: ReviewItem, selection: Selection = null): string {
  return transactionsHref({ mes: item.month, tx: item.fingerprint }, selection)
}

/** Nombre accesible del enlace que abre el movimiento. */
export function openLabel(item: ReviewItem): string {
  return `Ver en Transacciones: ${item.merchant}, ${amountText(item)}, ${shortDay(item.day)} · ${item.account_label}`
}

/** Nombre accesible de "Ya lo revisé" (o de "No es único" en un gasto único). */
export function reviewedLabel(item: ReviewItem): string {
  if (item.kind === 'regla_posible') return `Descartar regla: ${item.merchant}`
  return item.kind === 'unico' ? `No es único: ${item.merchant}` : `Ya lo revisé: ${item.merchant}`
}

/** Ruta del PUT que marca (o desmarca) un movimiento como revisado. */
export function reviewPath(kind: ReviewKind, fingerprint: string): string {
  return `/api/review/${kind}/${encodeURIComponent(fingerprint)}`
}

/** Clave estable de un elemento: la misma huella puede salir con dos tipos. */
export function itemKey(item: Pick<ReviewItem, 'kind' | 'fingerprint'>): string {
  return `${item.kind}:${item.fingerprint}`
}
