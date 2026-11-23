// Installment plans ("Plan de cuotas") in the interface (pure logic). The server links the
// charges and counts what is left (src/michelito/web/installments.py); this only builds texts,
// the form's state and its request body.
import { t } from '@/i18n'
import type {
  InstallmentBody,
  InstallmentDraft,
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

/** "US$ 150.00 al mes · VISA ···4242". */
export function eachLine(plan: InstallmentPlan): string {
  return t('installments.plan.each', {
    amount: formatMoney(plan.amount_cents, plan.currency),
    account: plan.account_label,
  })
}

/** A member's plan: "Lo paga Ana · grupo Casa"; null for the user's own. */
export function ownerLine(plan: InstallmentPlan): string | null {
  if (plan.group_id === null || plan.contact_name === null || plan.group_name === null) return null
  return t('installments.plan.paidBy', { contact: plan.contact_name, group: plan.group_name })
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
    tx.amount_cents > 0 &&
    cards.has(tx.account) &&
    !tx.installment &&
    !tx.provisional &&
    !NOT_A_PURCHASE.has(tx.link)
  )
}

export type Owner = 'me' | 'member'

/** The "It is an installment…" form as typed (numbers as text until saved). */
export interface PlanForm {
  name: string
  count: string
  number: string
  owner: Owner
  groupId: number | null
  contactId: number | null
}

/** The form prefilled from the draft: its name and installment number, 6 installments (or as
 * many as the number needs). */
export function initialForm(draft: InstallmentDraft): PlanForm {
  return {
    name: draft.name.slice(0, NAME_MAX),
    count: String(Math.max(DEFAULT_COUNT, draft.number)),
    number: String(draft.number),
    owner: 'me',
    groupId: null,
    contactId: null,
  }
}

/** "Encontramos 2 cuotas anteriores." when earlier installments were found; else null. */
export function foundLine(draft: Pick<InstallmentDraft, 'paid_before'>): string | null {
  if (draft.paid_before <= 0) return null
  return t('installments.form.found', { count: draft.paid_before })
}

export type BodyResult = { body: InstallmentBody; error: null } | { body: null; error: string }

function wholeNumber(text: string): number | null {
  const clean = text.trim()
  return /^\d+$/.test(clean) ? Number(clean) : null
}

/** The POST body, or the first thing to fix in the form. */
export function planBody(fingerprint: string, form: PlanForm): BodyResult {
  const name = form.name.trim()
  if (name.length === 0 || name.length > NAME_MAX) {
    return { body: null, error: t('installments.form.invalid.name', { max: NAME_MAX }) }
  }
  const count = wholeNumber(form.count)
  if (count === null || count < COUNT_MIN || count > COUNT_MAX) {
    return {
      body: null,
      error: t('installments.form.invalid.count', { min: COUNT_MIN, max: COUNT_MAX }),
    }
  }
  const number = wholeNumber(form.number)
  if (number === null || number < 1 || number > count) {
    return { body: null, error: t('installments.form.invalid.number', { count }) }
  }
  const base = { fingerprint, name, count, number }
  if (form.owner === 'me') return { body: base, error: null }
  if (form.groupId === null || form.contactId === null) {
    return { body: null, error: t('installments.form.invalid.member') }
  }
  return { body: { ...base, group_id: form.groupId, contact_id: form.contactId }, error: null }
}

/** The plan a row belongs to, among the loaded ones. */
export function planOf(
  plans: readonly InstallmentPlan[] | undefined,
  id: number | undefined,
): InstallmentPlan | null {
  if (id === undefined) return null
  return plans?.find((plan) => plan.id === id) ?? null
}
