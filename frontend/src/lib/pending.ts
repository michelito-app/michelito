// Textos de Pendientes (quién te debe y a quién debes). Puros: sirven a la página y a cualquier
// tarjeta que los resuma.
import { hrefWithSelection, type Selection } from './accountFilter'
import type { Pending, PendingItem } from './api'
import { formatDop, formatSignedDop, formatUsd } from './money'
import { monthPhrase, shortDay } from './months'

export const PENDING_PATH = '/pendientes'
export const EMPTY_TEXT = 'Nadie te debe y no debes nada'

/** Enlace a Pendientes con las cuentas elegidas (como los demás enlaces del Resumen). */
export function pendingHref(selection: Selection): string {
  return hrefWithSelection(PENDING_PATH, {}, selection)
}

/** Antigüedad respecto de hoy: "hoy", "hace 1 día", "hace 39 días". */
export function ageText(days: number): string {
  if (days <= 0) return 'hoy'
  return days === 1 ? 'hace 1 día' : `hace ${days} días`
}

/** "20 dic 2025 · 2 gastos · Luis · VISA ···4242": fecha (la del gasto pendiente más viejo),
 * cuántos gastos tiene el grupo (si son varios), con quién (si se sabe) y cuenta. */
export function itemMeta(item: PendingItem): string {
  const day = `${shortDay(item.day)} ${item.day.slice(0, 4)}`
  const several = item.kind === 'shared' && item.expense_count > 1
  const count = several ? `${item.expense_count} gastos` : ''
  const who = item.who === item.merchant ? '' : item.who // el título ya es «Con quién»
  return [day, count, who, item.account_label].filter((part) => part !== '').join(' · ')
}

export interface ItemAmount {
  main: string // en su moneda
  approx: string | null // "≈ RD$ X" si es en US$ y hay tasa; en un cambio, "a 58.85" al final
}

function rateText(rate: string): string {
  return `a ${Number(rate).toFixed(2)}`
}

/** Lo pendiente de una fila en su moneda; si es en US$, lo que vale en pesos y, en un cambio,
 * la tasa a la que se pactó. */
export function itemAmount(item: PendingItem): ItemAmount {
  if (item.kind === 'shared' && item.parts.length > 1) {
    // Un grupo con gastos en las dos monedas: "RD$ 6,000 + US$ 100.00 ≈ RD$ 12,200".
    const main = item.parts
      .map((p) => (p.currency === 'USD' ? formatUsd(p.cents) : formatDop(p.cents)))
      .join(' + ')
    const dop = item.pending_dop_cents
    const approx = dop === null ? null : `≈ ${formatDop(dop)}`
    return { main, approx }
  }
  const pactada = item.kind === 'exchange' && item.rate !== null ? rateText(item.rate) : null
  if (item.currency === 'DOP') return { main: formatDop(item.pending_cents), approx: pactada }
  const parts = [
    item.pending_dop_cents === null ? null : `≈ ${formatDop(item.pending_dop_cents)}`,
    pactada,
  ].filter((part) => part !== null)
  return { main: formatUsd(item.pending_cents), approx: parts.length ? parts.join(' ') : null }
}

/** "+ US$ X sin tasa" (los dólares que no entran en las cifras en RD$); null si no hay. */
export function unconvertedNote(cents: number): string | null {
  return cents > 0 ? `+ ${formatUsd(cents)} sin tasa` : null
}

export interface Figure {
  key: 'owed' | 'owe' | 'net'
  label: string
  value: string
  extra: string | null
}

/** Las tres cifras de arriba: Te deben, Debes y Neto (te deben − debes), en RD$. */
export function pendingFigures(p: Pending): Figure[] {
  const net = p.net_dop_cents === 0 ? formatDop(0) : formatSignedDop(p.net_dop_cents)
  return [
    {
      key: 'owed',
      label: 'Te deben',
      value: formatDop(p.owed_to_me_dop_cents),
      extra: unconvertedNote(p.unconverted_usd_cents.owed_to_me),
    },
    {
      key: 'owe',
      label: 'Debes',
      value: formatDop(p.i_owe_dop_cents),
      extra: unconvertedNote(p.unconverted_usd_cents.i_owe),
    },
    { key: 'net', label: 'Neto', value: net, extra: null },
  ]
}

export type NetTone = 'favor' | 'contra' | 'cero'

/** El neto a tu favor (te deben más de lo que debes), en contra o en cero. */
export function netTone(cents: number): NetTone {
  if (cents > 0) return 'favor'
  return cents < 0 ? 'contra' : 'cero'
}

/** "Compartidos en US$ a la tasa de febrero 2026 (63.70)" si algún gasto compartido en US$ se
 * convirtió con la tasa más reciente; si no, null (los cambios llevan su tasa en la fila). */
export function rateNote(p: Pending): string | null {
  const used = [...p.owed_to_me, ...p.i_owe].some(
    (i) =>
      i.kind === 'shared' &&
      i.parts.some((part) => part.currency === 'USD') &&
      i.pending_dop_cents !== null,
  )
  if (!used || p.rate === null) return null
  const value = Number(p.rate.value).toFixed(2)
  return `Compartidos en US$ a la tasa de ${monthPhrase(p.rate.month_used)} (${value})`
}

/** Nadie te debe y no debes nada. */
export function isEmpty(p: Pending): boolean {
  return p.owed_to_me.length === 0 && p.i_owe.length === 0
}
