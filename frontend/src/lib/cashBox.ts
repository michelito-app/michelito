// The cash account ("Efectivo" (cash)) in the interface (pure logic). The server does the math
// (src/michelito/analysis/cash_box.py, cash_schedule.py); here only texts and request bodies
// are built.
import { LOCALE, t } from '@/i18n'
import type {
  CashBox,
  CashConcept,
  CashCount,
  CashCurrency,
  CashEntryBody,
  CashEntryKind,
  CashLine,
  CashLineKind,
  CashOccurrence,
  CashSchedule,
  CashUpcoming,
  CurrencyAmount,
  DepositBody,
  Frequency,
  RepeatBody,
  ScheduleBody,
  ScheduleKind,
  Tx,
} from './api'
import type { UpcomingSource } from './home'
import { formatMoney, parseCents } from './links'
import { formatDop } from './money'

export const CASH_BOX_KEY = 'manual:cash-box'
export const CASH_KIND = 'cash'
export const CASH_BOX_ID = 'cash-box'
export const CASH_BOX_HREF = `/accounts#${CASH_BOX_ID}`
/** The cash account in Accounts (its movements, schedules and reconcile). */
export const CASH_ACCOUNT_HREF = `/accounts?account=${encodeURIComponent(CASH_BOX_KEY)}`
/** Dates of hand-written entries (the same the server validates): from here to today + 31. */
export const FIRST_DAY = '2000-01-01'
const DAYS_AHEAD = 31

