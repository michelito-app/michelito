// Agrupación, selección y textos de la pantalla Cuentas (lógica pura).
import type { Account, StatementLine } from './api'
import { formatDop, formatUsd } from './money'
import { monthName, shortDay } from './months'

const CREDIT_CARD = 'credit_card'
const DASH = '—'
const SYMBOLS: Record<string, string> = { DOP: 'RD$', USD: 'US$' }
const DAY_MS = 86_400_000

export interface AccountGroups {
  cards: Account[]
  others: Account[]
}

export interface Status {
  text: string
  missing: boolean
}

/** ¿Es tarjeta de crédito? Solo ellas tienen fecha límite y pago mínimo. */
export function isCreditCard(account: Account): boolean {
  return account.kind === CREDIT_CARD
}

/** Encabezados de cargos y abonos: compras y pagos solo existen en tarjetas de crédito. */
export function movementLabels(account: Account): {
  charges: string
  payments: string
} {
  return isCreditCard(account)
    ? { charges: 'Compras', payments: 'Pagos' }
    : { charges: 'Débitos', payments: 'Créditos' }
}

/** Separa "Visa ···1234" en nombre y "···1234" para que los últimos dígitos nunca se corten. */
export function splitLabel(label: string): { name: string; tail: string } {
  const at = label.indexOf('···')
  if (at < 0) return { name: label, tail: '' }
  return { name: label.slice(0, at).trimEnd(), tail: label.slice(at) }
}

// Tipo de cuenta bancaria según su nombre guardado ("POPULAR Cuenta de ahorro 100200300").
const BANK_TYPES: readonly { pattern: RegExp; word: string }[] = [
  { pattern: /\bahorros?\b/i, word: 'Ahorro' },
  { pattern: /\bcorriente\b/i, word: 'Corriente' },
]
const TRAILING_NUMBER = /(\d[\d-]*)\s*$/

/** Nombre corto para filas angostas: una cuenta bancaria queda como "Ahorro ···0300" (tipo y
 * últimos 4 dígitos del número); las tarjetas ("MC BLACK ···0000") y lo que no se reconoce
 * quedan igual. El nombre completo sigue disponible como `title`. */
export function shortAccountLabel(label: string): string {
  if (label.includes('···')) return label
  const word = BANK_TYPES.find((t) => t.pattern.test(label))?.word
  const digits = TRAILING_NUMBER.exec(label)?.[1].replace(/\D/g, '') ?? ''
  if (!word || digits === '') return label
  return `${word} ···${digits.slice(-4)}`
}

/** Tarjetas de crédito por un lado; débito, ahorro y el resto por otro. */
export function groupAccounts(accounts: readonly Account[]): AccountGroups {
  return {
    cards: accounts.filter(isCreditCard),
    others: accounts.filter((a) => !isCreditCard(a)),
  }
}

/** La cuenta pedida si existe; si no, la primera tarjeta (o la primera cuenta). */
export function resolveAccount(
  accounts: readonly Account[],
  requested: string | null,
): Account | null {
  return (
    accounts.find((a) => a.key === requested) ??
    accounts.find(isCreditCard) ??
    accounts[0] ??
    null
  )
}

/** Monto en la moneda de la línea; "—" si el estado no lo trae. */
export function amountText(cents: number | null, currency: string): string {
  if (cents === null) return DASH
  return currency === 'USD' ? formatUsd(cents) : formatDop(cents)
}

/** "Corta el día 20 · RD$ y US$". */
export function cutLine(account: Account): string {
  if (account.cut_day === null) return 'Sin estados todavía'
  const currencies = account.currencies.map((c) => SYMBOLS[c] ?? c).join(' y ')
  return `Corta el día ${account.cut_day} · ${currencies}`
}

/** "21 sep – 20 oct"; sin inicio conocido: "hasta 20 oct"; impresión: "Impresión · 12 oct–20 oct". */
export function periodText(line: StatementLine): string {
  const end = shortDay(line.period_end)
  if (line.printout) {
    const start = line.period_start ? shortDay(line.period_start) : end
    return `Impresión · ${start}–${end}`
  }
  return line.period_start ? `${shortDay(line.period_start)} – ${end}` : `hasta ${end}`
}

/** Columna "Corte": el día del corte; una impresión del portal no tiene corte ("—"). */
export function cutText(line: StatementLine): string {
  return line.printout ? DASH : shortDay(line.period_end)
}

function lastCut(account: Account): string | null {
  return account.latest[0]?.period_end ?? null
}

/** Mes del estado que falta (el siguiente al último corte), o null si está al día. */
export function missingMonth(account: Account): string | null {
  const cut = lastCut(account)
  if (!account.missing_statement || cut === null) return null
  const next = (Number(cut.slice(5, 7)) % 12) + 1
  return monthName(`2000-${String(next).padStart(2, '0')}`)
}

/** Línea de estado de la tarjeta en la lista. */
export function statusText(account: Account): Status {
  const cut = lastCut(account)
  if (cut === null) return { text: 'Sin estados todavía', missing: false }
  const missing = missingMonth(account)
  if (missing === null) {
    return {
      text: `Al día · último estado del ${shortDay(cut)}`,
      missing: false,
    }
  }
  return {
    text: `Último estado del ${shortDay(cut)} · falta el estado de ${missing}`,
    missing: true,
  }
}

function dayNumber(iso: string): number {
  return Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)))
}

/** Cuánto falta para la fecha límite; si ya pasó, solo de qué corte es. */
export function dueNote(due: string, today: string, cut?: string): string {
  const days = Math.round((dayNumber(due) - dayNumber(today)) / DAY_MS)
  if (days === 0) return 'hoy'
  if (days === 1) return 'mañana'
  if (days > 1) return `en ${days} días`
  return cut ? `del estado del ${shortDay(cut)}` : ''
}

/** Nota bajo la tabla de estados. */
export function footnote(account: Account): string {
  const missing = missingMonth(account)
  if (missing !== null) {
    return `El estado de ${missing} todavía no llega por correo; los meses que cubre se completan cuando llegue.`
  }
  if (account.currencies.length > 1) {
    return 'Esta cuenta tiene saldo en dos monedas; cada estado se verifica por separado en RD$ y en US$.'
  }
  return 'Aquí se ve cada estado tal como lo emitió el banco; el Resumen suma por mes de calendario.'
}
