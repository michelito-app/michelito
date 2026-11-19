// Shared groups, reimbursements and currency exchanges in the interface (pure logic). The
// server does the math (src/michelito/analysis/shared.py and exchanges.py); this only builds
// texts, badges and request bodies.
import { t } from '@/i18n'
import type {
  CurrencyCents,
  ExchangeInfo,
  GroupExpense,
  GroupRef,
  InvestmentRole,
  SharedTotal,
  LinkedTx,
  SharedInfo,
  Split,
  SplitBody,
  Tx,
} from './api'
import { formatDop, formatUsd } from './money'
import { monthName } from './months'

/** An amount in its currency: RD$ without decimals, US$ with two. */
export function formatMoney(cents: number, currency: string): string {
  return currency === 'USD' ? formatUsd(cents) : formatDop(cents)
}

/** "2026-02-13" → the day and the month name, e.g. 13 February in Spanish. */
export function shortDay(iso: string): string {
  return t('links.dayOfMonth', { day: Number(iso.slice(8, 10)), month: monthName(iso.slice(0, 7)) })
}

/** Amounts in several currencies: "RD$ 3,000 + US$ 120.00". Zero ones are left out, unless
 * all of them are zero ("RD$ 0"). */
export function moneyList(parts: readonly CurrencyCents[]): string {
  const shown = parts.filter((p) => p.cents !== 0)
  if (shown.length === 0) return formatMoney(0, parts[0]?.currency ?? 'DOP')
  return shown.map((p) => formatMoney(p.cents, p.currency)).join(' + ')
}

/** How an expense was split: split among N people, my share, or paid for someone else. */
export function splitText(split: Split, currency: string): string {
  if (split.for_other) return t('links.split.forOther')
  if (split.people !== null) return t('links.split.people', { people: split.people })
  return t('links.split.myShare', { amount: formatMoney(split.my_share_cents ?? 0, currency) })
}

/** One figure of a group (your share, reimbursed, owed), each by currency. */
export interface SharedStat {
  label: string
  value: string
}

function byCurrency(totals: readonly SharedTotal[], pick: (total: SharedTotal) => number): string {
  return moneyList(totals.map((total) => ({ currency: total.currency, cents: pick(total) })))
}

/** The group's share, reimbursed and pending (or written-off) amounts, by currency. */
export function sharedStats(group: SharedInfo): SharedStat[] {
  const totals = group.totals
  return [
    { label: t('links.stat.yourShare'), value: byCurrency(totals, (s) => s.share_cents) },
    { label: t('links.stat.reimbursed'), value: byCurrency(totals, (s) => s.reimbursed_cents) },
    group.written_off
      ? { label: t('links.stat.writtenOff'), value: byCurrency(totals, (s) => s.written_off_cents) }
      : { label: t('links.stat.owed'), value: byCurrency(totals, (s) => s.pending_cents) },
  ]
}

/** Status of a group expense after applying the reimbursements (oldest to newest). */
export function expenseStatus(expense: GroupExpense): string {
  if (expense.written_off_cents > 0) {
    return t('links.expense.writtenOff', {
      amount: formatMoney(expense.written_off_cents, expense.currency),
    })
  }
  if (expense.pending_cents === 0) return t('links.expense.settled')
  return t('links.expense.pending', { amount: formatMoney(expense.pending_cents, expense.currency) })
}

/** Warning when the whole group got back more than it owed: the excess does not count; it is
 * usually a repeated reimbursement. */
export function overWarning(group: SharedInfo): string | null {
  if (group.excess.length === 0) return null
  return t('links.warning.over', { amount: moneyList(group.excess) })
}

/** Warning when some reimbursement does not count (or not fully) for lack of its month's rate. */
export function unconvertedWarning(group: SharedInfo): string | null {
  const n = group.unconverted.length
  if (n === 0) return null
  return t('links.warning.unconverted', { count: n })
}

/** The group title and what you are owed (or that it is settled). */
export function groupLabel(group: GroupRef): string {
  const status = group.pending.length
    ? t('links.group.owed', { amount: moneyList(group.pending) })
    : t('links.group.settled')
  return t('links.group.label', { title: group.title, status })
}

/** The number of expenses, pluralized. */
export function expenseCount(n: number): string {
  return t('links.expenseCount', { count: n })
}

