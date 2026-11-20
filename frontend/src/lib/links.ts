// Links of a transaction in the interface (pure logic): its shared group, currency exchanges and
// investments. The server does the math (src/michelito/analysis/ledger.py and exchanges.py);
// this only builds texts, badges and request bodies.
import { t } from '@/i18n'
import type { CurrencyCents, ExchangeInfo, InvestmentRole, LinkedTx, Tx } from './api'
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

export interface LinkBadge {
  label: string
  tone: 'shared' | 'linked' | 'suggested'
}

/** A row's link badges: shared (with what you are owed), a group movement, a group payment, an
 * exchange or an investment, and their suggestions. */
export function linkBadges(tx: Tx): LinkBadge[] {
  const badges: LinkBadge[] = []
  if (tx.link === 'shared' && tx.ledger) {
    badges.push({ label: t('links.badge.shared'), tone: 'shared' })
    if (tx.pending_cents > 0) {
      const amount = formatMoney(tx.pending_cents, tx.currency)
      badges.push({ label: t('links.badge.owed', { amount }), tone: 'shared' })
    }
  }
  if (tx.link === 'group') badges.push({ label: t('links.badge.group'), tone: 'shared' })
  if (tx.link === 'reimbursement') badges.push({ label: t('links.badge.reimbursement'), tone: 'linked' })
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

/** A row's statement amount (before splitting). */
export function grossCents(tx: Tx): number {
  return tx.gross_cents ?? tx.amount_cents
}

/** "1,850.50" or "1850,5" → cents; null unless it is a positive amount with up to 2 decimals. */
export function parseCents(text: string): number | null {
  const clean = text.trim().replace(/^(RD|US)?\$\s*/i, '').replaceAll(',', '')
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return null
  const cents = Math.round(Number(clean) * 100)
  return cents > 0 ? cents : null
}

/** Is the Shared line shown? An expense that can go to a group, or a row already in one (an
 * entry, a payment or a group movement). */
export function showShared(tx: Tx): boolean {
  return tx.can_share || tx.ledger !== null
}

/** Is "It is a payment…" offered? A credit that can be a payment received, not in a group yet. */
export function showReimbursement(tx: Tx): boolean {
  return tx.can_reimburse && tx.ledger === null
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

/** A group payment or movement, an exchange leg, an investment or cash box movement: the link
 * sets its category. */
export function categoryLocked(tx: Tx): boolean {
  return (
    tx.link === 'reimbursement' ||
    tx.link === 'group' ||
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

/** A line of the detail panel: the link's status and the button that opens its screen (or, with
 * `href`, the page it goes to: a shared group). */
export interface LinkSummary {
  kind: SummaryKind
  title: string
  text: string
  /** The button's label (manage, share, "it is an investment"…). */
  action: string
  href?: string
}

const MANAGE = () => t('links.action.manage')

/** Path of a shared group's page. */
export function groupPath(id: number): string {
  return `/shared/${id}`
}

/** The row in its group: "Part of group X · your share RD$ Y" (an entry), a payment, or the
 * user's share of an expense someone else paid; otherwise the offer to share it. */
function sharedSummary(tx: Tx): LinkSummary {
  const base = { kind: 'shared', title: t('shared.tx.title') } as const
  const ledger = tx.ledger
  if (ledger === null) return { ...base, text: t('shared.tx.offer'), action: t('shared.tx.share') }
  const open = { action: t('shared.tx.openGroup'), href: groupPath(ledger.group_id) }
  const group = ledger.group_name
  if (ledger.role === 'payment') return { ...base, ...open, text: t('shared.tx.payment', { group }) }
  const share = formatMoney(ledger.my_share_cents ?? 0, ledger.currency)
  if (ledger.role === 'group') {
    return { ...base, ...open, text: t('shared.tx.group', { payer: ledger.paid_by_name, group }) }
  }
  const pending = ledger.pending_cents ?? 0
  const text =
    pending > 0
      ? t('shared.tx.entryPending', { group, share, pending: formatMoney(pending, ledger.currency) })
      : t('shared.tx.entry', { group, share })
  return { ...base, ...open, text }
}

/** A credit not in a group: "Did someone from a group pay you this?". */
function reimbursementSummary(): LinkSummary {
  return {
    kind: 'reimbursement',
    title: t('shared.credit.title'),
    text: t('shared.tx.creditOffer'),
    action: t('shared.tx.record'),
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
  if (showReimbursement(tx)) found.push(reimbursementSummary())
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
