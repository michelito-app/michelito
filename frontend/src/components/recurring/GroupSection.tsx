import { useId } from 'react'
import { PANEL, PANEL_TITLE } from '@/components/summary/styles'
import type { Recurring } from '@/lib/api'
import { type Section, totalLine } from '@/lib/recurring'
import { cn } from '@/lib/utils'
import { RecurringRow } from './RecurringRow'

interface GroupSectionProps {
  section: Section
  month: string | null
  firstMonth: string | null
  /** Toda la pantalla: de ahí salen los destinos de «Unir con…». */
  overview: Recurring
}

/** Un grupo (Suscripciones, Servicios…) con su total mensual y anual y sus cargos. */
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
          {total ? totalLine(total.monthly_cents, total.yearly_cents) : 'Sin cargos activos'}
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
