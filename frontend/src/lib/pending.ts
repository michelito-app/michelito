// Texts of Pending (who owes you and whom you owe). Pure: they serve the page and any card that
// sums them up.
import { t } from '@/i18n'
import { hrefWithSelection, type Selection } from './accountFilter'
import type { Pending, PendingItem } from './api'
import { formatDop, formatSignedDop, formatUsd } from './money'
import { monthPhrase, shortDay } from './months'

export const PENDING_PATH = '/pending'
export const EMPTY_TEXT = t('pending.empty')

/** Link to Pending with the chosen accounts (like the other Summary links). */
export function pendingHref(selection: Selection): string {
  return hrefWithSelection(PENDING_PATH, {}, selection)
}

/** Age relative to today: "today", "1 day ago", "39 days ago". */
export function ageText(days: number): string {
  if (days <= 0) return t('pending.age.today')
  return t('pending.age.daysAgo', { count: days })
}

/** "20 Dec 2025 · 2 expenses · Luis · VISA ···4242": date (of the oldest pending expense), how
 * many expenses the group has (if several), with whom (if known) and account. */
export function itemMeta(item: PendingItem): string {
  const day = `${shortDay(item.day)} ${item.day.slice(0, 4)}`
  const several = item.kind === 'shared' && item.expense_count > 1
  const count = several ? t('pending.meta.expenses', { count: item.expense_count }) : ''
  const who = item.who === item.merchant ? '' : item.who // the title already is "With whom"
  return [day, count, who, item.account_label].filter((part) => part !== '').join(' · ')
}

export interface ItemAmount {
  main: string // in its currency
  approx: string | null // "≈ RD$ X" if in US$ with a rate; for an exchange, "a 58.85" at the end
}

function rateText(rate: string): string {
  return t('pending.agreedRate', { rate: Number(rate).toFixed(2) })
}

function approx(cents: number): string {
  return t('pending.approx', { amount: formatDop(cents) })
}

/** What is pending on a row in its currency; if in US$, what it is worth in RD$ and, for an
 * exchange, the agreed rate. */
export function itemAmount(item: PendingItem): ItemAmount {
  if (item.kind === 'shared' && item.parts.length > 1) {
    // A group with expenses in both currencies: "RD$ 6,000 + US$ 100.00 ≈ RD$ 12,200".
    const main = item.parts
      .map((p) => (p.currency === 'USD' ? formatUsd(p.cents) : formatDop(p.cents)))
      .join(' + ')
    const dop = item.pending_dop_cents
    return { main, approx: dop === null ? null : approx(dop) }
  }
  const agreed = item.kind === 'exchange' && item.rate !== null ? rateText(item.rate) : null
  if (item.currency === 'DOP') return { main: formatDop(item.pending_cents), approx: agreed }
  const parts = [
    item.pending_dop_cents === null ? null : approx(item.pending_dop_cents),
    agreed,
  ].filter((part) => part !== null)
  return { main: formatUsd(item.pending_cents), approx: parts.length ? parts.join(' ') : null }
}

/** "+ US$ X without a rate" (the dollars left out of the RD$ figures); null if none. */
export function unconvertedNote(cents: number): string | null {
  return cents > 0 ? t('pending.unconverted', { amount: formatUsd(cents) }) : null
}

export interface Figure {
  key: 'owed' | 'owe' | 'net'
  label: string
  value: string
  extra: string | null
}

/** The three figures on top: Owed to you, You owe and Net (owed to you − you owe), in RD$. */
export function pendingFigures(p: Pending): Figure[] {
  const net = p.net_dop_cents === 0 ? formatDop(0) : formatSignedDop(p.net_dop_cents)
  return [
    {
      key: 'owed',
      label: t('pending.figure.owed'),
      value: formatDop(p.owed_to_me_dop_cents),
      extra: unconvertedNote(p.unconverted_usd_cents.owed_to_me),
    },
    {
      key: 'owe',
      label: t('pending.figure.owe'),
      value: formatDop(p.i_owe_dop_cents),
      extra: unconvertedNote(p.unconverted_usd_cents.i_owe),
    },
    { key: 'net', label: t('pending.figure.net'), value: net, extra: null },
  ]
}

export type NetTone = 'positive' | 'negative' | 'zero'

/** The net in your favor (you are owed more than you owe), against you or at zero. */
export function netTone(cents: number): NetTone {
  if (cents > 0) return 'positive'
  return cents < 0 ? 'negative' : 'zero'
}

/** "Shared in US$ at the February 2026 rate (63.70)" if any shared expense in US$ was converted
 * with the latest rate; otherwise null (exchanges carry their rate on the row). */
export function rateNote(p: Pending): string | null {
  const used = [...p.owed_to_me, ...p.i_owe].some(
    (i) =>
      i.kind === 'shared' &&
      i.parts.some((part) => part.currency === 'USD') &&
      i.pending_dop_cents !== null,
  )
  if (!used || p.rate === null) return null
  const value = Number(p.rate.value).toFixed(2)
  return t('pending.rateNote', { month: monthPhrase(p.rate.month_used), value })
}

/** Nobody owes you and you owe nothing. */
export function isEmpty(p: Pending): boolean {
  return p.owed_to_me.length === 0 && p.i_owe.length === 0
}
