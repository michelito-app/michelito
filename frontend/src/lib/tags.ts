// Tags: purposes that group transactions across months and categories (spec
// `.superpowers/sdd/tags.md`). Amounts in integer cents; RD$ amounts are null for dollars
// without the month's rate.
import { t } from '@/i18n'
import { formatDop } from './money'
import { dateRange } from './months'

export type { TagChip } from './api'

export interface TagSummary {
  id: number
  name: string
  color: string | null
  group_id: number | null // a shared group's tag: renamed and deleted with the group
  spent_cents: number // the user's own share, in RD$
  still_to_pay_cents: number // what tagged financed loans and plans still owe
  unconverted: number // members in dollars without a rate: listed, not added
  count: number
  first: string | null
  last: string | null
}

export type TagVia = 'manual' | 'group' | 'loan' | 'installment'

interface TagRow {
  fingerprint: string
  day: string
  merchant: string
  description: string
  category: string
  amount_cents: number
  currency: string
  amount_dop_cents: number | null
  one_off: boolean
  counted: boolean // adds to the total (expenses and their refunds)
}

export interface TagMember extends TagRow {
  derived: boolean
  via: TagVia
}

/** A loan or installment plan the tag holds as a whole (its payments come along). */
export interface TagTarget {
  kind: 'loan' | 'installment'
  id: number
  name: string
  has_payout: boolean // its money reached the account: the purchase counts, not the payments
  still_to_pay_cents: number
}

export interface Tag extends TagSummary {
  members: TagMember[]
  by_category: { category: string; amount_cents: number }[]
  targets: TagTarget[]
}

export interface TagCandidate extends TagRow {
  likely: boolean
  tagged: boolean
}

export interface TagCandidates {
  from: string
  to: string
  items: TagCandidate[]
}

export interface CandidateFilters {
  from?: string
  to?: string
  category_id?: number
  merchant?: string
  account?: string
}

/** The days a tag spans ("18 Apr – 7 Jul 2026"); empty for a tag with no members. */
export function spanLabel(first: string | null, last: string | null): string {
  if (first === null || last === null) return ''
  return dateRange(first, last)
}

/** What the "Tag N" button says: how many rows are checked and what the counted ones add. */
export function selectionSummary(
  candidates: readonly TagCandidate[],
  selected: ReadonlySet<string>,
): { count: number; totalDopCents: number } {
  let count = 0
  let totalDopCents = 0
  for (const row of candidates) {
    if (!selected.has(row.fingerprint)) continue
    count += 1
    if (row.counted && row.amount_dop_cents !== null) totalDopCents += row.amount_dop_cents
  }
  return { count, totalDopCents }
}

function newestFirst<T extends { day: string }>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0))
}

/** The picker's two lists: likely first, then the rest, each newest first. */
export function pickerSections(items: readonly TagCandidate[]): {
  likely: TagCandidate[]
  rest: TagCandidate[]
} {
  return {
    likely: newestFirst(items.filter((r) => r.likely)),
    rest: newestFirst(items.filter((r) => !r.likely)),
  }
}

/** A member tagged by hand can be removed; one from its group, loan or plan is removed there. */
export function canRemove(member: Pick<TagMember, 'derived'>): boolean {
  return !member.derived
}

function fold(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').toLocaleLowerCase().split(/\s+/).filter(Boolean).join(' ')
}

/** The tag with this name (folded like the API folds it), or null: then it is a new one. */
export function findTag<T extends { name: string }>(tags: readonly T[], name: string): T | null {
  const wanted = fold(name)
  return tags.find((tag) => fold(tag.name) === wanted) ?? null
}

/** The line under a tagged loan or plan: what is left, or why it adds nothing. */
export function targetNote(target: TagTarget): string {
  if (target.has_payout) return t('tags.target.payout')
  return t('tags.target.left', { amount: formatDop(target.still_to_pay_cents) })
}

/** The checked rows the current filters still show: what the button counts and what it tags
 * (a row checked and then hidden by a filter is not tagged behind the user's back). */
export function visibleSelection(
  selected: ReadonlySet<string>,
  items: readonly TagCandidate[],
): ReadonlySet<string> {
  return new Set(items.filter((row) => selected.has(row.fingerprint)).map((row) => row.fingerprint))
}
