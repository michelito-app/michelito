import { ArrowRight, Check, Landmark, Receipt } from 'lucide-react'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { byMonth, displayName, effectText, entryLine, paymentLine } from '@/lib/ledger'
import { monthTitle, shortDay } from '@/lib/months'
import type { Entry, Payment, TimelineItem } from '@/lib/sharedApi'
import { cn } from '@/lib/utils'

interface GroupTimelineProps {
  items: readonly TimelineItem[]
  onOpen: (item: TimelineItem) => void
  onLink: (payment: Payment) => void
}

/** The group's timeline by month (sticky headers), most recent first: expenses with their effect
 * on the user and payments, set apart with an arrow and their bank state. */
export function GroupTimeline({ items, onOpen, onLink }: GroupTimelineProps) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('shared.group.empty')}</p>
  }
  return (
    <section aria-label={t('shared.group.timeline')} className="flex flex-col">
      {byMonth(items).map((block) => (
        <div key={block.month} role="group" aria-label={monthTitle(block.month)}>
          <h3 className="sticky top-0 z-10 -mx-4 border-b border-[#EFEFEA] bg-[#FAFAF8] px-4 py-1.5 text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase sm:mx-0 sm:rounded-lg">
            {monthTitle(block.month)}
          </h3>
          <ul className="flex flex-col">
            {block.items.map((item) => (
              <li key={`${item.kind}-${item.id}`} className="border-b border-border last:border-b-0">
                {item.kind === 'entry' ? (
                  <EntryRow entry={item} onOpen={() => onOpen(item)} />
                ) : (
                  <PaymentRow payment={item} onOpen={() => onOpen(item)} onLink={() => onLink(item)} />
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}

const ROW = cn(
  'flex min-h-14 min-w-0 flex-1 items-center gap-3 rounded-lg py-2 text-left hover:bg-muted/60',
  FOCUS,
)

function EntryRow({ entry, onOpen }: { entry: Entry; onOpen: () => void }) {
  const effect = effectText(entry.effect, entry.currency)
  return (
    <button type="button" onClick={onOpen} className={cn(ROW, 'w-full')} data-testid="timeline-entry">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Receipt size={16} aria-hidden="true" />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-sm font-semibold break-words">{entryLine(entry)}</span>
        <span className="text-[13px] text-muted-foreground">{shortDay(entry.day)}</span>
      </span>
      <span
        className={cn(
          'shrink-0 text-right text-[13px] font-semibold',
          entry.effect.kind === 'owe' ? 'text-up' : entry.effect.kind === 'lent' ? 'text-down' : 'text-muted-foreground',
        )}
      >
        {effect}
      </span>
    </button>
  )
}

function PaymentRow({ payment, onOpen, onLink }: { payment: Payment; onOpen: () => void; onLink: () => void }) {
  const line = paymentLine(payment)
  return (
    <div className="flex items-center gap-2" data-testid="timeline-payment">
      <button type="button" onClick={onOpen} className={ROW}>
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-secondary text-secondary-foreground">
          <ArrowRight size={16} aria-hidden="true" />
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="text-sm font-semibold break-words">{line}</span>
          <span className="flex flex-wrap items-center gap-x-1.5 text-[13px] text-muted-foreground">
            {shortDay(payment.day)}
            {payment.transaction ? (
              <span className="inline-flex items-center gap-1 text-down">
                · <Landmark size={13} aria-hidden="true" />
                <Check size={13} aria-hidden="true" />
                {t('shared.payment.inBank')}
              </span>
            ) : (
              <span>· {t('shared.payment.unlinked')}</span>
            )}
          </span>
        </span>
      </button>
      {!payment.transaction && (
        <button
          type="button"
          aria-label={t('shared.payment.linkLabel', {
            from:
              payment.from_contact === null
                ? t('shared.payment.unknown')
                : displayName(payment.from_name, payment.from_me),
            to: displayName(payment.to_name, payment.to_me),
          })}
          onClick={onLink}
          className={cn(
            'inline-flex min-h-11 shrink-0 items-center rounded-xl px-3 text-[13px] font-semibold text-primary hover:bg-muted',
            FOCUS,
          )}
        >
          {t('shared.payment.link')}
        </button>
      )}
    </div>
  )
}
