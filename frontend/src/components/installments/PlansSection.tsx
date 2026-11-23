import { useId } from 'react'
import { PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { LoadFailure } from '@/components/transactions/linkParts'
import { t } from '@/i18n'
import { useInstallments } from '@/lib/installmentQueries'
import { cn } from '@/lib/utils'
import { PlanCard } from './PlanCard'

/** Recurring's "Installment plans": every plan's card (nothing while there are none). */
export function PlansSection() {
  const titleId = useId()
  const plans = useInstallments()
  if (plans.isError) {
    return <LoadFailure what={t('installments.plans.loadWhat')} error={plans.error} />
  }
  if (!plans.data?.length) return null
  return (
    <section
      data-testid="installment-plans"
      aria-labelledby={titleId}
      className={cn(PANEL, '@container overflow-hidden')}
    >
      <header className="border-b border-[#EFEFEA] px-4 py-4 sm:px-5">
        <h2 id={titleId} className={PANEL_TITLE}>
          {t('installments.plans.title')}
          <span className="ml-2 text-[13px] font-medium text-muted-foreground">
            {plans.data.length}
          </span>
        </h2>
      </header>
      <div className="grid gap-3 p-3 sm:p-4 @2xl:grid-cols-2">
        {plans.data.map((plan) => (
          <PlanCard key={plan.id} plan={plan} />
        ))}
      </div>
    </section>
  )
}
