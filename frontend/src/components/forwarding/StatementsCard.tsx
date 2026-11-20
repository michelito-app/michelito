import { useId } from 'react'
import { Link } from 'react-router'
import { FOCUS, PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { t } from '@/i18n'
import {
  type Forwarding,
  arrivalLine,
  overdueLine,
  problemLine,
  shortDate,
} from '@/lib/forwarding'
import { cn } from '@/lib/utils'

/** The statements card (hosted, once forwarding is set up): the newest statement per account that
 * arrived by email, and what needs the person (passwords, quarantine, problems, late ones). */
export function StatementsCard({ data }: { data: Forwarding }) {
  const id = useId()
  const problems = data.problems.map(problemLine).filter((line): line is string => line !== null)
  const waiting = data.waiting.filter((item) => item.reason !== '').length
  const attention = [
    ...(waiting ? [t('forwarding.card.waiting', { count: waiting })] : []),
    ...(data.quarantine.length ? [t('forwarding.card.quarantine', { count: data.quarantine.length })] : []),
    ...data.overdue.map(overdueLine),
    ...[...new Set(problems)],
  ]
  return (
    <section aria-labelledby={id} data-statements-card className={cn(PANEL, 'flex flex-col gap-2 px-5 py-4')}>
      <div className="flex items-center justify-between gap-2">
        <h2 id={id} className={PANEL_TITLE}>
          {t('forwarding.card.title')}
        </h2>
        <Link
          to="/settings#automate"
          className={cn('inline-flex min-h-11 items-center rounded-lg px-3 text-[13px] font-semibold text-primary hover:bg-muted', FOCUS)}
        >
          {t('forwarding.card.manage')}
        </Link>
      </div>
      {data.arrivals.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('forwarding.card.none')}</p>
      ) : (
        <ul className="flex flex-col">
          {data.arrivals.map((arrival) => (
            <li
              key={`${arrival.bank}-${arrival.identifier}`}
              className="flex flex-wrap justify-between gap-x-3 border-b border-border py-1.5 text-sm last:border-b-0"
            >
              <span className="font-medium">{arrivalLine(arrival)}</span>
              <span className="text-[13px] text-muted-foreground">
                {t('forwarding.card.arrivedOn', { date: shortDate(arrival.at) })}
              </span>
            </li>
          ))}
        </ul>
      )}
      {attention.length > 0 && (
        <ul className="flex flex-col gap-1" aria-label={t('forwarding.card.attention')}>
          {attention.map((line) => (
            <li key={line} className="text-sm text-destructive">
              {line}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
