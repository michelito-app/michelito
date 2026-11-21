import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import { useBudget } from '@/lib/budgetQueries'
import { budgetHref, capShare, closestToCap } from '@/lib/home'
import { formatDop } from '@/lib/money'
import { cn } from '@/lib/utils'
import { Card } from './Card'
import { CardError } from './CardError'

const NBSP = (text: string) => text.replace(/RD\$ /g, 'RD$ ')

interface BudgetCardProps {
  month: string
  selection: Selection
}

/** «Budget»: the three categories closest to their cap, with progress bars; terracotta only
 * past the cap. The card leads to Budget. */
export function BudgetCard({ month, selection }: BudgetCardProps) {
  const budget = useBudget(month, selection)
  const lines = budget.data ? closestToCap(budget.data.lines) : []
  return (
    <Card id="budget" title={t('home.budget.title')} href={budgetHref(month, selection)}>
      {budget.isPending ? (
        <Skeleton className="h-[96px] rounded-xl" />
      ) : budget.isError ? (
        <CardError what={t('home.what.budget')} error={budget.error} onRetry={() => budget.refetch()} />
      ) : lines.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('home.budget.noCaps')}</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {lines.map((line) => {
            const over = line.spent_cents > (line.cap_cents ?? 0)
            return (
              <li key={line.category_id} className="flex flex-col gap-1.5">
                <span className="flex items-baseline justify-between gap-3 text-[13.5px]">
                  <span className="min-w-0 truncate font-medium">{line.category}</span>
                  <span
                    className={cn(
                      'shrink-0 whitespace-nowrap tabular-nums',
                      over ? 'font-semibold text-up' : 'text-ink-2',
                    )}
                  >
                    {over
                      ? NBSP(t('home.budget.over', { amount: formatDop(line.over_cents) }))
                      : NBSP(
                          t('home.budget.line', {
                            spent: formatDop(line.spent_cents),
                            cap: formatDop(line.cap_cents ?? 0),
                          }),
                        )}
                  </span>
                </span>
                <span aria-hidden="true" className="h-2 overflow-hidden rounded-full bg-[#EDEDE8]">
                  <span
                    className={cn('block h-full rounded-full', over ? 'bg-up' : 'bg-primary')}
                    style={{ width: `${capShare(line)}%` }}
                  />
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
