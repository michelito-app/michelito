// Months as "YYYY-MM" text and days as ISO "YYYY-MM-DD", like the API.
import { LOCALE, t } from '@/i18n'
import type { MonthOption } from './api'

// Month names come from Intl (LOCALE), in lowercase as written in phrases.
const MONTH_NAME = new Intl.DateTimeFormat(LOCALE, { month: 'long', timeZone: 'UTC' })
const NAMES: readonly string[] = Array.from({ length: 12 }, (_, index) =>
  MONTH_NAME.format(new Date(Date.UTC(2000, index, 1))),
)

function parts(month: string): { year: number; index: number } {
  return { year: Number(month.slice(0, 4)), index: Number(month.slice(5, 7)) - 1 }
}

/** "2026-09" → the month name (lowercase). */
export function monthName(month: string): string {
  return NAMES[parts(month).index] ?? month
}

/** "2026-09" → month name and year, for phrases. */
export function monthPhrase(month: string): string {
  return `${monthName(month)} ${parts(month).year}`
}

/** "2026-09" → capitalized month name and year, as a title. */
export function monthTitle(month: string): string {
  const phrase = monthPhrase(month)
  return phrase.charAt(0).toUpperCase() + phrase.slice(1)
}

/** Last day of the month: 30 for "2026-09". */
export function lastDay(month: string): number {
  const { year, index } = parts(month)
  return new Date(Date.UTC(year, index + 1, 0)).getUTCDate()
}

/** "2026-10-13" → day and the first three letters of the month. */
export function shortDay(iso: string): string {
  return `${Number(iso.slice(8, 10))} ${monthName(iso.slice(0, 7)).slice(0, 3)}`
}

/** "2026-10-13" → day and full month name (`months.longDay`). */
export function longDay(iso: string): string {
  return t('months.longDay', { day: Number(iso.slice(8, 10)), month: monthName(iso.slice(0, 7)) })
}

/** "2026-10-13" → day, short month and year. */
export function dayWithYear(iso: string): string {
  return `${shortDay(iso)} ${iso.slice(0, 4)}`
}

/** A span of days (month names from the UI locale): "20 Dec 2025", "3 Feb – 7 Feb 2026" or,
 * across years, "18 Dec 2025 – 9 Jan 2026". */
export function dateRange(first: string, last: string): string {
  if (first === last) return dayWithYear(first)
  if (first.slice(0, 4) === last.slice(0, 4)) return `${shortDay(first)} – ${dayWithYear(last)}`
  return `${dayWithYear(first)} – ${dayWithYear(last)}`
}

/** Today in the browser's time zone, as "YYYY-MM-DD". */
export function localToday(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** The requested month if it exists; otherwise the newest one (the month in progress, live):
 * every month screen opens on it. */
export function resolveMonth(options: readonly MonthOption[], requested: string | null): string | null {
  if (requested && options.some((o) => o.month === requested)) return requested
  return options[0]?.month ?? null
}

/** Default month one can go back to from `month`; null if already on it. */
export function returnTarget(options: readonly MonthOption[], month: string): MonthOption | null {
  const home = resolveMonth(options, null)
  if (home === null || home === month) return null
  return options.find((o) => o.month === home) ?? null
}

export interface Neighbors {
  older: string | null
  newer: string | null
}

/** Neighboring months; `options` goes from newest to oldest, as the API sends it. */
export function neighbors(options: MonthOption[], month: string): Neighbors {
  const at = options.findIndex((o) => o.month === month)
  if (at < 0) return { older: null, newer: null }
  return {
    older: options[at + 1]?.month ?? null,
    newer: at > 0 ? options[at - 1].month : null,
  }
}
