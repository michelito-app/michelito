import { Link } from 'react-router'
import type { Selection } from '@/lib/accountFilter'
import {
  contributionDetail,
  contributionDiff,
  contributionHref,
  flagSentence,
  monthFlags,
} from '@/lib/anomalies'
import type { Contribution, MonthTotal } from '@/lib/api'
import { formatSignedDop } from '@/lib/money'
import { cn } from '@/lib/utils'
import { FOCUS, ROW_DIVIDER } from './styles'

interface WhatHappenedProps {
  /** El mes elegido, tal como viene en la tendencia (con sus marcas). */
  point: MonthTotal
  items: Contribution[]
  selection: Selection
}

/** «Qué pasó» (pestaña de «Lectura del mes»): en un mes atípico, los comercios que más explican
 * el desvío de cada lado, cada uno con enlace a su movimiento. */
export function WhatHappened({ point, items, selection }: WhatHappenedProps) {
  return (
    <div className="grid gap-x-8 gap-y-4 md:grid-cols-2">
      {monthFlags(point).map((flag) => {
        const side = items.filter((item) => item.side === flag.side)
        if (side.length === 0) return null
        return (
          <div key={flag.side} className="flex min-w-0 flex-col gap-1">
            <p className="text-[13px] text-ink-2">{flagSentence(point, flag)}</p>
            <ul className="flex flex-col">
              {side.map((item) => (
                <li key={item.merchant} className={cn(ROW_DIVIDER, 'py-1.5')}>
                  <Link
                    to={contributionHref(item, point.month, selection)}
                    aria-label={`Ver ${item.merchant}: ${contributionDiff(item)}`}
                    className={cn(
                      '-mx-2 flex min-w-0 flex-col gap-0.5 rounded-md px-2 py-1.5 text-foreground no-underline transition-colors hover:bg-muted/60',
                      FOCUS,
                    )}
                  >
                    <span className="flex min-w-0 items-baseline gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold" title={item.description || item.merchant}>
                        {item.merchant}
                      </span>
                      <span
                        className={cn(
                          'shrink-0 text-sm font-semibold whitespace-nowrap tabular-nums',
                          (item.side === 'gasto') === item.diff_cents > 0 ? 'text-up' : 'text-down',
                        )}
                      >
                        {formatSignedDop(item.diff_cents)}
                      </span>
                    </span>
                    <span className="text-[13px] text-muted-foreground">{contributionDetail(item)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}
