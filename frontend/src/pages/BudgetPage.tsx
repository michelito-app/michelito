import { useSearchParams } from 'react-router'
import { CategoryBudget } from '@/components/budget/CategoryBudget'
import { ReservesSection } from '@/components/budget/ReservesSection'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { LoadError } from '@/components/LoadError'
import { MonthHeader } from '@/components/MonthHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { ACCOUNTS_PARAM, scopeText } from '@/lib/accountFilter'
import { useBudget, useReserves } from '@/lib/budgetQueries'
import { localToday, neighbors, resolveMonth, returnTarget } from '@/lib/months'
import { useCategories, useMonths } from '@/lib/queries'
import { useAccountSelection } from '@/lib/useAccountSelection'
import { cn } from '@/lib/utils'

/** Pantalla Presupuesto: el mes (`?mes=`, con la misma cabecera que el Resumen) y las cuentas
 * elegidas. Arriba las categorías (topes y lo gastado), debajo las reservas. */
export function BudgetPage() {
  const [params, setParams] = useSearchParams()
  const { selection, accounts, ready, select } = useAccountSelection()
  const months = useMonths(selection, ready)
  const month = months.data ? resolveMonth(months.data, params.get('mes')) : null
  const budget = useBudget(month, selection)
  const reserves = useReserves(selection, ready)
  const categories = useCategories()
  const home = months.data && month ? returnTarget(months.data, month) : null

  function goTo(target: string | null) {
    const next = new URLSearchParams(target ? { mes: target } : {})
    const chosen = params.get(ACCOUNTS_PARAM)
    if (chosen) next.set(ACCOUNTS_PARAM, chosen)
    setParams(next)
  }

  if (months.isError) {
    return <LoadError what="los meses" error={months.error} onRetry={() => months.refetch()} />
  }
  if (!ready || months.isPending) return <Skeleton className="h-[300px] rounded-2xl" />
  if (month === null) {
    return <p className="text-sm text-muted-foreground">Todavía no hay estados.</p>
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
        title="Presupuesto"
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
          <LoadError what="el presupuesto" error={budget.error} onRetry={() => budget.refetch()} />
        ) : budget.data ? (
          <CategoryBudget budget={budget.data} />
        ) : (
          <Skeleton className="h-[300px] rounded-2xl" />
        )}
        {reserves.isError ? (
          <LoadError
            what="las reservas"
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
