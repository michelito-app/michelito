import { useSearchParams } from 'react-router'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { LoadError } from '@/components/LoadError'
import { BudgetCard } from '@/components/summary/BudgetCard'
import { ByAccount } from '@/components/summary/ByAccount'
import { CategoryTable } from '@/components/summary/CategoryTable'
import { CoverageChips } from '@/components/summary/CoverageChips'
import { InterestCard } from '@/components/summary/InterestCard'
import { Kpis } from '@/components/summary/Kpis'
import { MonthHeader } from '@/components/MonthHeader'
import { MobileSummary } from '@/components/summary/MobileSummary'
import { MonthReading } from '@/components/summary/MonthReading'
import { PendingCard } from '@/components/summary/PendingCard'
import { ReviewCard } from '@/components/summary/ReviewCard'
import { RecurringCard } from '@/components/summary/RecurringCard'
import { PANEL } from '@/components/summary/styles'
import { TrendBars } from '@/components/summary/TrendBars'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { tn } from '@/i18n/nodes'
import {
  ACCOUNTS_PARAM,
  type AccountRef,
  includesCard,
  scopeText,
  type Selection,
} from '@/lib/accountFilter'
import type { MonthOption, Summary } from '@/lib/api'
import { neighbors, resolveMonth, returnTarget } from '@/lib/months'
import { usePublishNavMonth } from '@/lib/navMonth'
import { useMonths, useReview, useSummary } from '@/lib/queries'
import { partialNote } from '@/lib/summary'
import { useAccountSelection } from '@/lib/useAccountSelection'
import { useIsMobile } from '@/lib/useMobile'
import { cn } from '@/lib/utils'

/** Summary screen: the month (`?month=YYYY-MM`) and the chosen accounts (`accounts=k1,k2`, also
 * remembered in the browser) live in the URL. */
export function SummaryPage() {
  const [params, setParams] = useSearchParams()
  const { selection, accounts, ready, select } = useAccountSelection()
  const months = useMonths(selection, ready)
  const month = months.data ? resolveMonth(months.data, params.get('month')) : null
  const summary = useSummary(month, selection)
  const home = months.data && month ? returnTarget(months.data, month) : null
  usePublishNavMonth(home ? month : null)

  // Changing the month keeps the URL's accounts (when it has them).
  function goTo(target: string | null) {
    const next = new URLSearchParams(target ? { month: target } : {})
    const chosen = params.get(ACCOUNTS_PARAM)
    if (chosen) next.set(ACCOUNTS_PARAM, chosen)
    setParams(next)
  }

  if (months.isError) {
    return <LoadError what={t('summary.page.months')} error={months.error} onRetry={() => months.refetch()} />
  }
  if (!ready || months.isPending) return <SummarySkeleton />
  if (month === null) return <EmptyState />

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
        picker={
          accounts.length > 1 && (
            <AccountPicker selection={selection} accounts={accounts} onChange={select} />
          )
        }
      >
        {summary.data && <CoverageChips coverage={summary.data.coverage} />}
      </MonthHeader>
      {summary.isError ? (
        <LoadError what={t('summary.page.summary')} error={summary.error} onRetry={() => summary.refetch()} />
      ) : summary.data ? (
        <MonthBody
          summary={summary.data}
          stale={summary.isPlaceholderData}
          newest={months.data[0]}
          onSelectMonth={goTo}
          selection={selection}
          accounts={accounts}
        />
      ) : (
        <BodySkeleton />
      )}
    </>
  )
}

interface MonthBodyProps {
  summary: Summary
  stale: boolean
  newest: MonthOption
  onSelectMonth: (month: string) => void
  selection: Selection
  accounts: readonly AccountRef[]
}

function MonthBody({
  summary,
  stale,
  newest,
  onSelectMonth,
  selection,
  accounts,
}: MonthBodyProps) {
  const { option } = summary
  const chosen = summary.trend.find((point) => point.month === option.month)
  const note = option.partial
    ? partialNote(option.label, summary.coverage)
    : newest.partial && newest.month > option.month
      ? t('summary.page.inProgress', { label: newest.label })
      : null
  // With nothing to review, "To review" stays on one line and Categories takes the full width.
  const review = useReview(option.month, selection)
  const nothingToReview = review.isSuccess && review.data.length === 0
  // Interest belongs to cards: with none chosen, the widget does not show.
  const cards = selection === null || includesCard(selection, accounts)
  const mobile = useIsMobile()
  if (mobile) {
    return (
      <div
        aria-busy={stale}
        className={cn('flex flex-col gap-5 transition-opacity', stale && 'opacity-60')}
      >
        <MobileSummary
          summary={summary}
          onSelectMonth={onSelectMonth}
          selection={selection}
          accounts={accounts}
          note={note}
        />
      </div>
    )
  }
  return (
    <div
      aria-busy={stale}
      className={cn('flex flex-col gap-6 transition-opacity', stale && 'opacity-60')}
    >
      <Kpis key={option.month} summary={summary} selection={selection} />
      <TrendBars trend={summary.trend} month={option.month} onSelect={onSelectMonth} />
      <MonthReading
        key={`reading-${option.month}`}
        month={option.month}
        point={chosen}
        whatHappened={summary.what_happened}
        changes={summary.changes}
        partial={option.partial}
        comparable={summary.habitual_cents !== null}
        selection={selection}
      />
      <div
        data-testid="summary-pair"
        className={cn(
          'grid items-stretch gap-6',
          !nothingToReview && 'xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]',
        )}
      >
        <CategoryTable
          key={`cat-${option.month}`}
          month={option.month}
          categories={summary.categories}
          selection={selection}
        />
        <ReviewCard key={`rev-${option.month}`} month={option.month} selection={selection} />
      </div>
      <div
        className={cn(
          'grid items-stretch gap-6 md:grid-cols-2',
          cards ? 'xl:grid-cols-4' : 'xl:grid-cols-3',
        )}
      >
        <RecurringCard month={option.month} selection={selection} />
        <PendingCard selection={selection} />
        {cards && <InterestCard month={option.month} selection={selection} />}
        <ByAccount key={`acc-${option.month}`} accounts={summary.by_account} rate={summary.rate} />
      </div>
      <BudgetCard month={option.month} selection={selection} />
      {note && <p className="text-[13px] text-muted-foreground">{note}</p>}
    </div>
  )
}

function EmptyState() {
  return (
    <div className={cn(PANEL, 'flex flex-col gap-2 px-6 py-10 text-center')}>
      <h1 className="text-xl font-bold tracking-tight">{t('summary.page.title')}</h1>
      <p className="text-sm text-muted-foreground">
        {tn('summary.page.empty', {
          command: (
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[13px] text-foreground">
              uv run michelito sync
            </code>
          ),
        })}
      </p>
    </div>
  )
}

function SummarySkeleton() {
  return (
    <div aria-busy="true" aria-label={t('summary.page.loading')} className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-11 w-72 rounded-[10px]" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <BodySkeleton />
    </div>
  )
}

function BodySkeleton() {
  return (
    <div aria-busy="true" className="flex flex-col gap-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-[130px] rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-[300px] rounded-2xl" />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Skeleton className="h-[420px] rounded-2xl" />
        <Skeleton className="h-[420px] rounded-2xl" />
      </div>
    </div>
  )
}