/** Today as "YYYY-MM-DD" in local time. */
export function localToday(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** The last day that can be entered: `today` ("YYYY-MM-DD") + 31 days. */
export function lastDay(today: string): string {
  const [year, month, day] = today.split('-').map(Number)
  const limit = new Date(Date.UTC(year, month - 1, day + DAYS_AHEAD))
  return limit.toISOString().slice(0, 10)
}

export const LINE_LABELS: Record<CashLineKind, string> = {
  initial: t('cashBox.line.initial'),
  income: t('cashBox.line.income'),
  expense: t('cashBox.line.expense'),
  stored: t('cashBox.line.stored'),
  deposit: t('cashBox.line.deposit'),
}

/** Title of each form for hand-written entries. */
export const ENTRY_TITLES: Record<CashEntryKind, string> = {
  initial: t('cashBox.entryTitle.initial'),
  income: t('cashBox.entryTitle.income'),
  expense: t('cashBox.entryTitle.expense'),
}

/** "of that, RD$ X went to the cash box"; null without stored withdrawals in the month. */
export function cashBoxNote(cents: number): string | null {
  if (cents <= 0) return null
  return t('cashBox.note', { amount: formatDop(cents) })
}

/** Balance per currency: "RD$ 5,000 + US$ 200.00"; empty, "RD$ 0". */
export function balanceText(balances: readonly CurrencyAmount[]): string {
  const shown = balances.filter((b) => b.amount_cents !== 0)
  if (shown.length === 0) return formatDop(0)
  return shown.map((b) => formatMoney(b.amount_cents, b.currency)).join(' + ')
}

/** "≈ RD$ 17,620" and, if something has no rate, "+ US$ 50.00 without a rate"; null if all is in RD$. */
export function approxText(box: CashBox): string | null {
  const foreign = box.balances.some((b) => b.currency !== 'DOP' && b.amount_cents !== 0)
  if (!foreign) return null
  const aside = box.unconverted
    .filter((u) => u.amount_cents !== 0)
    .map((u) => t('cashBox.approx.withoutRate', { amount: formatMoney(u.amount_cents, u.currency) }))
  return [t('cashBox.approx.total', { amount: formatDop(box.total_dop_cents) }), ...aside].join(' ')
}

/** The balance of `currency` after moving `deltaCents` (negative: out); null if it is not negative. */
export function balanceAfter(box: CashBox, currency: string, deltaCents: number): number | null {
  const now = box.balances.find((b) => b.currency === currency)?.amount_cents ?? 0
  const left = now + deltaCents
  return left < 0 ? left : null
}

/** "The box would be at −US$ 200.00; adjust the initial balance?" (before saving). */
export function wouldBeNegative(currency: string, cents: number): string {
  return t('cashBox.wouldBeNegative', { amount: formatMoney(cents, currency) })
}

/** "The box is at −US$ 200.00; adjust the initial balance?" (already saved). */
export function isNegative(item: CurrencyAmount): string {
  return t('cashBox.isNegative', { amount: formatMoney(item.amount_cents, item.currency) })
}

/** The link to the row in Transactions (its month and the row chosen). */
export function lineHref(line: CashLine): string {
  return `/transactions?month=${line.day.slice(0, 7)}&tx=${encodeURIComponent(line.fingerprint)}`
}

/** The warning before deleting a hand-written entry; if it is in a shared group, it says so. */
export function deleteWarning(group: string | null): string {
  const base = t('cashBox.delete.warning')
  if (group === null) return base
  return t('cashBox.delete.warningInGroup', { base, group })
}

/** Amount of a line with its sign: "+RD$ 5,000", "−US$ 100.00"; without a rate, the credit's. */
export function lineAmount(line: CashLine): string {
  if (line.amount_cents === null) {
    const amount = formatMoney(line.source_amount_cents, line.source_currency)
    return t('cashBox.lineAmount.withoutRate', { amount })
  }
  const text = formatMoney(Math.abs(line.amount_cents), line.currency)
  return `${line.amount_cents < 0 ? '−' : '+'}${text}`
}

/** What a line says under its kind: the account of the withdrawal or deposit, the category and
 * the note of a hand-written entry; for a deposit in another currency, how much it was at the bank. */
export function lineDetail(line: CashLine): string {
  const parts: string[] = []
  if (line.kind === 'stored' || line.kind === 'deposit') parts.push(line.account_label)
  if (line.kind === 'income' || line.kind === 'expense') {
    if (line.concept) parts.push(line.concept)
    parts.push(line.category)
  }
  if (line.state === 'unconfirmed') parts.push(t('cashBox.lineDetail.unconfirmed'))
  if (line.state === 'pending') parts.push(t('cashBox.lineDetail.pending'))
  if (line.kind === 'deposit' && line.source_currency !== line.currency) {
    parts.push(
      t('cashBox.lineDetail.atBank', {
        amount: formatMoney(line.source_amount_cents, line.source_currency),
      }),
    )
  }
  if (line.note) parts.push(line.note)
  return parts.join(' · ')
}

/** "Never", "on a date" or "after some times". */
export type EndMode = 'never' | 'on' | 'after'

export interface EntryDraft {
  kind: CashEntryKind
  day: string
  amount: string
  currency: CashCurrency
  categoryId: number | null
  note: string
  concept: string
  repeat: boolean
  frequency: Frequency
  endMode: EndMode
  endDay: string
  times: string
}

export function emptyDraft(kind: CashEntryKind, today: string): EntryDraft {
  return {
    kind,
    day: today,
    amount: '',
    currency: 'DOP',
    categoryId: null,
    note: '',
    concept: '',
    repeat: false,
    frequency: 'monthly',
    endMode: 'never',
    endDay: '',
    times: '',
  }
}

/** The longest concept the server accepts (after collapsing spaces). */
export const CONCEPT_MAX = 60
export const MAX_TIMES = 1000

export const FREQUENCIES: readonly Frequency[] = ['weekly', 'biweekly', 'semimonthly', 'monthly']

export const FREQUENCY_LABELS: Record<Frequency, string> = {
  weekly: t('cashBox.frequency.weekly'),
  biweekly: t('cashBox.frequency.biweekly'),
  semimonthly: t('cashBox.frequency.semimonthly'),
  monthly: t('cashBox.frequency.monthly'),
}

const WEEKDAY = new Intl.DateTimeFormat(LOCALE, { weekday: 'long', timeZone: 'UTC' })
const SHORT_WEEKDAY = new Intl.DateTimeFormat(LOCALE, { weekday: 'short', timeZone: 'UTC' })

function utc(iso: string): Date {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day))
}

