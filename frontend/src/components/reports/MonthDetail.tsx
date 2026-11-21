import { LoadError } from '@/components/LoadError'
import { MonthHeader } from '@/components/MonthHeader'
import { ByAccount } from '@/components/summary/ByAccount'
import { CategoryTable } from '@/components/summary/CategoryTable'
import { InterestCard } from '@/components/summary/InterestCard'
import { Kpis } from '@/components/summary/Kpis'
import { MonthReading } from '@/components/summary/MonthReading'
import { TrendBars } from '@/components/summary/TrendBars'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { type AccountRef, includesCard, scopeText, type Selection } from '@/lib/accountFilter'
import type { Coverage, MonthOption } from '@/lib/api'
import { neighbors, returnTarget } from '@/lib/months'
import { useSummary } from '@/lib/queries'
import { partialNote } from '@/lib/summary'
import { cn } from '@/lib/utils'

interface MonthDetailProps {
  month: string
  months: MonthOption[]
  onMonth: (month: string | null) => void
  selection: Selection
  accounts: readonly AccountRef[]
}

/** The month in detail, in Reports (where the Summary's «Flow» card leads): the figures, the
 * last months, the month's reading, the categories table and the spending by account. */
export function MonthDetail({ month, months, onMonth, selection, accounts }: MonthDetailProps) {
  const summary = useSummary(month, selection)
  const option = months.find((o) => o.month === month) ?? months[0]
  return (
    <section aria-labelledby="month-detail" className="flex min-w-0 flex-col gap-6">
      <h2 id="month-detail" className="sr-only">
        {t('reports.month.title')}
      </h2>
      <MonthHeader
        month={month}
        label={option.label}
        months={months}
        neighbors={neighbors(months, month)}
        onNavigate={onMonth}
        home={returnTarget(months, month)}
        onReturn={() => onMonth(null)}
        scope={scopeText(selection, accounts)}
        title={t('reports.month.title')}
      />
      {summary.isError ? (
        <LoadError what={t('summary.page.summary')} error={summary.error} onRetry={() => summary.refetch()} />
      ) : summary.data ? (
        <div
          aria-busy={summary.isPlaceholderData}
          className={cn(
            'flex min-w-0 flex-col gap-6 transition-opacity',
            summary.isPlaceholderData && 'opacity-60',
          )}
        >
          <Kpis key={month} summary={summary.data} selection={selection} />
          <TrendBars trend={summary.data.trend} month={month} onSelect={onMonth} />
          <MonthReading
            key={`reading-${month}`}
            month={month}
            point={summary.data.trend.find((point) => point.month === month)}
            whatHappened={summary.data.what_happened}
            changes={summary.data.changes}
            partial={summary.data.option.partial}
            comparable={summary.data.habitual_cents !== null}
            selection={selection}
          />
          <CategoryTable
            key={`cat-${month}`}
            month={month}
            categories={summary.data.categories}
            selection={selection}
          />
          <div className="grid items-stretch gap-6 md:grid-cols-2">
            <ByAccount key={`acc-${month}`} accounts={summary.data.by_account} rate={summary.data.rate} />
            {(selection === null || includesCard(selection, accounts)) && (
              <InterestCard month={month} selection={selection} />
            )}
          </div>
          <MonthNote option={summary.data.option} newest={months[0]} coverage={summary.data.coverage} />
        </div>
      ) : (
        <Skeleton className="h-[420px] rounded-2xl" />
      )}
    </section>
  )
}

interface MonthNoteProps {
  option: MonthOption
  newest: MonthOption
  coverage: Coverage[]
}

/** The month's note: incomplete (with how far each account reaches) or another in progress. */
function MonthNote({ option, newest, coverage }: MonthNoteProps) {
  const note = option.partial
    ? partialNote(option.label, coverage)
    : newest.partial && newest.month > option.month
      ? t('summary.page.inProgress', { label: newest.label })
      : null
  return note ? <p className="text-[13px] text-muted-foreground">{note}</p> : null
}
