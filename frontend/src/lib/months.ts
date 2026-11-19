// Meses como texto "YYYY-MM" y días como ISO "YYYY-MM-DD", igual que la API.
import type { MonthOption } from './api'

const NAMES = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
] as const

function parts(month: string): { year: number; index: number } {
  return { year: Number(month.slice(0, 4)), index: Number(month.slice(5, 7)) - 1 }
}

/** "2026-09" → "septiembre". */
export function monthName(month: string): string {
  return NAMES[parts(month).index] ?? month
}

/** "2026-09" → "septiembre 2026", para frases. */
export function monthPhrase(month: string): string {
  return `${monthName(month)} ${parts(month).year}`
}

/** "2026-09" → "Septiembre 2026", como título. */
export function monthTitle(month: string): string {
  const phrase = monthPhrase(month)
  return phrase.charAt(0).toUpperCase() + phrase.slice(1)
}

/** Último día del mes: 30 para "2026-09". */
export function lastDay(month: string): number {
  const { year, index } = parts(month)
  return new Date(Date.UTC(year, index + 1, 0)).getUTCDate()
}

/** "2026-10-13" → "13 oct". */
export function shortDay(iso: string): string {
  return `${Number(iso.slice(8, 10))} ${monthName(iso.slice(0, 7)).slice(0, 3)}`
}

/** "2026-10-13" → "13 de octubre". */
export function longDay(iso: string): string {
  return `${Number(iso.slice(8, 10))} de ${monthName(iso.slice(0, 7))}`
}

/** Hoy en la zona del navegador, como "YYYY-MM-DD". */
export function localToday(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** El mes pedido si existe; si no, el más reciente completo (o el más reciente). */
export function resolveMonth(options: MonthOption[], requested: string | null): string | null {
  if (requested && options.some((o) => o.month === requested)) return requested
  return (options.find((o) => !o.partial) ?? options[0])?.month ?? null
}

/** Mes por defecto al que se puede volver desde `month`; null si ya se está en él. */
export function returnTarget(options: MonthOption[], month: string): MonthOption | null {
  const home = resolveMonth(options, null)
  if (home === null || home === month) return null
  return options.find((o) => o.month === home) ?? null
}

export interface Neighbors {
  older: string | null
  newer: string | null
}

/** Meses vecinos; `options` va del más nuevo al más viejo, como lo manda la API. */
export function neighbors(options: MonthOption[], month: string): Neighbors {
  const at = options.findIndex((o) => o.month === month)
  if (at < 0) return { older: null, newer: null }
  return {
    older: options[at + 1]?.month ?? null,
    newer: at > 0 ? options[at - 1].month : null,
  }
}
