import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import { amountText } from '@/lib/accounts'
import type { Interest } from '@/lib/api'
import { interestYear, nextDueText, yearTotalText } from '@/lib/interest'
import { formatUsd } from '@/lib/money'
import { useInterest } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { FOCUS, PANEL_TITLE, ROW_DIVIDER, WIDGET } from './styles'

/** "Cards" widget: the next payment so no interest accrues and the interest paid in the chosen
 * month's year. */
export function InterestCard({
  month,
  selection = null,
}: {
  month: string
  selection?: Selection
}) {
  const year = interestYear(month)
  const interest = useInterest(year, selection)
  if (interest.isPending) return <Skeleton className="h-full min-h-[164px] rounded-2xl" />

  return (
    <section aria-labelledby="int-title" className={WIDGET}>
      <h2 id="int-title" className={PANEL_TITLE}>
        {t('summary.interestCard.title')}
      </h2>
      {interest.isError ? (
        <p role="alert" className="text-[13px] text-muted-foreground">
          {t('summary.interestCard.loadError', { message: interest.error.message })}
        </p>
      ) : (
        <CardBody data={interest.data} year={year} />
      )}
    </section>
  )
}

function CardBody({ data, year }: { data: Interest; year: number }) {
  const next = data.next_due
  return (
    <>
      {next !== null ? (
        <Link
          to={`/accounts?${new URLSearchParams({ account: next.key })}`}
          className={cn(
            '-mx-2 flex min-h-11 items-center justify-between gap-3 rounded-lg bg-secondary/60 px-2 py-1.5 text-primary no-underline hover:bg-secondary',
            FOCUS,
          )}
        >
          <span className="flex min-w-0 flex-col">
            <span className="text-sm font-semibold">{nextDueText(next)}</span>
            <span className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
              {next.label}
            </span>
          </span>
          <ArrowRight size={14} aria-hidden="true" className="flex-none" />
        </Link>
      ) : (
        <p className="text-[13px] text-muted-foreground">{t('summary.interestCard.noUpcoming')}</p>
      )}
      <div className="flex flex-col gap-1">
        <h3 className="text-[12px] font-semibold tracking-[0.04em] text-muted-foreground uppercase">
          {t('summary.interestCard.yearTitle', { year })}
        </h3>
        {data.lines.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">{t('summary.interestCard.noInterest')}</p>
        ) : (
          <>
            <p className="text-[22px] leading-tight font-bold whitespace-nowrap tabular-nums">
              {yearTotalText(data)}
            </p>
            <ul className="flex flex-col">
              {data.lines.map((line) => (
                <li
                  key={`${line.key}|${line.currency}`}
                  className={cn(ROW_DIVIDER, 'flex items-baseline justify-between gap-3 py-1.5')}
                >
                  <span className="min-w-0 text-sm [overflow-wrap:anywhere]">{line.label}</span>
                  <span className="flex-none text-sm font-semibold whitespace-nowrap tabular-nums">
                    {amountText(line.total_cents, line.currency)}
                  </span>
                </li>
              ))}
            </ul>
            {data.unconverted_usd_cents > 0 && (
              <p className="text-[13px] text-up">
                {t('summary.interestCard.unconverted', { amount: formatUsd(data.unconverted_usd_cents) })}
              </p>
            )}
          </>
        )}
      </div>
    </>
  )
}