/** "vie" for "2026-11-27" (the short weekday, without the dot). */
export function shortWeekday(iso: string): string {
  return SHORT_WEEKDAY.format(utc(iso)).replace('.', '')
}

/** How often a schedule repeats, short: "every <weekday>", "the 15th and the last day"… */
export function frequencyText(frequency: Frequency, start: string): string {
  const weekday = WEEKDAY.format(utc(start))
  const day = Number(start.slice(8, 10))
  if (frequency === 'weekly') return t('cashBox.frequencyShort.weekly', { weekday })
  if (frequency === 'biweekly') return t('cashBox.frequencyShort.biweekly', { weekday })
  if (frequency === 'semimonthly') return t('cashBox.frequencyShort.semimonthly')
  if (day >= 31) return t('cashBox.frequencyShort.monthlyLast')
  return t('cashBox.frequencyShort.monthly', { day })
}

/** A schedule's line: "every <weekday> · next: <day>" (or paused / finished). */
export function scheduleText(schedule: CashSchedule): string {
  const parts = [frequencyText(schedule.frequency, schedule.start_day)]
  if (schedule.paused) parts.push(t('cashBox.schedule.paused'))
  else if (schedule.finished) parts.push(t('cashBox.schedule.finished'))
  else if (schedule.next_due) parts.push(t('cashBox.schedule.next', { day: shortDayOf(schedule.next_due) }))
  parts.push(schedule.category)
  return parts.join(' · ')
}

function shortDayOf(iso: string): string {
  const day = Number(iso.slice(8, 10))
  const month = new Intl.DateTimeFormat(LOCALE, { month: 'short', timeZone: 'UTC' })
    .format(utc(iso))
    .replace('.', '')
  return `${day} ${month}`
}

/** "Next: <concept> · RD$ 3,000 · <weekday>". */
export function upcomingText(upcoming: CashUpcoming): string {
  return t('cashBox.upcoming', {
    concept: upcoming.concept,
    amount: formatMoney(upcoming.amount_cents, upcoming.currency),
    day: shortWeekday(upcoming.day),
  })
}

/** The Summary's «Upcoming» source (`lib/home`): each scheduled cash payment or collection
 * with its next date (the card keeps those within the week). */
export function cashSource(schedules: readonly CashSchedule[], href: string): UpcomingSource {
  return () =>
    schedules
      .filter((s) => !s.paused && s.next_due !== null)
      .map((s) => ({
        key: `cash|${s.id}`,
        name: s.concept,
        day: s.next_due!,
        amount: `${s.kind === 'payment' ? '−' : '+'}${formatMoney(s.amount_cents, s.currency)}`,
        href,
      }))
}

/** How many cash items "To review" shows: the occurrences waiting and the monthly reconcile. */
export function cashReviewCount(box: CashBox | undefined): number {
  if (!box) return 0
  return box.occurrences.length + (box.reconcile_due ? 1 : 0)
}

/** The question of an occurrence in To review. */
export function occurrenceQuestion(item: CashOccurrence): string {
  return item.kind === 'expense'
    ? t('cashBox.review.payment', { concept: item.concept })
    : t('cashBox.review.collection', { concept: item.concept })
}

export function occurrenceMeta(item: CashOccurrence): string {
  return t('cashBox.review.meta', {
    amount: formatMoney(item.amount_cents, item.currency),
    day: shortDayOf(item.day),
  })
}

/** The concepts that start with (or contain) what is typed, for the entry's kind; the exact
 * match (without case or accents) first. */
export function matchConcepts(
  concepts: readonly CashConcept[],
  kind: CashEntryKind,
  typed: string,
): CashConcept[] {
  const wanted = fold(typed)
  return concepts.filter((c) => c.kind === kind && (wanted === '' || fold(c.concept).includes(wanted)))
}

