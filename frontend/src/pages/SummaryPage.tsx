import { type ReactNode, type TouchEvent, useRef } from 'react'
import { useSearchParams } from 'react-router'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { CoveragePill } from '@/components/cards/CoveragePill'
import { HomeCards } from '@/components/cards/HomeCards'
import { FabSpace, QuickCashButton } from '@/components/cashBox/QuickCash'
import { NoMonths } from '@/components/cards/NoMonths'
import { LoadError } from '@/components/LoadError'
import { MonthHeader } from '@/components/MonthHeader'
import { SummaryOnboarding } from '@/components/onboarding/SummaryOnboarding'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { ACCOUNTS_PARAM, scopeText } from '@/lib/accountFilter'
import {
  lastDay,
  monthName,
  neighbors,
  type Neighbors,
  resolveMonth,
  returnTarget,
} from '@/lib/months'
import { usePublishNavMonth } from '@/lib/navMonth'
import { useMonths, useSummary } from '@/lib/queries'
import { useScrollMemory } from '@/lib/scrollMemory'
import { useAccountSelection } from '@/lib/useAccountSelection'
import { cn } from '@/lib/utils'

/** A horizontal swipe longer than this (and mostly sideways) changes the month. */
const SWIPE_PX = 60

/** Summary screen: a stack of cards for the month (`?month=YYYY-MM`, by default the newest, in
 * progress) with the chosen accounts (`accounts=k1,k2`, also remembered in the browser). Each
 * card leads to the list that explains it; going back returns to the same scroll position. */
export function SummaryPage() {
  const [params, setParams] = useSearchParams()
  const { selection, accounts, ready, select } = useAccountSelection()
  const months = useMonths(selection, ready)
  const month = months.data ? resolveMonth(months.data, params.get('month')) : null
  const summary = useSummary(month, selection)
  const home = months.data && month ? returnTarget(months.data, month) : null
  usePublishNavMonth(home ? month : null)
  useScrollMemory()

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
  if (month === null) return <NoMonths />

  const option = months.data.find((o) => o.month === month) ?? months.data[0]
  const around = neighbors(months.data, month)
  return (
    <>
      <Swipe around={around} onNavigate={goTo}>
        <MonthHeader
          month={month}
          label={option.label}
          months={months.data}
          neighbors={around}
          onNavigate={goTo}
          home={home}
          onReturn={() => goTo(null)}
          scope={null}
          picker={
            accounts.length > 1 && (
              <AccountPicker selection={selection} accounts={accounts} onChange={select} />
            )
          }
        >
          {summary.data && (
            <CoveragePill
              coverage={summary.data.coverage}
              scope={t('months.headerScope', {
                last: lastDay(month),
                month: monthName(month),
                scope: scopeText(selection, accounts),
              })}
            />
          )}
        </MonthHeader>
      </Swipe>
      <SummaryOnboarding />
      <div className="flex justify-end">
        <QuickCashButton />
      </div>
      {summary.isError ? (
        <LoadError what={t('summary.page.summary')} error={summary.error} onRetry={() => summary.refetch()} />
      ) : summary.data ? (
        <div
          aria-busy={summary.isPlaceholderData}
          className={cn('transition-opacity', summary.isPlaceholderData && 'opacity-60')}
        >
          <HomeCards summary={summary.data} selection={selection} />
        </div>
      ) : (
        <BodySkeleton />
      )}
      <FabSpace />
    </>
  )
}

interface SwipeProps {
  around: Neighbors
  onNavigate: (month: string) => void
  children: ReactNode
}

/** Swiping the header sideways changes the month: to the left, the next one; to the right, the
 * previous one (like turning pages). */
function Swipe({ around, onNavigate, children }: SwipeProps) {
  const start = useRef<{ x: number; y: number } | null>(null)
  function onTouchStart(event: TouchEvent) {
    const touch = event.touches[0]
    start.current = touch ? { x: touch.clientX, y: touch.clientY } : null
  }
  function onTouchEnd(event: TouchEvent) {
    const from = start.current
    const touch = event.changedTouches[0]
    start.current = null
    if (!from || !touch) return
    const dx = touch.clientX - from.x
    const dy = touch.clientY - from.y
    if (Math.abs(dx) < SWIPE_PX || Math.abs(dx) < 2 * Math.abs(dy)) return
    const target = dx < 0 ? around.newer : around.older
    if (target) onNavigate(target)
  }
  return (
    <div data-testid="summary-header" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
      {children}
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
    <div aria-busy="true" className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <Skeleton className="h-[220px] rounded-[20px] md:col-span-2" />
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-[160px] rounded-[20px]" />
      ))}
    </div>
  )
}