export interface LinkBadge {
  label: string
  tone: 'shared' | 'linked' | 'suggested'
}

/** A row's link badges: shared (with what you are owed), reimbursement or exchange, and their
 * suggestions. */
export function linkBadges(tx: Tx): LinkBadge[] {
  const badges: LinkBadge[] = []
  if (tx.link === 'shared' && tx.shared) {
    badges.push({ label: t('links.badge.shared'), tone: 'shared' })
    if (tx.pending_cents > 0) {
      const amount = formatMoney(tx.pending_cents, tx.currency)
      badges.push({ label: t('links.badge.owed', { amount }), tone: 'shared' })
    }
  }
  if (tx.link === 'reimbursement') badges.push({ label: t('links.badge.reimbursement'), tone: 'linked' })
  if (tx.suggested_group) {
    badges.push({ label: t('links.badge.suggestedReimbursement'), tone: 'suggested' })
  }
  if (tx.link === 'exchange') badges.push({ label: t('links.badge.exchange'), tone: 'linked' })
  if (tx.suggested_exchange_with) {
    badges.push({ label: t('links.badge.suggestedExchange'), tone: 'suggested' })
  }
  if (tx.link === 'investment') badges.push({ label: t('links.badge.investment'), tone: 'linked' })
  if (tx.suggested_investment) {
    badges.push({ label: t('links.badge.suggestedInvestment'), tone: 'suggested' })
  }
  if (tx.link === 'reserve') badges.push({ label: t('links.badge.reserve'), tone: 'linked' })
  return badges
}

/** Another transaction as "MERCHANT (day)", for questions and lists. */
export function linkedLabel(linked: LinkedTx): string {
  return t('links.linkedLabel', { merchant: linked.merchant, day: shortDay(linked.day) })
}

/** Amount of another transaction, with "+" when money comes in; a credit in the expense's other
 * currency carries what it is worth in it ("+RD$ 600 ≈ US$ 10.00") or a no-rate note. */
export function linkedAmount(linked: LinkedTx): string {
  const text = formatMoney(Math.abs(linked.amount_cents), linked.currency)
  const signed = linked.amount_cents < 0 ? `+${text}` : text
  if (!linked.converted_currency) return signed
  if (linked.converted_cents == null) return t('links.linkedAmount.noRate', { amount: signed })
  return `${signed} ≈ ${formatMoney(linked.converted_cents, linked.converted_currency)}`
}

/** A rate with two decimals: "62.5000" → "62.50". */
export function rateLabel(rate: string): string {
  const value = Number(rate)
  return Number.isFinite(value) ? value.toFixed(2) : rate
}

/** Both sides of the exchange, the rate and what is pending (with its RD$ value). The base side
 * goes first. */
export function exchangeLine(exchange: ExchangeInfo): string {
  const total = (currency: string) =>
    exchange.totals.find((t) => t.currency === currency)?.cents ?? 0
  const other = exchange.base === 'DOP' ? 'USD' : 'DOP'
  const sides = `${formatMoney(total(exchange.base), exchange.base)} ↔ ${formatMoney(total(other), other)}`
  const parts = [
    t('links.exchange.line', { sides }),
    t('links.exchange.rate', { rate: rateLabel(exchange.rate) }),
  ]
  if (exchange.closed) parts.push(t('links.exchange.closed'))
  else if (exchange.pending_cents === 0) parts.push(t('links.exchange.noPending'))
  else {
    const amount = formatMoney(exchange.pending_cents, exchange.pending_currency)
    parts.push(
      exchange.pending_currency === 'DOP'
        ? t('links.exchange.pending', { amount })
        : t('links.exchange.pendingConverted', {
            amount,
            dop: formatDop(exchange.pending_dop_cents),
          }),
    )
  }
  return parts.join(' · ')
}

/** "1,850.50" or "1850,5" → cents; null unless it is a positive amount with up to 2 decimals. */
export function parseCents(text: string): number | null {
  const clean = text.trim().replace(/^(RD|US)?\$\s*/i, '').replaceAll(',', '')
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null
  const cents = Math.round(Number(clean) * 100)
  return cents > 0 ? cents : null
}

