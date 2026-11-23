import { Plus } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { NewPlanSheet } from '@/components/installments/NewPlanSheet'
import { PlanCard } from '@/components/installments/PlanCard'
import { LoanFormSheet } from '@/components/loans/LoanFormSheet'
import { LoanSummaryCard } from '@/components/loans/LoanSummaryCard'
import { LoadError } from '@/components/LoadError'
import { PANEL } from '@/components/summary/styles'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { useInstallments } from '@/lib/installmentQueries'
import { useLoans } from '@/lib/loanQueries'
import { cn } from '@/lib/utils'

/** «Deudas»: the loans and the installment plans (a plan is a loan at 0 %), each with "New". */
export function InstallmentsPage() {
  const [creating, setCreating] = useState<'loan' | 'plan' | null>(null)
  return (
    <div className="flex max-w-[960px] flex-col gap-8">
      <header className="flex min-w-0 flex-col gap-1">
        <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">
          {t('loans.page.title')}
        </h1>
        <p className="text-[13px] text-muted-foreground">{t('loans.page.subtitle')}</p>
      </header>
      <Section
        title={t('loans.section.loans')}
        action={t('loans.section.new')}
        onNew={() => setCreating('loan')}
      >
        <Loans />
      </Section>
      <Section
        title={t('loans.section.plans')}
        action={t('installments.page.new')}
        onNew={() => setCreating('plan')}
      >
        <Plans />
      </Section>
      {creating === 'plan' && (
        <NewPlanSheet onClose={() => setCreating(null)} onCreated={() => setCreating(null)} />
      )}
      {creating === 'loan' && <LoanFormSheet loan={null} onClose={() => setCreating(null)} />}
    </div>
  )
}

interface SectionProps {
  title: string
  action: string
  onNew: () => void
  children: ReactNode
}

function Section({ title, action, onNew, children }: SectionProps) {
  return (
    <section className="flex flex-col gap-3" aria-label={title}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 className="text-lg font-bold tracking-tight">{title}</h2>
        <Button
          type="button"
          onClick={onNew}
          className="h-11 gap-1.5 rounded-xl px-4 text-sm font-semibold"
        >
          <Plus size={16} aria-hidden="true" />
          {action}
        </Button>
      </div>
      {children}
    </section>
  )
}

function Busy() {
  return (
    <div aria-busy="true" aria-label={t('loans.page.loading')} className="grid gap-3 md:grid-cols-2">
      {[0, 1].map((i) => (
        <Skeleton key={i} className="h-40 rounded-xl" />
      ))}
    </div>
  )
}

function Empty({ title, hint }: { title: string; hint: string }) {
  return (
    <div className={cn(PANEL, 'flex flex-col gap-1.5 px-6 py-8 text-center')}>
      <p className="text-[15px] font-semibold">{title}</p>
      <p className="text-[13px] text-muted-foreground">{hint}</p>
    </div>
  )
}

function Loans() {
  const loans = useLoans()
  if (loans.isError) {
    return (
      <LoadError
        what={t('loans.section.loadWhat')}
        error={loans.error}
        onRetry={() => loans.refetch()}
      />
    )
  }
  if (loans.isPending) return <Busy />
  if (loans.data.length === 0) {
    return <Empty title={t('loans.section.empty.title')} hint={t('loans.section.empty.hint')} />
  }
  return (
    <div data-testid="loans" className="grid gap-3 md:grid-cols-2">
      {loans.data.map((loan) => (
        <LoanSummaryCard key={loan.id} loan={loan} />
      ))}
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
  if (plans.isPending) return <Busy />
  if (plans.data.length === 0) {
    return (
      <Empty title={t('installments.page.empty.title')} hint={t('installments.page.empty.hint')} />
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
