// Link pickers (legs of an exchange, reimbursements): the server sorts them and marks which ones
// are shown (`primary`); here they are searched and split into the visible ones and "See more".
import type { Candidate } from './api'

/** How many primary options are shown before "See more". */
export const VISIBLE = 5

export interface Shown {
  visible: Candidate[]
  more: Candidate[]
}

/** Without a search: the first VISIBLE primary ones in view; the rest (the other primary and the
 * non-primary ones) behind "See more", in the server's order. */
export function partition(items: readonly Candidate[], limit = VISIBLE): Shown {
  const visible = items.filter((c) => c.primary).slice(0, limit)
  const shown = new Set(visible.map((c) => c.fingerprint))
  return { visible, more: items.filter((c) => !shown.has(c.fingerprint)) }
}

const AMOUNT_QUERY = /^\d[\d,]*(\.\d{0,2})?$/

/** Digits of an amount to compare: "1,000.50" → "1000.50"; null if it does not look like one. */
export function amountQuery(query: string): string | null {
  const clean = query.trim().replace(/^(RD|US)?\$\s*/i, '')
  if (!AMOUNT_QUERY.test(clean)) return null
  return clean.replaceAll(',', '')
}

/** The amounts the option shows (its own and, if present, the converted one), as "1000.50". */
function amountTexts(item: Candidate): string[] {
  const cents = [item.amount_cents]
  if (item.converted_cents != null) cents.push(item.converted_cents)
  return cents.map(centsText)
}

/** An amount as the search compares it: "1000.50" (unsigned). */
export function centsText(cents: number): string {
  return (Math.abs(cents) / 100).toFixed(2)
}

/** Does the option match the search? An amount ("1000", "1,000", "1000.50") matches if any of
 * its amounts starts with those digits; otherwise the text is searched in the merchant, the
 * description and the account (ignoring case and accents). */
export function matches(item: Candidate, query: string): boolean {
  const amount = amountQuery(query)
  if (amount !== null) return amountTexts(item).some((text) => text.startsWith(amount))
  const needle = fold(query.trim())
  if (needle === '') return true
  return [item.merchant, item.description ?? '', item.account_label].some((text) =>
    fold(text).includes(needle),
  )
}

/** What is shown: without a search, the partition; with one, every match (from the whole list,
 * not only the visible ones). */
export function shownCandidates(items: readonly Candidate[], query: string): Shown {
  if (query.trim() === '') return partition(items)
  return { visible: items.filter((c) => matches(c, query)), more: [] }
}

/** Without accents and in lowercase, for searching. */
export function fold(text: string): string {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
}
