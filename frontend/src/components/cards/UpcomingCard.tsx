import { t } from '@/i18n'
import type { RecurringAlert } from '@/lib/api'
import { dueText, type UpcomingItem } from '@/lib/home'
import { alertTone } from '@/lib/recurring'
import { cn } from '@/lib/utils'
import { Card } from './Card'
import { CardError } from './CardError'

interface UpcomingCardProps {
  items: readonly UpcomingItem[]
  /** Recurring warnings (a price rise, a new charge, a charge after cancelling). */
  alerts: readonly RecurringAlert[]
  today: string
  href: string
  /** The recurring charges did not load. */
  failure?: { error: Error; retry: () => void }
}

/** «Upcoming»: what is due in the next 7 days, from every source (today, the recurring
 * charges), and the first recurring warning with how many there are; the card leads to
 * Recurring. */
export function UpcomingCard({ items, alerts, today, href, failure }: UpcomingCardProps) {
  return (
    <Card id="upcoming" title={t('home.upcoming.title')} href={href}>
      {failure ? (
        <CardError what={t('home.what.recurring')} error={failure.error} onRetry={failure.retry} />
      ) : (
        <>
          {alerts.length > 0 && <AlertLine alerts={alerts} />}
          {items.length === 0 ? (
            <p className="text-[13px] text-muted-foreground">{t('home.upcoming.none')}</p>
          ) : (
            <ul className="flex flex-col">
              {items.slice(0, 4).map((item, index) => (
                <li
                  key={item.key}
                  className={cn(
                    'flex items-baseline justify-between gap-3 py-1.5 text-[13.5px]',
                    index > 0 && 'border-t border-[#F2F2EE]',
                  )}
                >
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate font-medium">{item.name}</span>
                    <span className="text-[12px] text-muted-foreground">
                      {dueText(today, item.day)}
                    </span>
                  </span>
                  <span className="shrink-0 font-semibold whitespace-nowrap tabular-nums">
                    {item.amount}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  )
}

function AlertLine({ alerts }: { alerts: readonly RecurringAlert[] }) {
  const first = alerts[0]
  const up = alertTone(first.kind) === 'up'
  return (
    <div data-testid="upcoming-alerts" className="flex flex-col gap-0.5 rounded-xl bg-[#F6F6F3] px-3 py-2">
      <span className={cn('text-[12px] font-semibold', up ? 'text-up' : 'text-ink-2')}>
        {t('home.upcoming.alerts', { count: alerts.length })}
      </span>
      <span className="text-[13px] leading-snug text-ink-2">
        <span className="font-medium text-foreground">{first.name}</span> · {first.detail}
      </span>
    </div>
  )
}