/** The concept written before with exactly that text (without case or accents). */
export function knownConcept(
  concepts: readonly CashConcept[],
  kind: CashEntryKind,
  typed: string,
): CashConcept | null {
  const wanted = fold(typed)
  if (!wanted) return null
  return concepts.find((c) => c.kind === kind && fold(c.concept) === wanted) ?? null
}

/** For comparing concepts: no accents, no case, single spaces. */
export function fold(text: string): string {
  return text
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
}

/** The schedule a "Repeat" draft makes, or the error shown. */
export function repeatBody(draft: EntryDraft): RepeatBody | string {
  if (draft.endMode === 'on') {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.endDay) || draft.endDay < draft.day) {
      return t('cashBox.error.day')
    }
    return { frequency: draft.frequency, end_day: draft.endDay }
  }
  if (draft.endMode === 'after') {
    const times = Number(draft.times)
    if (!Number.isInteger(times) || times < 1 || times > MAX_TIMES) {
      return t('cashBox.error.times', { max: MAX_TIMES })
    }
    return { frequency: draft.frequency, max_count: times }
  }
  return { frequency: draft.frequency }
}

function conceptError(concept: string): string | null {
  const text = concept.trim().split(/\s+/).join(' ')
  if (!text) return t('cashBox.error.concept')
  if (text.length > CONCEPT_MAX) return t('cashBox.error.conceptLong', { max: CONCEPT_MAX })
  return null
}

/** The schedule body of a "Payment / Collection" form (`draft.kind`: expense → payment). */
export function scheduleBody(draft: EntryDraft): ScheduleBody | string {
  const cents = parseCents(draft.amount)
  if (cents === null) return t('cashBox.error.amount')
  const error = conceptError(draft.concept)
  if (error) return error
  if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.day)) return t('cashBox.error.day')
  const repeat = repeatBody(draft)
  if (typeof repeat === 'string') return repeat
  const kind: ScheduleKind = draft.kind === 'income' ? 'collection' : 'payment'
  return {
    kind,
    concept: draft.concept.trim(),
    amount_cents: cents,
    currency: draft.currency,
    category_id: draft.categoryId,
    frequency: repeat.frequency,
    start_day: draft.day,
    end_day: repeat.end_day ?? null,
    max_count: repeat.max_count ?? null,
  }
}

/** The draft of a schedule (to edit it). */
export function draftOfSchedule(schedule: CashSchedule): EntryDraft {
  const endMode: EndMode = schedule.end_day ? 'on' : schedule.max_count ? 'after' : 'never'
  return {
    kind: schedule.kind === 'payment' ? 'expense' : 'income',
    day: schedule.start_day,
    amount: (schedule.amount_cents / 100).toFixed(2),
    currency: schedule.currency,
    categoryId: schedule.category_id,
    note: '',
    concept: schedule.concept,
    repeat: true,
    frequency: schedule.frequency,
    endMode,
    endDay: schedule.end_day ?? '',
    times: schedule.max_count ? String(schedule.max_count) : '',
  }
}

/** The currencies a reconcile asks about: RD$ always, US$ when the account has had dollars. */
export function countCurrencies(box: CashBox): CashCurrency[] {
  const dollars =
    box.balances.some((b) => b.currency === 'USD') || box.lines.some((l) => l.currency === 'USD')
  return dollars ? ['DOP', 'USD'] : ['DOP']
}

/** The reconcile body from what was typed per currency (empty: not counted), or the error. */
export function countsBody(typed: Partial<Record<CashCurrency, string>>): CashCount[] | string {
  const counts: CashCount[] = []
  for (const currency of ['DOP', 'USD'] as const) {
    const text = (typed[currency] ?? '').trim()
    if (text === '') continue
    const cents = text === '0' || /^0+([.,]0+)?$/.test(text) ? 0 : parseCents(text)
    if (cents === null) return t('cashBox.error.count')
    counts.push({ currency, amount_cents: cents })
  }
  if (counts.length === 0) return t('cashBox.error.count')
  return counts
}

