// Installment plans ("Plan de cuotas") in the interface (pure logic). The server links the
// charges and counts what is left (src/michelito/web/installments.py); this only builds texts.
// The forms' state and request bodies live in installmentForm.ts.
import { t } from '@/i18n'
import type {
  InstallmentPlan,
  InstallmentState,
  Tx,
  TxInstallment,
} from './api'
import { formatMoney } from './links'
import { monthPhrase } from './months'

/** Limits the server checks too (src/michelito/migrations_v25.py). */
export const NAME_MAX = 80
export const COUNT_MIN = 2
export const COUNT_MAX = 120
/** The usual store plan: what "Number of installments" starts with. */
export const DEFAULT_COUNT = 6

/** A row's line: "cuota 3/6 · Phone (Store)"; null outside a plan. */
export function installmentTag(tx: Pick<Tx, 'installment'>): string | null {
  const tag = tx.installment
  if (!tag) return null
  return t('installments.row.tag', { number: tag.number, count: tag.count, name: tag.name })
}

/** In the detail: "Cuota 3 de 6 · Phone (Store)". */
export function linkedLine(tag: TxInstallment): string {
  return t('installments.detail.linked', { number: tag.number, count: tag.count, name: tag.name })
}

/** "3 de 6 · faltan US$ 450.00 · termina en mayo 2026" (or, all paid, that it ended). */
export function planSummary(plan: InstallmentPlan): string {
  const month = monthPhrase(plan.last_month)
  if (plan.paid >= plan.count) return t('installments.plan.done', { count: plan.count, month })
  return t('installments.plan.summary', {
    paid: plan.paid,
    count: plan.count,
    amount: formatMoney(plan.remaining_cents, plan.currency),
    month,
  })
}

/** The installment amount and its card (see the `installments.plan.each` text). */
export function eachLine(plan: InstallmentPlan): string {
  return t('installments.plan.each', {
    amount: formatMoney(plan.amount_cents, plan.currency),
    account: plan.account_label,
  })
}

/** A person's plan: "For Ana" (`installments.plan.paidBy`); null for the user's own. */
export function ownerLine(plan: Pick<InstallmentPlan, 'contact_name'>): string | null {
  if (plan.contact_name === null) return null
  return t('installments.plan.paidBy', { contact: plan.contact_name })
}

/** Accessible name of an installment: "Cuota 2, enero 2026: pagada". */
export function installmentLabel(number: number, month: string, state: InstallmentState): string {
  return t('installments.plan.installment', {
    number,
    month: monthPhrase(month),
    state: t(`installments.plan.state.${state}`),
  })
}

/** Paid installments as a share of the plan (0 to 1), for the progress bar. */
export function progress(plan: Pick<InstallmentPlan, 'paid' | 'count'>): number {
  if (plan.count <= 0) return 0
  return Math.min(1, Math.max(0, plan.paid / plan.count))
}

/** Links that make a charge something else (the server refuses them as installments). */
const NOT_A_PURCHASE = new Set<Tx['link']>(['exchange', 'investment'])

/** Is "It is an installment…" offered? A charge (a positive expense) on a credit card, from its
 * statement (not provisional), not an exchange or investment leg and not in a plan yet. */
export function canBeInstallment(tx: Tx, cards: ReadonlySet<string>): boolean {
  return (
    tx.kind === 'expense' &&
    // A shared charge counts as the statement amount (the user's own part may be zero).
    (tx.gross_cents ?? tx.amount_cents) > 0 &&
    cards.has(tx.account) &&
    !tx.installment &&
    !tx.provisional &&
    !NOT_A_PURCHASE.has(tx.link)
  )
}

/** The group a row is shared in as an expense the user paid (null otherwise): its other member
 * is the owner suggested. */
export function sharedGroupOf(tx: Pick<Tx, 'ledger'>): number | null {
  return tx.ledger?.role === 'entry' ? tx.ledger.group_id : null
}

/** The plan a row belongs to, among the loaded ones. */
export function planOf(
  plans: readonly InstallmentPlan[] | undefined,
  id: number | undefined,
): InstallmentPlan | null {
  if (id === undefined) return null
  return plans?.find((plan) => plan.id === id) ?? null
}
