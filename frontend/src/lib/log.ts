// Change log (pure logic of the view and of a transaction's history). The rules live on the
// server (src/michelito/analysis/changelog.py and changelog_rules.py).
import { LOCALE, t } from '@/i18n'
import { transactionsHref } from './accountFilter'

export type Author = 'user' | 'claude'

/** One side of an entry: the readable line and the rows as they were. */
export interface LogSide {
  text: string
  rows: Record<string, Record<string, unknown>[]>
}

/** An entry (GET /api/log, /api/transactions/{fingerprint}/history). */
export interface LogEntry {
  id: number
  at: string // ISO with a zone (UTC)
  author: Author
  kind: string
  target_type: string
  target: string
  subject: string
  merchant: string | null
  before: LogSide
  after: LogSide
  affected: number
  fingerprints: string[]
  reason: string | null
  undoes: number | null
  undone: boolean // the original is undone now: "Redo" applies
  can_undo: boolean
  can_redo?: boolean
  undo_message: string // why the action that applies cannot be done now
  blocked_by: number | null
  toggles?: number // how many times it was undone or redone
  toggled_at?: string | null
  summary?: string | null // Shared's changes as a sentence ("You removed Javier from …")
  link_kind?: 'group' | 'contact' | null // what a change that is not a transaction's points to
  link_id?: number | null
  fingerprint: string | null // the transaction for the link
  month: string | null // its month (null: it no longer shows up)
  session_start?: string | null
  session_end?: string | null
  session_count?: number | null
}

export interface LogPage {
  items: LogEntry[]
  total: number
  offset: number
  kinds: string[]
}

export interface RuleHint {
  merchant: string
  category_id: number
  category: string
  count: number
}

export interface TxHistory {
  items: LogEntry[]
  rule_hint: RuleHint | null
}

export interface LogFilters {
  kind: string | null
  author: Author | null
  q: string
}

export const NO_FILTERS: LogFilters = { kind: null, author: null, q: '' }
export const PAGE_SIZE = 50
export const REASON_MAX = 500

/** The known kinds, in the filter's order. */
const KINDS = [
  'category',
  'category_batch',
  'merchant_rule',
  'note',
  'one_off',
  'shared',
  'group_new',
  'group',
  'group_member',
  'write_off',
  'group_entry',
  'group_entry_delete',
  'group_payment',
  'group_payment_delete',
  'contact',
  'contact_rename',
  'contact_alias',
  'contact_merge',
  'exchange',
  'investment',
  'cash_box',
  'cash_entry',
  'cash_schedule',
  'cash_occurrence',
  'cash_reconcile',
  'recurring',
  'recurring_union',
  'reviewed',
  'keywords',
  'category_kind',
  'category_deleted',
  'budget',
  'budget_warning',
  'reserve',
  'reserve_expense',
  'reserve_dismissal',
  'onboarding',
] as const

/** Name of each kind (in the filter's order). */
export const KIND_LABELS: Record<string, string> = Object.fromEntries(
  KINDS.map((kind) => [kind, t(`log.kind.${kind}`)]),
)

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind
}

/** "SUBJECT · before → after" on one line; an undo entry says so in front. */
type LineParts = Pick<LogEntry, 'subject' | 'before' | 'after' | 'undoes'> &
  Partial<Pick<LogEntry, 'summary'>>

/** The entry's line: Shared's sentence when there is one, else "SUBJECT · before → after". */
export function entryLine(entry: LineParts): string {
  const line = entry.summary ?? `${entry.subject} · ${entry.before.text} → ${entry.after.text}`
  return entry.undoes === null ? line : t('log.undone', { line })
}

/** How many transactions an entry touched. */
export function affectedText(count: number): string {
  return t('log.affected', { count })
}

/** Whether to say how many transactions it touched: not for a change that is not about
 * transactions (a group, a person) and touched none. */
export function showsAffected(entry: Pick<LogEntry, 'target_type' | 'affected'>): boolean {
  return entry.target_type === 'transaction' || entry.target_type === 'merchant' || entry.affected > 0
}

/** "undone and redone 3 times" when it went back and forth more than once. */
export function toggledText(entry: Pick<LogEntry, 'toggles'>): string | null {
  const count = entry.toggles ?? 0
  return count > 1 ? t('log.row.toggled', { count }) : null
}

