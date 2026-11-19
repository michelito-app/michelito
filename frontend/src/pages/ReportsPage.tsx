import { useSearchParams } from 'react-router'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { LoadError } from '@/components/LoadError'
import { CompareTable } from '@/components/reports/CompareTable'
import { InsightsSection } from '@/components/reports/InsightsSection'
import { ReviewHistory } from '@/components/reports/ReviewHistory'
import { PANEL } from '@/components/summary/styles'
import { Skeleton } from '@/components/ui/skeleton'
import { scopeText } from '@/lib/accountFilter'
import { useComparison, useMonths } from '@/lib/queries'
import { FROM_PARAM, orderedRange, parseRange, type Range, TO_PARAM } from '@/lib/reports'
import { useAccountSelection } from '@/lib/useAccountSelection'
import { cn } from '@/lib/utils'

/** Pantalla Reportes: comparar meses, análisis guardados e historial de «Para revisar», con
 * las cuentas elegidas (las mismas del Resumen). El rango vive en la URL (`desde`, `hasta`). */
export function ReportsPage() {
  const [params, setParams] = useSearchParams()
  const { selection, accounts, ready, select } = useAccountSelection()
  const months = useMonths(selection, ready)
  const range = months.data ? parseRange(params, months.data) : { from: null, to: null }
  const comparison = useComparison(range, selection, ready && months.isSuccess)

  function changeRange(next: Range) {
    const ordered = orderedRange(next)
    setParams((current) => {
      const copy = new URLSearchParams(current)
      for (const [key, value] of [
        [FROM_PARAM, ordered.from],
        [TO_PARAM, ordered.to],
      ] as const) {
        if (value) copy.set(key, value)
        else copy.delete(key)
      }
      return copy
    })
  }

  return (
    <>
      <header className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">Reportes</h1>
          {accounts.length > 1 && (
            <AccountPicker selection={selection} accounts={accounts} onChange={select} />
          )}
        </div>
        <p className="text-[13px] text-muted-foreground">
          Mes a mes en {scopeText(selection, accounts)} · montos en RD$
        </p>
      </header>
      <div className="flex min-w-0 flex-col gap-6">
        {months.isError ? (
          <LoadError what="los meses" error={months.error} onRetry={() => months.refetch()} />
        ) : comparison.isError ? (
          <LoadError what="la comparación" error={comparison.error} onRetry={() => comparison.refetch()} />
        ) : comparison.data && months.data ? (
          <div aria-busy={comparison.isPlaceholderData} className={cn('min-w-0', comparison.isPlaceholderData && 'opacity-60')}>
            {comparison.data.months.length === 0 ? (
              <p className={cn(PANEL, 'px-6 py-5 text-sm text-muted-foreground')}>
                Todavía no hay meses para comparar.
              </p>
            ) : (
              <CompareTable
                data={comparison.data}
                options={months.data}
                range={range}
                onRange={changeRange}
                selection={selection}
              />
            )}
          </div>
        ) : (
          <Skeleton className="h-[320px] rounded-2xl" />
        )}
        {months.data && <InsightsSection months={months.data} selection={selection} />}
        {ready && <ReviewHistory selection={selection} />}
      </div>
    </>
  )
}
