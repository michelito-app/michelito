// "Yes" to a suggestion over one or several payments (pure): what the review sheet shows and
// what it sends. The server makes the plan (src/michelito/analysis/ledger_cover.py).
import { t } from '@/i18n'
import { memberBalanceText } from './ledger'
import { formatMoney } from './links'
import { shortDay } from './months'
import type { ReviewItem } from './api'
import type { CoverAfter, CoverBody, CoverPayment, CoverPlan } from './sharedApi'

/** The payments a "paid for others?" review item is about (all of them answer "No" at once). */
export function itemPayments(item: Pick<ReviewItem, 'payment_id' | 'payment_ids'>): number[] {
  if (item.payment_ids && item.payment_ids.length > 0) return item.payment_ids
  return item.payment_id == null ? [] : [item.payment_id]
}

/** The body that applies the plan as one change: every payment with its proposed parts. */
export function planBody(plan: Pick<CoverPlan, 'payments'>): CoverBody {
  return {
    payments: plan.payments.map((payment) => ({
      payment_id: payment.payment_id,
      allocations: payment.allocations
        .filter((part) => part.cents > 0)
        .map((part) => ({ contact_id: part.contact_id, cents: part.cents })),
    })),
  }
}

/** "Payment of 3 Oct · RD$ 98,000". */
export function planPaymentLine(payment: Pick<CoverPayment, 'day' | 'amount_cents' | 'currency'>): string {
  return t('shared.plan.payment', {
    day: shortDay(payment.day),
    amount: formatMoney(payment.amount_cents, payment.currency),
  })
}

/** A person's balance once the plan is applied (with its exchange leftover). */
export function afterText(person: Pick<CoverAfter, 'balance' | 'leftover'>): string {
  return memberBalanceText(person)
}
