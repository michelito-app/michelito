import { useSearchParams } from 'react-router'
import { HostedEmpty } from '@/components/onboarding/HostedEmpty'
import { isHosted, useMode } from '@/lib/demo'
import { CategoryBudget } from '@/components/budget/CategoryBudget'
import { ReservesSection } from '@/components/budget/ReservesSection'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { LoadError } from '@/components/LoadError'
import { MonthHeader } from '@/components/MonthHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { ACCOUNTS_PARAM, scopeText } from '@/lib/accountFilter'
import { useBudget, useReserves } from '@/lib/budgetQueries'
import { localToday, neighbors, resolveMonth, returnTarget } from '@/lib/months'
import { useCategories, useMonths } from '@/lib/queries'
import { useAccountSelection } from '@/lib/useAccountSelection'
import { cn } from '@/lib/utils'

/** Budget screen: the month (`?month=`, with the same header as the Summary) and the chosen
 * accounts. On top the categories (caps and spending), below the reserves. */
export function BudgetPage() {
  const [params, setParams] = useSearchParams()
  const { selection, accounts, ready, select } = useAccountSelection()
  const months = useMonths(selection, ready)
  const month = months.data ? resolveMonth(months.data, params.get('month')) : null
  const budget = useBudget(month, selection)
  const reserves = useReserves(selection, ready)
  const categories = useCategories()
  const home = months.data && month ? returnTarget(months.data, month) : null

  function goTo(target: string | null) {
    const next = new URLSearchParams(target ? { month: target } : {})
    const chosen = params.get(ACCOUNTS_PARAM)
    if (chosen) next.set(ACCOUNTS_PARAM, chosen)
    setParams(next)
  }

  if (months.isError) {
    return <LoadError what={t('budget.load.months')} error={months.error} onRetry={() => months.refetch()} />
  }
  if (!ready || months.isPending) return <Skeleton className="h-[300px] rounded-2xl" />
  if (month === null) {
    return <NoStatements />
  }
  const option = months.data.find((o) => o.month === month) ?? months.data[0]
  return (
    <>
      <MonthHeader
        month={month}
        label={option.label}
        months={months.data}
        neighbors={neighbors(months.data, month)}
        onNavigate={goTo}
        home={home}
        onReturn={() => goTo(null)}
        scope={scopeText(selection, accounts)}
        title={t('budget.title')}
        picker={
          accounts.length > 1 && (
            <AccountPicker selection={selection} accounts={accounts} onChange={select} />
          )
        }
      />
      <div
        aria-busy={budget.isPlaceholderData}
        className={cn(
          'flex max-w-[960px] flex-col gap-6 transition-opacity',
          budget.isPlaceholderData && 'opacity-60',
        )}
      >
        {budget.isError ? (
          <LoadError what={t('budget.load.budget')} error={budget.error} onRetry={() => budget.refetch()} />
        ) : budget.data ? (
          <CategoryBudget budget={budget.data} />
        ) : (
          <Skeleton className="h-[300px] rounded-2xl" />
        )}
        {reserves.isError ? (
          <LoadError
            what={t('budget.load.reserves')}
            error={reserves.error}
            onRetry={() => reserves.refetch()}
          />
        ) : reserves.data && categories.data ? (
          <ReservesSection
            data={reserves.data}
            categories={categories.data}
            today={localToday().slice(0, 7)}
            selection={selection}
          />
        ) : (
          <Skeleton className="h-[200px] rounded-2xl" />
        )}
      </div>
    </>
  )
}

function NoStatements() {
  if (isHosted(useMode())) return <HostedEmpty view="budget" />
  return <p className="text-sm text-muted-foreground">{t('budget.noStatements')}</p>
}
