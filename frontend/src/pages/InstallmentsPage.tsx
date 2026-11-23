import { Plus } from 'lucide-react'
import { useState } from 'react'
import { NewPlanSheet } from '@/components/installments/NewPlanSheet'
import { PlanCard } from '@/components/installments/PlanCard'
import { LoadError } from '@/components/LoadError'
import { PANEL } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { useInstallments } from '@/lib/installmentQueries'
import { cn } from '@/lib/utils'

/** "Cuotas": every installment plan's card and "New plan" (from one of its charges). */
export function InstallmentsPage() {
  const [creating, setCreating] = useState(false)
  return (
    <div className="flex max-w-[960px] flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">
            {t('installments.page.title')}
          </h1>
          <p className="text-[13px] text-muted-foreground">{t('installments.page.subtitle')}</p>
        </div>
        <Button
          type="button"
          onClick={() => setCreating(true)}
          className="h-11 gap-1.5 rounded-xl px-4 text-sm font-semibold"
        >
          <Plus size={16} aria-hidden="true" />
          {t('installments.page.new')}
        </Button>
      </header>
      <Plans />
      {creating && (
        <NewPlanSheet onClose={() => setCreating(false)} onCreated={() => setCreating(false)} />
      )}
    </div>
  )
}

function Plans() {
  const plans = useInstallments()
  if (plans.isError) {
    return (
      <LoadError
        what={t('installments.plans.loadWhat')}
        error={plans.error}
        onRetry={() => plans.refetch()}
      />
    )
  }
  if (plans.isPending) {
    return (
      <div aria-busy="true" aria-label={t('installments.page.loading')} className="grid gap-3 md:grid-cols-2">
        {[0, 1].map((i) => (
          <Skeleton key={i} className="h-56 rounded-xl" />
        ))}
      </div>
    )
  }
  if (plans.data.length === 0) {
    return (
      <div className={cn(PANEL, 'flex flex-col gap-1.5 px-6 py-10 text-center')}>
        <p className="text-[15px] font-semibold">{t('installments.page.empty.title')}</p>
        <p className="text-[13px] text-muted-foreground">{t('installments.page.empty.hint')}</p>
      </div>
    )
  }
  return (
    <section
      data-testid="installment-plans"
      aria-label={t('installments.plans.title')}
      className="grid gap-3 md:grid-cols-2"
    >
      {plans.data.map((plan) => (
        <PlanCard key={plan.id} plan={plan} />
      ))}
    </section>
  )
}