/** How the detail form splits an expense. */
export type SplitMode = 'people' | 'share' | 'other'

export interface SplitDraft {
  mode: SplitMode
  people: string
  share: string
}

/** The draft of a split: the one in `split` (an expense already split, or the last one added
 * to the group, offered when adding another) or two people. */
export function splitDraftOf(split: Split | null): SplitDraft {
  if (split === null) return { mode: 'people', people: '2', share: '' }
  const mode: SplitMode = split.for_other ? 'other' : split.people !== null ? 'people' : 'share'
  return {
    mode,
    people: String(split.people ?? 2),
    share: split.my_share_cents === null ? '' : (split.my_share_cents / 100).toFixed(2),
  }
}

/** The split body, or the error shown when the form is not valid. `amountCents`: the expense's
 * amount (your share cannot exceed it). */
export function sharedBody(
  draft: SplitDraft,
  amountCents: number,
): { body: SplitBody } | { error: string } {
  if (draft.mode === 'other') return { body: { for_other: true } }
  if (draft.mode === 'people') {
    const people = Number(draft.people)
    if (!Number.isInteger(people) || people < 2 || people > 100) {
      return { error: t('links.splitError.people') }
    }
    return { body: { people } }
  }
  const cents = parseCents(draft.share)
  if (cents === null) return { error: t('links.splitError.share') }
  if (cents > amountCents) return { error: t('links.splitError.shareTooBig') }
  return { body: { my_share_cents: cents } }
}


/** A row's statement amount (before splitting). */
export function grossCents(tx: Tx): number {
  return tx.gross_cents ?? tx.amount_cents
}

/** Is the Shared section shown? An expense that can be shared or one already marked (even if
 * the link is dormant: it lets you stop sharing it). */
export function showShared(tx: Tx): boolean {
  return tx.can_share || tx.link === 'shared'
}

/** Is the Reimbursement section shown? A credit that can be one (server rules) or a linked one. */
export function showReimbursement(tx: Tx): boolean {
  return tx.can_reimburse || tx.link === 'reimbursement'
}

/** Is the Currency exchange section shown? */
export function showExchange(tx: Tx): boolean {
  return tx.can_exchange || tx.link === 'exchange'
}

/** Is the Investment section shown? A bank debit or credit that can be one, or one already in
 * an investment. */
export function showInvestment(tx: Tx): boolean {
  return tx.can_invest || tx.can_invest_credit || tx.link === 'investment'
}

/** A credit, an exchange leg, an investment or cash box movement: the link sets its category. */
export function categoryLocked(tx: Tx): boolean {
  return (
    tx.link === 'reimbursement' ||
    tx.link === 'exchange' ||
    tx.link === 'investment' ||
    tx.link === 'cash_box'
  )
}

/** A new set with `key` added or removed. */
export function toggled(current: ReadonlySet<string>, key: string): ReadonlySet<string> {
  const next = new Set(current)
  if (!next.delete(key)) next.add(key)
  return next
}

/** Which link a panel line summarizes. */
export type SummaryKind = 'shared' | 'reimbursement' | 'exchange' | 'investment'

/** A line of the detail panel: the link's status and the button that opens its screen. */
export interface LinkSummary {
  kind: SummaryKind
  title: string
  text: string
  /** The button's label (manage, share, "it is an investment"…). */
  action: string
}

const MANAGE = () => t('links.action.manage')

function sharedSummary(tx: Tx): LinkSummary {
  const base = { kind: 'shared', title: t('links.summary.sharedTitle'), action: MANAGE() } as const
  const shared = tx.shared
  if (shared === null) {
    if (tx.link === 'shared') return { ...base, text: t('links.summary.sharedDormant') }
    return { ...base, text: t('links.summary.sharedOffer'), action: t('links.action.share') }
  }
  const refunds = t('links.summary.refundCount', {
    count: shared.reimbursements.length + shared.manual.length,
  })
  const lost = shared.totals.map((total) => ({
    currency: total.currency,
    cents: total.written_off_cents,
  }))
  const status = shared.written_off
    ? t('links.summary.writtenOff', { amount: moneyList(lost) })
    : shared.pending.length
      ? t('links.group.owed', { amount: moneyList(shared.pending) })
      : t('links.group.settled')
  return { ...base, text: t('links.summary.sharedText', { title: shared.title, status, refunds }) }
}

