import { t } from '@/i18n'
import type { Selection } from '@/lib/accountFilter'
import type { Summary } from '@/lib/api'
import { flowBar, reportsMonthHref } from '@/lib/home'
import { formatDop } from '@/lib/money'
import { incomeThroughNote, NO_FLOW_NOTE } from '@/lib/summary'
import { cn } from '@/lib/utils'
import { Card, FIGURE } from './Card'

const ROW = 'flex items-baseline justify-between gap-3 border-t border-[#F2F2EE] py-1.5 first:border-t-0'
const NBSP = (text: string) => text.replace(/RD\$ /g, 'RD$ ')

interface FlowCardProps {
  summary: Summary
  selection: Selection
}

/** «Flow»: what came in, went out and stayed, in one bar; it leads to the month in Reports.
 * Keeping less than nothing is a line with a terracotta dot, not a headline, and only once the
 * month's income is in: while a bank account ends earlier ("through 15 Jan") the figure stays
 * neutral. */
export function FlowCard({ summary, selection }: FlowCardProps) {
  const href = reportsMonthHref(summary.option.month, selection)
  const net = summary.net_cents
  if (net === null) {
    return (
      <Card id="flow" title={t('home.flow.title')} href={href}>
        <p className="text-[13px] text-muted-foreground">{NO_FLOW_NOTE}</p>
      </Card>
    )
  }
  const inCents = summary.income_cents
  const outCents = inCents - net
  const bar = flowBar(inCents, outCents)
  const through = incomeThroughNote(summary.income_through)
  // Overspent only says so when the income is complete.
  const overspent = net < 0 && through === null
  return (
    <Card
      id="flow"
      title={t('home.flow.title')}
      href={href}
      label={`${t('home.flow.title')}: ${t('home.flow.kept')} ${formatDop(net)}`}
    >
      <div
        aria-hidden="true"
        className="flex h-3 w-full overflow-hidden rounded-full bg-[#EDEDE8]"
        data-testid="flow-bar"
      >
        {bar.over ? (
          <>
            <span className="h-full bg-ink-2" style={{ width: `${bar.kept * 100}%` }} />
            <span
              className={cn('h-full', overspent ? 'bg-up' : 'bg-[#B8BDC4]')}
              style={{ width: `${(1 - bar.kept) * 100}%` }}
            />
          </>
        ) : (
          <>
            <span className="h-full bg-ink-2" style={{ width: `${bar.out * 100}%` }} />
            <span className="h-full bg-primary" style={{ width: `${bar.kept * 100}%` }} />
          </>
        )}
      </div>
      <dl className="flex flex-col">
        <div className={ROW}>
          <dt className="flex flex-col text-[13px] text-ink-2">
            {t('home.flow.in')}
            {through && (
              <span data-testid="flow-through" className="text-[12px] text-muted-foreground">
                {through}
              </span>
            )}
          </dt>
          <dd className={cn('text-[16px] text-primary', FIGURE)}>{NBSP(formatDop(inCents))}</dd>
        </div>
        <div className={ROW}>
          <dt className="text-[13px] text-ink-2">{t('home.flow.out')}</dt>
          <dd className={cn('text-[16px]', FIGURE)}>{NBSP(formatDop(outCents))}</dd>
        </div>
        <div className={ROW}>
          <dt className="text-[13px] text-ink-2">{t('home.flow.kept')}</dt>
          <dd
            data-testid="flow-kept"
            className={cn(
              'flex items-center gap-1.5 text-[16px]',
              FIGURE,
              net < 0 ? 'text-foreground' : 'text-primary',
            )}
          >
            {overspent && (
              <span
                data-testid="flow-overspent"
                aria-label={t('home.flow.overspent')}
                role="img"
                className="size-2 shrink-0 rounded-full bg-up"
              />
            )}
            {NBSP(formatDop(net))}
          </dd>
        </div>
      </dl>
    </Card>
  )
}
