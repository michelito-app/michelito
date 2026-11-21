import { Ellipsis } from 'lucide-react'
import { useId, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { FOCUS } from '@/components/summary/styles'
import { t } from '@/i18n'
import { selectionFromParams, transactionsHref } from '@/lib/accountFilter'
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

// Narrow: initial | merchant (with the cost below) | actions. From @xl the cost gets its own
// column on the right.
const GRID =
  'grid grid-cols-[36px_minmax(0,1fr)_44px] gap-x-3 gap-y-1.5 @xl:grid-cols-[36px_minmax(0,1fr)_auto_44px] @xl:gap-x-4'

interface RecurringRowProps {
  item: RecurringItem
  /** Month ("YYYY-MM") that decides the "new" badge. */
  month: string | null
  /** Month of the first transaction: nothing is marked "new" there. */
  firstMonth: string | null
  /** The whole screen: the targets of "Join with…" come from it. */
  overview: Recurring
}

/** A recurring charge: merchant, when it charges, how much it costs and its marks. */
export function RecurringRow({ item, month, firstMonth, overview }: RecurringRowProps) {
  const actionsId = useId()
  const [open, setOpen] = useState(false)
  const active = item.status === 'active'
  const cost = costLines(item)
  const badges = badgesOf(item, month, firstMonth)
  const members = membersText(item)
  const extras = extrasText(item)
  const [params] = useSearchParams()
  // The name opens its last charge's month in Transactions, searching the merchant.
  const chargesHref = transactionsHref(
    { month: item.last_day.slice(0, 7), q: item.merchant },
    selectionFromParams(params),
  )
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
          <Link
            to={chargesHref}
            className={cn(
              'relative self-start rounded-sm text-sm font-semibold text-foreground underline-offset-2 [overflow-wrap:anywhere] hover:underline',
              'before:absolute before:-inset-y-3 before:inset-x-0 before:content-[""]',
              FOCUS,
              !active && 'text-muted-foreground',
            )}
          >
            {item.name}
          </Link>
          <span className="text-xs text-muted-foreground">
            {item.category} · {cadenceText(item)} · {sinceText(item)} · {lastChargeText(item)}
          </span>
          {members && (
            <span className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
              {t('recurring.row.includes', { members })}
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
          aria-label={t('recurring.row.markNamed', { name: item.name })}
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
