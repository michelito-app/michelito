import { Link } from 'react-router'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import type { Summary } from '@/lib/api'
import { curvePoints, monthSpendingHref, spendingLine, txHref } from '@/lib/home'
import { type Pace, usePace } from '@/lib/homeQueries'
import { formatDop } from '@/lib/money'
import { shortDay } from '@/lib/months'
import { provisionalNote } from '@/lib/summary'
import { cn } from '@/lib/utils'
import { Card, FIGURE } from './Card'
import { CardError } from './CardError'

const NBSP = (text: string) => text.replace(/RD\$ /g, 'RD$ ')

interface SpendingCardProps {
  summary: Summary
  selection: Selection
  className?: string
}

/** «Month spending»: the total (provisional ones included), the comparison with last month at
 * the same date and the cumulative curve. The card leads to the month's expenses; each one-off
 * dot, to its transaction. */
export function SpendingCard({ summary, selection, className }: SpendingCardProps) {
  const month = summary.option.month
  const pace = usePace(month, selection)
  const line = pace.data ? spendingLine(pace.data, summary.total_cents, summary.one_offs_cents) : null
  const provisional = provisionalNote(summary.provisional_cents)
  return (
    <Card
      id="spending"
      title={t('home.spending.title')}
      href={monthSpendingHref(month, selection)}
      label={`${t('home.spending.title')}: ${formatDop(summary.total_cents)}`}
      className={className}
    >
      <p data-testid="spending-total" className={cn(FIGURE, 'text-[34px] leading-none sm:text-[40px]')}>
        {NBSP(formatDop(summary.total_cents))}
      </p>
      {line && <p className="text-[13px] leading-snug text-ink-2">{NBSP(line)}</p>}
      {provisional && (
        <p data-testid="provisional-total" className="text-[12.5px] text-muted-foreground">
          {NBSP(provisional)}
        </p>
      )}
      {pace.isPending ? (
        <Skeleton className="h-[96px] rounded-xl" />
      ) : pace.isError ? (
        <CardError what={t('home.what.pace')} error={pace.error} onRetry={() => pace.refetch()} />
      ) : (
        <Curve pace={pace.data} selection={selection} />
      )}
    </Card>
  )
}

const HEIGHT = 96
const PAD = 8 // room for the dots at the top and bottom

/** The two cumulative curves (this month in brand green, last month dashed grey), no axes or
 * grid; today's value marked and the one-off expenses as dots that open their transaction. */
function Curve({ pace, selection }: { pace: Pace; selection: Selection }) {
  const points = curvePoints(pace.current_cents, pace.previous_cents, pace.days_in_month)
  const days = points.length
  const top = Math.max(1, ...pace.current_cents, ...pace.previous_cents)
  const x = (day: number) => (days <= 1 ? 0 : ((day - 1) / (days - 1)) * 100)
  const y = (cents: number) => PAD + (1 - cents / top) * (HEIGHT - 2 * PAD)
  const path = (values: readonly number[]) =>
    values.map((cents, index) => `${index === 0 ? 'M' : 'L'}${x(index + 1)},${y(cents)}`).join(' ')
  const today = pace.through_day
  const todayCents = pace.current_cents[today - 1] ?? 0
  const sameDay = pace.previous_same_day_cents
  const description = pace.finished
    ? t('home.spending.chartWhole', {
        current: formatDop(todayCents),
        previous: formatDop(sameDay),
      })
    : t('home.spending.chart', {
        current: formatDop(todayCents),
        day: today,
        previous: formatDop(sameDay),
      })
  return (
    <div className="flex flex-col gap-1.5">
      <div className="pointer-events-none relative" style={{ height: HEIGHT }}>
        <svg
          role="img"
          aria-label={description}
          viewBox={`0 0 100 ${HEIGHT}`}
          preserveAspectRatio="none"
          className="absolute inset-0 size-full overflow-visible"
        >
          {pace.previous_cents.length > 1 && (
            <path
              d={path(pace.previous_cents)}
              fill="none"
              stroke="#B8BDC4"
              strokeWidth={1.75}
              strokeDasharray="4 4"
              vectorEffect="non-scaling-stroke"
            />
          )}
          {pace.current_cents.length > 1 && (
            <path
              d={path(pace.current_cents)}
              fill="none"
              stroke="var(--primary)"
              strokeWidth={2.5}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>
        {today > 0 && (
          <span
            data-testid="curve-today"
            aria-hidden="true"
            className="absolute size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-card bg-primary"
            style={{ left: `${x(today)}%`, top: y(todayCents) }}
          />
        )}
        {pace.one_offs.map((item) => {
          const day = Number(item.day.slice(8, 10))
          return (
            <Link
              key={item.fingerprint}
              to={txHref(item, selection)}
              data-one-off=""
              aria-label={t('home.spending.oneOff', {
                merchant: item.merchant,
                amount: formatDop(item.amount_cents),
                day: shortDay(item.day),
              })}
              className="group pointer-events-auto absolute z-[2] flex size-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              style={{ left: `${x(day)}%`, top: y(pace.current_cents[day - 1] ?? 0) }}
            >
              <span className="size-3 rounded-full border-2 border-ink-2 bg-card group-hover:bg-ink-2" />
            </Link>
          )
        })}
      </div>
      <p aria-hidden="true" className="flex gap-4 text-[11.5px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded bg-primary" />
          {t('home.spending.thisMonth')}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="w-4 border-t-2 border-dashed border-[#B8BDC4]" />
          {t('home.spending.lastMonth')}
        </span>
      </p>
    </div>
  )
}
