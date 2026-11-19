import { Ellipsis } from 'lucide-react'
import { useId, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { FOCUS } from '@/components/summary/styles'
import type { Recurring, RecurringItem } from '@/lib/api'
import {
  type BadgeTone,
  badgeTone,
  badgesOf,
  cadenceText,
  costLines,
  extrasText,
  lastChargeText,
  membersText,
  sinceText,
} from '@/lib/recurring'
import { cn } from '@/lib/utils'
import { RecurringActions } from './RecurringActions'

const BADGE_TONE: Record<BadgeTone, string> = {
  up: 'bg-up-soft text-up-ink',
  neutral: 'bg-[#EEF0F2] text-ink-2',
  positive: 'bg-secondary text-secondary-foreground',
  muted: 'border-[#D6D6D0] bg-card text-muted-foreground',
}

// En angosto: inicial | comercio (y el costo debajo) | acciones. Desde @xl, el costo va en su
// propia columna a la derecha.
const GRID =
  'grid grid-cols-[36px_minmax(0,1fr)_44px] gap-x-3 gap-y-1.5 @xl:grid-cols-[36px_minmax(0,1fr)_auto_44px] @xl:gap-x-4'

interface RecurringRowProps {
  item: RecurringItem
  /** Mes ("YYYY-MM") con el que se decide la insignia "Nuevo". */
  month: string | null
  /** Mes del primer movimiento: ahí no se marca "Nuevo". */
  firstMonth: string | null
  /** Toda la pantalla: de ahí salen los destinos de «Unir con…». */
  overview: Recurring
}

/** Un cargo recurrente: comercio, cuándo cobra, cuánto cuesta y sus marcas. */
export function RecurringRow({ item, month, firstMonth, overview }: RecurringRowProps) {
  const actionsId = useId()
  const [open, setOpen] = useState(false)
  const active = item.status === 'activo'
  const cost = costLines(item)
  const badges = badgesOf(item, month, firstMonth)
  const members = membersText(item)
  const extras = extrasText(item)
  return (
    <li className="border-b border-[#F2F2EE] last:border-b-0">
      <div
        className={cn(
          GRID,
          'min-h-[68px] items-center px-4 py-3 sm:px-5',
          !active && 'bg-[#FAFAF8]',
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            'row-span-2 flex size-9 items-center justify-center self-start rounded-[10px] text-sm font-bold @xl:row-span-1 @xl:self-center',
            active ? 'bg-secondary text-secondary-foreground' : 'bg-muted text-muted-foreground',
          )}
        >
          {item.name.charAt(0).toUpperCase()}
        </span>
        <span className="flex min-w-0 flex-col gap-1">
          <span
            className={cn(
              'text-sm font-semibold [overflow-wrap:anywhere]',
              !active && 'text-muted-foreground',
            )}
          >
            {item.name}
          </span>
          <span className="text-xs text-muted-foreground">
            {item.category} · {cadenceText(item)} · {sinceText(item)} · {lastChargeText(item)}
          </span>
          {members && (
            <span className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
              Incluye: {members}
            </span>
          )}
          {extras && <span className="text-xs font-medium text-ink-2">{extras}</span>}
          {badges.length > 0 && (
            <span className="flex flex-wrap gap-1.5 pt-0.5">
              {badges.map((badge) => (
                <Badge key={badge} className={BADGE_TONE[badgeTone(badge)]}>
                  {badge}
                </Badge>
              ))}
            </span>
          )}
        </span>
        <span className="col-start-2 row-start-2 flex items-baseline gap-2 tabular-nums @xl:col-start-3 @xl:row-start-1 @xl:flex-col @xl:items-end @xl:gap-0.5">
          <span
            className={cn(
              'text-[15px] font-bold whitespace-nowrap',
              !active && 'text-muted-foreground',
            )}
          >
            {cost.main}
          </span>
          <span className="text-xs whitespace-nowrap text-muted-foreground">{cost.detail}</span>
        </span>
        <button
          type="button"
          aria-label={`Marcar ${item.name}`}
          aria-expanded={open}
          aria-controls={actionsId}
          onClick={() => setOpen((value) => !value)}
          className={cn(
            'col-start-3 row-span-2 row-start-1 flex size-11 cursor-pointer items-center justify-center self-start rounded-[10px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground @xl:col-start-4 @xl:row-span-1 @xl:self-center',
            open && 'bg-muted text-foreground',
            FOCUS,
          )}
        >
          <Ellipsis size={18} aria-hidden="true" />
        </button>
      </div>
      {open && <RecurringActions item={item} id={actionsId} overview={overview} />}
    </li>
  )
}