function reimbursementSummary(tx: Tx): LinkSummary {
  const base = {
    kind: 'reimbursement',
    title: t('links.summary.reimbursementTitle'),
    action: MANAGE(),
  } as const
  if (tx.link !== 'reimbursement') return { ...base, text: t('links.summary.reimbursementOffer') }
  if (tx.shared) {
    return { ...base, text: t('links.summary.reimbursementOf', { what: groupLabel(tx.shared) }) }
  }
  const of = tx.reimbursement_of
  return {
    ...base,
    text: of
      ? t('links.summary.reimbursementOf', { what: linkedLabel(of) })
      : t('links.summary.reimbursementGone'),
  }
}

function exchangeSummary(tx: Tx): LinkSummary {
  const base = { kind: 'exchange', title: t('links.summary.exchangeTitle'), action: MANAGE() } as const
  const exchange = tx.exchange
  if (exchange === null) {
    if (tx.link === 'exchange') return { ...base, text: t('links.summary.exchangeIncomplete') }
    return { ...base, text: t('links.summary.exchangeOffer') }
  }
  if (exchange.closed) return { ...base, text: t('links.summary.exchangeClosed') }
  if (exchange.pending_cents === 0) return { ...base, text: t('links.summary.exchangeNoPending') }
  const amount = formatMoney(exchange.pending_cents, exchange.pending_currency)
  return { ...base, text: t('links.summary.exchangePending', { amount }) }
}

/** Role of a movement in its investment: contribution, return, capital back or mixed. */
export const ROLE_LABELS: Record<InvestmentRole, string> = {
  contribution: t('links.role.contribution'),
  return: t('links.role.return'),
  capital: t('links.role.capital'),
  mixed: t('links.role.mixed'),
}

function investmentSummary(tx: Tx): LinkSummary {
  const base = { kind: 'investment', title: t('links.summary.investmentTitle'), action: MANAGE() } as const
  const investment = tx.investment
  if (investment === null) {
    if (tx.link === 'investment') return { ...base, text: t('links.summary.investmentOrphan') }
    if (tx.can_invest) {
      return {
        ...base,
        text: t('links.summary.investmentOffer'),
        action: t('links.action.isInvestment'),
      }
    }
    return {
      ...base,
      text: t('links.summary.investmentCreditOffer'),
      action: t('links.action.fromInvestment'),
    }
  }
  const role =
    tx.investment_role === '' ? t('links.summary.movement') : ROLE_LABELS[tx.investment_role]
  return { ...base, text: t('links.summary.investmentText', { role, title: investment.title }) }
}

/** The panel's link lines (shared, reimbursement, exchange, investment), in that order; each
 * opens the link's screen. */
export function linkSummaries(tx: Tx): LinkSummary[] {
  const found: LinkSummary[] = []
  if (showShared(tx)) found.push(sharedSummary(tx))
  if (showReimbursement(tx)) found.push(reimbursementSummary(tx))
  if (showExchange(tx)) found.push(exchangeSummary(tx))
  if (showInvestment(tx)) found.push(investmentSummary(tx))
  return found
}

/** Path of a transaction's links screen. */
export function linkPagePath(fingerprint: string): string {
  return `/transactions/${encodeURIComponent(fingerprint)}`
}

/** Screens that open a links screen and that "Back" returns to as they were: the Transactions
 * list, Pending, Shared and Investments. */
function isListPath(from: unknown): from is string {
  return (
    typeof from === 'string' &&
    /^\/(transactions|pending|shared|investments)(\?|$)/.test(from)
  )
}

/** "Back" without the transaction (missing or not loaded): the list (or Pending) it came from,
 * otherwise Transactions. */
export function listPath(from: unknown): string {
  return isListPath(from) ? from : '/transactions'
}

/** Where "Back" goes: the list it came from (Transactions, Pending…) or, when entered directly,
 * the transaction's month with it selected. */
export function backPath(tx: Pick<Tx, 'fingerprint' | 'day'>, from: unknown): string {
  if (isListPath(from)) return from
  const params = new URLSearchParams({ month: tx.day.slice(0, 7), tx: tx.fingerprint })
  return `/transactions?${params.toString()}`
}
