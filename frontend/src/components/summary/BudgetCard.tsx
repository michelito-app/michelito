import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { hrefWithSelection, type Selection } from '@/lib/accountFilter'
import { BUDGET_PATH, missingText, overviewText } from '@/lib/budget'
import { useBudgetOverview } from '@/lib/budgetQueries'
import { formatDop } from '@/lib/money'
import { monthPhrase } from '@/lib/months'
import { cn } from '@/lib/utils'
import { PANEL, PANEL_TITLE, ROW_DIVIDER, WIDGET_ACTION } from './styles'

interface BudgetCardProps {
  month: string
  selection: Selection
}

/** Compact Summary card: how many categories went over their cap in the month (with the excess)
 * and the upcoming large expenses: the reserves due in the next 60 days. */
export function BudgetCard({ month, selection }: BudgetCardProps) {
  const overview = useBudgetOverview(month, selection)
  const href = hrefWithSelection(BUDGET_PATH, { month }, selection)
  if (overview.isPending) return <Skeleton className="h-[120px] rounded-2xl" />
  return (
    <section
      aria-labelledby="budget-card-title"
      className={cn(PANEL, 'grid gap-4 px-5 py-4 md:grid-cols-2')}
    >
      <div className="flex min-w-0 flex-col gap-2">
        <div className="-my-2 flex items-center justify-between gap-3">
          <h2 id="budget-card-title" className={PANEL_TITLE}>
            {t('summary.budgetCard.title')}
          </h2>
          <Link to={href} className={WIDGET_ACTION}>
            {t('summary.budgetCard.link')}
            <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </div>
        {overview.isError ? (
          <p role="alert" className="text-[13px] text-muted-foreground">
            {t('summary.budgetCard.loadError', { message: overview.error.message })}
          </p>
        ) : !overview.data.active ? (
          <p className="text-[13px] text-muted-foreground">
            {t('summary.budgetCard.inactive')}
          </p>
        ) : (
          <p
            data-testid="budget-status"
            className={cn(
              'text-sm font-semibold',
              (overview.data.over_count ?? 0) > 0 ? 'text-up' : 'text-ink-2',
            )}
          >
            {overviewText(overview.data).replace(/RD\$ /g, 'RD$\u00a0')}
          </p>
        )}
        {overview.data && missingText(overview.data.missing) && (
          <p className="text-[13px] text-up-ink">{missingText(overview.data.missing)}</p>
        )}
      </div>
      <div
        className="flex min-w-0 flex-col gap-2"
        role="group"
        aria-label={t('summary.budgetCard.upcomingLabel')}
      >
        <h3 className="text-[13px] font-semibold text-ink-2">{t('summary.budgetCard.upcomingTitle')}</h3>
        {overview.data && overview.data.upcoming.length > 0 ? (
          <ul className="flex flex-col">
            {overview.data.upcoming.map((item) => (
              <li
                key={item.id}
                className={cn(ROW_DIVIDER, 'flex items-baseline justify-between gap-3 py-1.5 text-sm')}
              >
                <span className="min-w-0 truncate">
                  {item.name}{' '}
                  <span className="text-muted-foreground">· {monthPhrase(item.due_month)}</span>
                </span>
                <span className="shrink-0 font-semibold tabular-nums">
                  {formatDop(item.amount_cents)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-muted-foreground">{t('summary.budgetCard.noUpcoming')}</p>
        )}
      </div>
    </section>
  )
}
