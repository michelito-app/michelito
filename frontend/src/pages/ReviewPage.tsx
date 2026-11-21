import { useSearchParams } from 'react-router'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { LoadError } from '@/components/LoadError'
import { MonthHeader } from '@/components/MonthHeader'
import { NoMonths } from '@/components/cards/NoMonths'
import { ReviewCard } from '@/components/summary/ReviewCard'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { ACCOUNTS_PARAM, scopeText } from '@/lib/accountFilter'
import { neighbors, resolveMonth, returnTarget } from '@/lib/months'
import { useMonths } from '@/lib/queries'
import { useAccountSelection } from '@/lib/useAccountSelection'

/** The review list (`/review?month=…`), where the Summary's «To review» card leads: every item of
 * the month with its actions. Same month and accounts as the Summary. */
export function ReviewPage() {
  const [params, setParams] = useSearchParams()
  const { selection, accounts, ready, select } = useAccountSelection()
  const months = useMonths(selection, ready)
  const month = months.data ? resolveMonth(months.data, params.get('month')) : null

  function goTo(target: string | null) {
    const next = new URLSearchParams(target ? { month: target } : {})
    const chosen = params.get(ACCOUNTS_PARAM)
    if (chosen) next.set(ACCOUNTS_PARAM, chosen)
    setParams(next)
  }

  if (months.isError) {
    return <LoadError what={t('summary.page.months')} error={months.error} onRetry={() => months.refetch()} />
  }
  if (!ready || months.isPending) return <Skeleton className="h-[320px] rounded-2xl" />
  if (month === null) return <NoMonths />
  const option = months.data.find((o) => o.month === month) ?? months.data[0]
  return (
    <>
      <MonthHeader
        month={month}
        label={option.label}
        months={months.data}
        neighbors={neighbors(months.data, month)}
        onNavigate={goTo}
        home={returnTarget(months.data, month)}
        onReturn={() => goTo(null)}
        scope={scopeText(selection, accounts)}
        title={t('home.reviewPage.title')}
        picker={
          accounts.length > 1 && (
            <AccountPicker selection={selection} accounts={accounts} onChange={select} />
          )
        }
      />
      <ReviewCard key={`${month}-${selection?.join(',') ?? 'all'}`} month={month} selection={selection} expanded />
    </>
  )
}
