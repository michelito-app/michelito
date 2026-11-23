import { useState } from 'react'
import { Action, Failure, SECTION_TITLE } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import type { InstallmentPlan } from '@/lib/api'
import { useChangeInstallmentLink } from '@/lib/installmentQueries'
import { monthPhrase } from '@/lib/months'
import { ChargePicker } from './ChargePicker'

/** In "Edit plan": the linked charges (each with "Remove") and "Add charge", which lists the
 * card's charges the plan can take, each as the installment it would be. */
export function PlanCharges({ plan }: { plan: InstallmentPlan }) {
  const change = useChangeInstallmentLink()
  const [adding, setAdding] = useState(false)
  const linked = plan.installments.filter((item) => item.fingerprint !== null)
  return (
    <section data-testid="installment-plan-charges" className="flex flex-col gap-2">
      <h3 className={SECTION_TITLE}>{t('installments.edit.charges')}</h3>
      {linked.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('installments.edit.noCharges')}</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded-xl border border-border">
          {linked.map((item) => (
            <li key={item.number} className="flex min-h-12 items-center gap-3 px-3 py-1.5 text-sm">
              <span className="min-w-0 flex-1 font-medium tabular-nums">
                {t('installments.edit.chargeLine', {
                  number: item.number,
                  month: monthPhrase(item.month),
                })}
              </span>
              <Action
                label={t('installments.edit.removeLabel', { number: item.number })}
                disabled={change.isPending}
                onClick={() =>
                  change.mutate({ planId: plan.id, fingerprint: item.fingerprint!, number: null })
                }
              >
                {t('installments.edit.remove')}
              </Action>
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <div className="flex flex-col gap-2">
          <p className="text-[13px] text-ink-2">{t('installments.edit.addHint')}</p>
          <ChargePicker
            planId={plan.id}
            empty={t('installments.edit.addEmpty')}
            disabled={change.isPending}
            onPick={(charge) =>
              change.mutate(
                { planId: plan.id, fingerprint: charge.fingerprint, number: charge.number ?? 1 },
                { onSuccess: () => setAdding(false) },
              )
            }
          />
        </div>
      ) : (
        <div>
          <Action onClick={() => setAdding(true)}>{t('installments.edit.add')}</Action>
        </div>
      )}
      <Failure error={change.error} />
    </section>
  )
}