/** The draft of a hand-written line (to edit it). */
export function draftOfLine(line: CashLine): EntryDraft {
  return {
    kind: line.kind as CashEntryKind,
    day: line.day,
    amount: (line.source_amount_cents / 100).toFixed(2),
    currency: line.currency as CashCurrency,
    categoryId: line.category_id,
    note: line.note,
    concept: line.concept ?? '',
    repeat: false,
    frequency: 'monthly',
    endMode: 'never',
    endDay: '',
    times: '',
  }
}

/** The request body or the error shown. `today`: for the date range; `editing`: an existing
 * entry (no "Repeat", and one written before concepts may stay without one). */
export function entryBody(
  draft: EntryDraft,
  today: string,
  editing = false,
): CashEntryBody | string {
  const cents = parseCents(draft.amount)
  if (cents === null) return t('cashBox.error.amount')
  if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.day)) return t('cashBox.error.day')
  if (draft.day < FIRST_DAY || draft.day > lastDay(today)) {
    return t('cashBox.error.dayRange', { first: FIRST_DAY, last: lastDay(today) })
  }
  const body: CashEntryBody = {
    kind: draft.kind,
    day: draft.day,
    amount_cents: cents,
    currency: draft.currency,
  }
  if (draft.kind === 'initial') return body
  // An entry written before concepts can be edited without one; a new one needs it.
  const concept = draft.concept.trim()
  if (concept || !editing) {
    const error = conceptError(draft.concept)
    if (error) return error
  }
  const filled: CashEntryBody = {
    ...body,
    category_id: draft.categoryId,
    note: draft.note.trim() || null,
    ...(concept ? { concept } : {}),
  }
  if (!draft.repeat || editing) return filled
  const repeat = repeatBody(draft)
  if (typeof repeat === 'string') return repeat
  return { ...filled, repeat }
}

/** How much the balance changes with what is about to be saved (negative: out). `previous`: the
 * line being edited, which stops counting. */
export function draftDelta(body: CashEntryBody, previous: CashLine | null = null): number {
  const signed = body.kind === 'expense' ? -body.amount_cents : body.amount_cents
  const before = previous && previous.currency === body.currency ? (previous.amount_cents ?? 0) : 0
  return signed - before
}

/** A deposit of `tx` that leaves the box in `currency` (the credit's unless another is chosen)
 * and, in another currency, for `amount` (empty: at the month's rate). */
export function depositBody(tx: Tx, currency: CashCurrency, amount: string): DepositBody | string {
  if (currency === tx.currency) return {}
  if (amount.trim() === '') return { currency }
  const cents = parseCents(amount)
  if (cents === null) return t('cashBox.error.amount')
  return { currency, amount_cents: cents }
}

/** What the detail of a transaction tied to the box says. */
export function cashBoxText(tx: Tx): string {
  if (tx.cash_state === 'unconfirmed') return t('cashBox.tx.unconfirmed')
  if (tx.cash_state === 'pending') return t('cashBox.tx.pending')
  if (tx.cash_box_role === 'stored') return t('cashBox.tx.stored')
  if (tx.cash_box_role === 'deposit') {
    if (tx.cash_box_currency && tx.cash_box_currency !== tx.currency) {
      const taken =
        tx.cash_box_amount_cents === null
          ? t('cashBox.tx.withoutRate')
          : t('cashBox.tx.taken', {
              amount: formatMoney(tx.cash_box_amount_cents, tx.cash_box_currency),
            })
      return t('cashBox.tx.depositTaken', { taken })
    }
    return t('cashBox.tx.deposit')
  }
  if (tx.can_store) return t('cashBox.tx.canStore')
  return t('cashBox.tx.canDeposit')
}

/** Does the detail show the cash box section? */
export function showCashBox(tx: Tx): boolean {
  return (
    tx.can_store ||
    tx.can_deposit ||
    tx.cash_box_role !== '' ||
    tx.cash_state === 'pending' ||
    tx.cash_state === 'unconfirmed'
  )
}
