import { useId } from 'react'
import { PANEL, PANEL_TITLE } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { Recurring } from '@/lib/api'
import { type Section, totalLine } from '@/lib/recurring'
import { cn } from '@/lib/utils'
import { RecurringRow } from './RecurringRow'

interface GroupSectionProps {
  section: Section
  month: string | null
  firstMonth: string | null
  /** The whole screen: the targets of "Join with…" come from it. */
  overview: Recurring
}

/** A group (subscriptions, utilities…) with its monthly and yearly total and its charges. */
export function GroupSection({ section, month, firstMonth, overview }: GroupSectionProps) {
  const titleId = useId()
  const { group, total, items } = section
  return (
    <section aria-labelledby={titleId} className={cn(PANEL, '@container overflow-hidden')}>
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-[#EFEFEA] px-4 py-4 sm:px-5">
        <h2 id={titleId} className={PANEL_TITLE}>
          {group}
          <span className="ml-2 text-[13px] font-medium text-muted-foreground">{items.length}</span>
        </h2>
        <p className="text-[13px] font-medium text-ink-2 tabular-nums">
          {total
            ? totalLine(total.monthly_cents, total.yearly_cents)
            : t('recurring.section.noActive')}
        </p>
      </header>
      <ul>
        {items.map((item) => (
          <RecurringRow
            key={`${item.merchant}|${item.currency}`}
            item={item}
            month={month}
            firstMonth={firstMonth}
            overview={overview}
          />
        ))}
      </ul>
    </section>
  )
}
