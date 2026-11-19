import { ChevronDown } from 'lucide-react'
import { useId, useState } from 'react'
import { FOCUS, PANEL } from '@/components/summary/styles'
import type { RecurringItem } from '@/lib/api'
import { useMarkRecurring } from '@/lib/queries'
import { cadenceText, costLines, lastChargeText, statusBody } from '@/lib/recurring'
import { cn } from '@/lib/utils'

interface DismissedSectionProps {
  items: RecurringItem[]
}

/** Los que el usuario marcó "No es recurrente", plegados; cada uno se puede deshacer. */
export function DismissedSection({ items }: DismissedSectionProps) {
  const listId = useId()
  const [open, setOpen] = useState(false)
  return (
    <section aria-label="Descartados" className={cn(PANEL, 'overflow-hidden')}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          'flex min-h-14 w-full cursor-pointer items-center justify-between gap-3 px-4 text-left transition-colors hover:bg-[#FAFAF8] sm:px-5',
          FOCUS,
          'focus-visible:ring-inset',
        )}
      >
        <span className="flex flex-col">
          <span className="text-[15px] font-semibold">Descartados ({items.length})</span>
          <span className="text-xs text-muted-foreground">
            Marcados como “No es recurrente”; no cuentan en los totales
          </span>
        </span>
        <ChevronDown
          size={18}
          aria-hidden="true"
          className={cn('shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && (
        <ul id={listId} className="border-t border-[#EFEFEA]">
          {items.map((item) => (
            <DismissedRow key={`${item.merchant}|${item.currency}`} item={item} />
          ))}
        </ul>
      )}
    </section>
  )
}

function DismissedRow({ item }: { item: RecurringItem }) {
  const mark = useMarkRecurring()
  return (
    <li className="flex flex-col gap-2 border-b border-[#F2F2EE] px-4 py-3 last:border-b-0 sm:px-5">
      <div className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="text-sm font-semibold text-ink-2 [overflow-wrap:anywhere]">
            {item.name}
          </span>
          <span className="text-xs text-muted-foreground">
            {costLines(item).main} · {cadenceText(item)} · {lastChargeText(item)}
          </span>
        </span>
        <button
          type="button"
          aria-label={`Deshacer: ${item.name}`}
          disabled={mark.isPending}
          onClick={() => mark.mutate(statusBody(item, null))}
          className={cn(
            'inline-flex min-h-11 shrink-0 cursor-pointer items-center rounded-xl border border-[#D6D6D0] bg-card px-3.5 text-sm font-semibold text-ink-2 transition-colors hover:bg-muted disabled:cursor-default disabled:opacity-60',
            FOCUS,
          )}
        >
          {mark.isPending ? 'Guardando…' : 'Deshacer'}
        </button>
      </div>
      {mark.isError && (
        <p
          role="alert"
          className="rounded-[10px] border border-up/30 bg-up-soft px-3 py-2.5 text-[13px] text-up-ink"
        >
          No se pudo deshacer: {mark.error.message}
        </p>
      )}
    </li>
  )
}
