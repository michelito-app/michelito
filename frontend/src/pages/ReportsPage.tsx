import { useSearchParams } from 'react-router'
import { HostedEmpty } from '@/components/onboarding/HostedEmpty'
import { isHosted, useMode } from '@/lib/demo'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { LoadError } from '@/components/LoadError'
import { CompareTable } from '@/components/reports/CompareTable'
import { InsightsSection } from '@/components/reports/InsightsSection'
import { MonthDetail } from '@/components/reports/MonthDetail'
import { ReviewHistory } from '@/components/reports/ReviewHistory'
import { PANEL } from '@/components/summary/styles'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { scopeText } from '@/lib/accountFilter'
import { resolveMonth } from '@/lib/months'
import { useComparison, useMonths } from '@/lib/queries'
import { FROM_PARAM, orderedRange, parseRange, type Range, TO_PARAM } from '@/lib/reports'
import { useAccountSelection } from '@/lib/useAccountSelection'
import { cn } from '@/lib/utils'

/** Reports screen: compare months, saved analyses and the "To review" history, with the chosen
 * accounts (the same as the Summary's). The range lives in the URL (`from`, `to`). */
const MONTH_PARAM = 'month'

export function ReportsPage() {
  const [params, setParams] = useSearchParams()
  const { selection, accounts, ready, select } = useAccountSelection()
  const months = useMonths(selection, ready)
  const range = months.data ? parseRange(params, months.data) : { from: null, to: null }
  const comparison = useComparison(range, selection, ready && months.isSuccess)
  const month = months.data ? resolveMonth(months.data, params.get(MONTH_PARAM)) : null

  // The month of the detail travels in the URL (`month`), next to the range.
  function changeMonth(next: string | null) {
    setParams((current) => {
      const copy = new URLSearchParams(current)
      if (next) copy.set(MONTH_PARAM, next)
      else copy.delete(MONTH_PARAM)
      return copy
    })
  }

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
          <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">{t('reports.page.title')}</h1>
          {accounts.length > 1 && (
            <AccountPicker selection={selection} accounts={accounts} onChange={select} />
          )}
        </div>
        <p className="text-[13px] text-muted-foreground">
          {t('reports.page.subtitle', { scope: scopeText(selection, accounts) })}
        </p>
      </header>
      <div className="flex min-w-0 flex-col gap-6">
        {ready && months.data && month && (
          <MonthDetail
            month={month}
            months={months.data}
            onMonth={changeMonth}
            selection={selection}
            accounts={accounts}
          />
        )}
        {months.isError ? (
          <LoadError what={t('summary.page.months')} error={months.error} onRetry={() => months.refetch()} />
        ) : comparison.isError ? (
          <LoadError what={t('reports.page.comparison')} error={comparison.error} onRetry={() => comparison.refetch()} />
        ) : comparison.data && months.data ? (
          <div aria-busy={comparison.isPlaceholderData} className={cn('min-w-0', comparison.isPlaceholderData && 'opacity-60')}>
            {comparison.data.months.length === 0 ? (
              <NoMonths />
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

function NoMonths() {
  if (isHosted(useMode())) return <HostedEmpty view="reports" />
  return (
    <p className={cn(PANEL, 'px-6 py-5 text-sm text-muted-foreground')}>{t('reports.page.empty')}</p>
  )
}