/** The link's label: the merchant, the group, the person or the transaction. */
export function linkLabel(entry: Pick<LogEntry, 'target_type' | 'link_kind'>): string {
  if (entry.target_type === 'merchant') return t('log.row.viewMerchant')
  if (entry.link_kind === 'group') return t('log.row.viewGroup')
  if (entry.link_kind === 'contact') return t('log.row.viewPerson')
  return t('log.row.viewTransaction')
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

const TIME = new Intl.DateTimeFormat(LOCALE, { hour: '2-digit', minute: '2-digit', hour12: false })
const DAY = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short' })
const DAY_YEAR = new Intl.DateTimeFormat(LOCALE, {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})

/** Today, yesterday, "12 feb" or "12 feb 2025" (in local time). */
export function dayText(when: Date, now: Date = new Date()): string {
  if (sameDay(when, now)) return t('log.today')
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (sameDay(when, yesterday)) return t('log.yesterday')
  const format = when.getFullYear() === now.getFullYear() ? DAY : DAY_YEAR
  // es-DO writes "12 feb. de 2025": drop the abbreviation dots and the joining word.
  return format.format(when).replace(/\./g, '').replace(/ de /g, ' ')
}

export function timeText(when: Date): string {
  return TIME.format(when)
}

/** The session heading: day, time span (one time when start and end match) and the number of
 * changes. With filters (`shown` less than `count`) it says how many of them are shown. */
export function sessionLabel(
  start: string,
  end: string,
  count: number,
  now: Date = new Date(),
  shown: number = count,
): string {
  const from = new Date(start)
  const to = new Date(end)
  const [first, last] = [timeText(from), timeText(to)]
  const span = first === last ? first : `${first}–${last}`
  const total = t('log.changes', { count })
  const changes = shown < count ? t('log.changesShown', { shown, total }) : total
  return t('log.session', { day: dayText(from, now), span, changes })
}

export interface SessionGroup {
  key: string
  label: string
  entries: LogEntry[]
}

/** Groups the entries (already ordered, newest first) by their editing session. */
export function groupBySession(
  entries: readonly LogEntry[],
  now: Date = new Date(),
): SessionGroup[] {
  const groups: { key: string; first: LogEntry; entries: LogEntry[] }[] = []
  for (const entry of entries) {
    const key = `${entry.session_start ?? entry.at}|${entry.session_end ?? entry.at}`
    const last = groups.at(-1)
    if (last && last.key === key) last.entries.push(entry)
    else groups.push({ key, first: entry, entries: [entry] })
  }
  // The total is the whole session's; when fewer are shown (filters, "See more"), it says so.
  return groups.map(({ key, first, entries: shown }) => ({
    key,
    label: sessionLabel(
      first.session_start ?? first.at,
      first.session_end ?? first.at,
      first.session_count ?? shown.length,
      now,
      shown.length,
    ),
    entries: shown,
  }))
}

/** The path of the requested page, with the filters. */
export function logPath(filters: LogFilters, offset = 0, limit = PAGE_SIZE): string {
  const query = new URLSearchParams()
  if (filters.kind) query.set('kind', filters.kind)
  if (filters.author) query.set('author', filters.author)
  if (filters.q.trim()) query.set('q', filters.q.trim())
  if (offset) query.set('offset', String(offset))
  query.set('limit', String(limit))
  return `/api/log?${query.toString()}`
}

/** Link to the entry's transaction (in Transactions, with its month) or, for a merchant rule, to
 * Transactions searching for the merchant. Null when it no longer shows up. */
export function entryHref(entry: LogEntry): string | null {
  if (entry.target_type === 'merchant' && entry.month) {
    return transactionsHref({ month: entry.month, q: entry.target }, null)
  }
  if (entry.link_kind === 'group' && entry.link_id != null) return `/shared/${entry.link_id}`
  if (entry.link_kind === 'contact' && entry.link_id != null) return `/shared/people/${entry.link_id}`
  const group =
    entry.target_type === 'link' && entry.link_kind === undefined
      ? /^group-(\d+)$/.exec(entry.target)
      : null
  if (group) return `/shared/${group[1]}`
  if (!entry.fingerprint || !entry.month) return null
  return transactionsHref({ month: entry.month, tx: entry.fingerprint }, null)
}

/** Why there is no undo (empty when there is). */
export function undoNote(entry: LogEntry): string {
  if (entry.undone ? entry.can_redo : entry.can_undo) return ''
  return entry.undo_message
}

/** The hint that the other times this merchant got the same category by hand. */
export function hintText(hint: RuleHint): string {
  return t('log.hint', { count: hint.count, category: hint.category })
}
