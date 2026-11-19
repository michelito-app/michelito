import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'
import { Skeleton } from '@/components/ui/skeleton'
import { t } from '@/i18n'
import { hrefWithSelection, type Selection } from '@/lib/accountFilter'
import type { AlertKind, Recurring } from '@/lib/api'
import { formatDop } from '@/lib/money'
import { localToday, shortDay } from '@/lib/months'
import { useRecurring } from '@/lib/queries'
import { alertTone, chargeText, upcomingCharges } from '@/lib/recurring'
import { cn } from '@/lib/utils'
import { PANEL_TITLE, ROW_DIVIDER, WIDGET, WIDGET_ACTION } from './styles'

const MAX_LINES = 3
const ALERT_ICON: Record<AlertKind, string> = { price_up: '↑', new: '+', charged_after_cancel: '!' }

function moreText(count: number): string {
  return t('summary.recurringCard.more', { count })
}

/** Recurring widget: the monthly total and what changed in the chosen month or, when nothing
 * changed, the upcoming charges. */
export function RecurringCard({
  month,
  selection = null,
}: {
  month: string
  selection?: Selection
}) {
  const recurring = useRecurring(month, selection)
  if (recurring.isPending) return <Skeleton className="h-full min-h-[164px] rounded-2xl" />

  return (
    <section aria-labelledby="rec-title" className={WIDGET}>
      <div className="-my-2 flex items-center justify-between gap-3">
        <h2 id="rec-title" className={PANEL_TITLE}>
          {t('summary.recurringCard.title')}
        </h2>
        <Link to={hrefWithSelection('/recurring', {}, selection)} className={WIDGET_ACTION}>
          {t('summary.recurringCard.seeAll')}
          <ArrowRight size={14} aria-hidden="true" />
        </Link>
      </div>
      {recurring.isError ? (
        <p role="alert" className="text-[13px] text-muted-foreground">
          {t('summary.recurringCard.loadError', { message: recurring.error.message })}
        </p>
      ) : (
        <CardBody data={recurring.data} />
      )}
    </section>
  )
}

function CardBody({ data }: { data: Recurring }) {
  if (data.items.length === 0) {
    return <p className="text-[13px] text-muted-foreground">{t('summary.recurringCard.empty')}</p>
  }
  return (
    <>
      <p className="flex items-baseline gap-1.5">
        <span className="text-[22px] leading-tight font-bold whitespace-nowrap tabular-nums">
          {formatDop(data.monthly_cents)}
        </span>
        <span className="text-[13px] text-muted-foreground">{t('summary.recurringCard.perMonth')}</span>
      </p>
      {data.alerts.length > 0 ? <Alerts data={data} /> : <Upcoming data={data} />}
    </>
  )
}

function Alerts({ data }: { data: Recurring }) {
  return (
    <>
      <ul className="flex flex-col gap-2.5">
        {data.alerts.slice(0, MAX_LINES).map((alert) => (
          <li
            key={`${alert.kind}|${alert.merchant}|${alert.currency}`}
            className="flex items-start gap-2.5"
          >
            <span
              aria-hidden="true"
              className={cn(
                'mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md text-[13px] font-bold',
                alertTone(alert.kind) === 'up'
                  ? 'bg-up-soft text-up'
                  : 'bg-secondary text-secondary-foreground',
              )}
            >
              {ALERT_ICON[alert.kind]}
            </span>
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-semibold" title={alert.name}>
                {alert.name}
              </span>
              <span className="text-[13px] text-muted-foreground">{alert.detail}</span>
            </span>
          </li>
        ))}
      </ul>
      {data.alerts.length > MAX_LINES && (
        <p className="text-[13px] text-muted-foreground">
          {moreText(data.alerts.length - MAX_LINES)}
        </p>
      )}
    </>
  )
}

function Upcoming({ data }: { data: Recurring }) {
  const next = upcomingCharges(data.items, localToday(), MAX_LINES)
  if (next.length === 0) return <p className="text-[13px] text-muted-foreground">{t('summary.recurringCard.noChanges')}</p>
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-[12px] font-semibold tracking-[0.04em] text-muted-foreground uppercase">
        {t('summary.recurringCard.upcoming')}
      </h3>
      <ul className="flex flex-col">
        {next.map(({ item, day }) => (
          <li
            key={`${item.merchant}|${item.currency}`}
            className={cn(ROW_DIVIDER, 'flex items-baseline justify-between gap-3 py-1.5')}
          >
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-medium" title={item.name}>
                {item.name}
              </span>
              <span className="text-xs text-muted-foreground">{shortDay(day)}</span>
            </span>
            <span className="shrink-0 text-sm font-semibold whitespace-nowrap tabular-nums">
              {chargeText(item)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
