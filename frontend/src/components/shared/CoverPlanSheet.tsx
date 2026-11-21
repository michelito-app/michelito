import { Action, Failure, LoadFailure } from '@/components/transactions/linkParts'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { t } from '@/i18n'
import { afterText, planBody, planPaymentLine } from '@/lib/coverPlan'
import { conversionText } from '@/lib/ledger'
import { formatMoney } from '@/lib/links'
import type { CoverSuggestion, Group } from '@/lib/sharedApi'
import { ledger, useCoverPlan, useLedgerWrite } from '@/lib/sharedQueries'
import { LIST_CARD } from './styles'

const LABEL = 'text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase'

interface CoverPlanSheetProps {
  group: Group
  cover: CoverSuggestion
  onClose: () => void
}

/** "Yes" to "Ana paid … too much in 3 payments…": each payment with what it would cover of each
 * person (payer first, each counting what the earlier ones covered; conversions shown) and how
 * the balances end up. "Confirm" applies all of them as one change (one undo); a single amount
 * is changed later from that payment's own detail. */
export function CoverPlanSheet({ group, cover, onClose }: CoverPlanSheetProps) {
  const plan = useCoverPlan(group.id, true)
  const write = useLedgerWrite()
  return (
    <BottomSheet title={t('shared.plan.title')} onClose={onClose}>
      <p className="text-sm font-semibold break-words">{cover.text}</p>
      <p className="text-[13px] text-muted-foreground">
        {t('shared.plan.hint', { name: cover.payer_name })}
      </p>
      {plan.isError ? (
        <LoadFailure what={t('shared.load')} error={plan.error} />
      ) : plan.isPending ? (
        <p className="text-[13px] text-muted-foreground">{t('shared.plan.loading')}</p>
      ) : (
        <>
          <ol aria-label={t('shared.plan.paymentsLabel')} className="flex flex-col gap-3">
            {plan.data.payments.map((payment) => (
              <li key={payment.payment_id} data-testid="plan-payment" className="flex flex-col gap-1.5">
                <h3 className={LABEL}>{planPaymentLine(payment)}</h3>
                <ul className={LIST_CARD}>
                  {payment.allocations.map((part) => {
                    const converted = conversionText(part, payment.currency, payment.rate)
                    return (
                      <li key={part.contact_id} className="flex flex-col px-3.5 py-2 text-sm">
                        <span className="flex items-center justify-between gap-3">
                          <span className="min-w-0 truncate">{part.name}</span>
                          <span className="shrink-0 font-semibold tabular-nums">
                            {formatMoney(part.cents, payment.currency)}
                          </span>
                        </span>
                        {converted && (
                          <span className="text-[12px] text-muted-foreground">{converted}</span>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </li>
            ))}
          </ol>
          <div className="flex flex-col gap-1.5">
            <h3 className={LABEL}>{t('shared.plan.after')}</h3>
            <ul className={LIST_CARD} aria-label={t('shared.plan.after')}>
              {plan.data.after.map((person) => (
                <li
                  key={person.contact_id}
                  className="flex min-h-11 items-center justify-between gap-3 px-3.5 text-sm"
                >
                  <span className="min-w-0 truncate">{person.name}</span>
                  <span className="shrink-0 text-right font-semibold">{afterText(person)}</span>
                </li>
              ))}
            </ul>
          </div>
          <Failure error={write.error} />
          <div className="flex flex-wrap gap-2">
            <Action
              primary
              disabled={write.isPending}
              onClick={() =>
                write.mutate(() => ledger.applyCover(group.id, planBody(plan.data)), {
                  onSuccess: onClose,
                })
              }
            >
              {t('shared.plan.confirm')}
            </Action>
            <Action onClick={onClose}>{t('shared.group.removeCancel')}</Action>
          </div>
        </>
      )}
    </BottomSheet>
  )
}
