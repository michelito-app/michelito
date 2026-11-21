import { ChevronLeft, ChevronRight, Undo2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { t } from '@/i18n'
import { cn } from '@/lib/utils'
import type { MonthOption } from '@/lib/api'
import { lastDay, monthName, type Neighbors } from '@/lib/months'
import { FOCUS } from '@/components/summary/styles'
import { MonthPicker } from './MonthPicker'

interface MonthHeaderProps {
  month: string
  label: string
  /** Months with data (newest to oldest), for the grid. */
  months: readonly MonthOption[]
  neighbors: Neighbors
  onNavigate: (month: string) => void
  /** Default month one can go back to; null when already on it. */
  home: MonthOption | null
  onReturn: () => void
  /** Account picker, next to the month. */
  picker?: ReactNode
  /** Which accounts the transactions belong to ("all your accounts", "VISA ···4242"…); null
   * leaves the scope line out (the Summary says it in its coverage sheet). */
  scope?: string | null
  /** Screen name, only for screen readers, before the month in the title. */
  title?: string
  children?: ReactNode
}

interface ArrowProps {
  target: string | null
  label: string
  onNavigate: (month: string) => void
  children: ReactNode
}

function Arrow({ target, label, onNavigate, children }: ArrowProps) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={target === null}
      onClick={() => target && onNavigate(target)}
      className={cn(
        'flex size-11 shrink-0 items-center justify-center rounded-[10px] border border-border bg-card text-ink-2 transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-card',
        FOCUS,
      )}
    >
      {children}
    </button>
  )
}

/** Month title (opens the month grid) with arrows (disabled at the ends) and whatever goes on
 * the right. Shared by Summary and Transactions. */
export function MonthHeader({
  month,
  label,
  months,
  neighbors,
  onNavigate,
  home,
  onReturn,
  picker,
  scope = t('common.allYourAccounts'),
  title,
  children,
}: MonthHeaderProps) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <Arrow target={neighbors.older} label={t('months.previous')} onNavigate={onNavigate}>
            <ChevronLeft size={16} strokeWidth={2.2} aria-hidden="true" />
          </Arrow>
          <MonthPicker
            month={month}
            label={label}
            options={months}
            onNavigate={onNavigate}
            title={title}
          />
          <Arrow target={neighbors.newer} label={t('months.next')} onNavigate={onNavigate}>
            <ChevronRight size={16} strokeWidth={2.2} aria-hidden="true" />
          </Arrow>
          {home && (
            <button
              type="button"
              onClick={onReturn}
              className={cn(
                'flex h-11 items-center gap-2 rounded-[10px] border border-border bg-card px-3 text-sm font-medium text-primary transition-colors hover:bg-muted',
                FOCUS,
              )}
            >
              <Undo2 size={16} strokeWidth={2.2} aria-hidden="true" />
              {t('months.backTo', { month: home.label })}
            </button>
          )}
          {picker}
        </div>
        {scope !== null && (
          <p className="text-sm text-muted-foreground">
            {t('months.headerScope', { last: lastDay(month), month: monthName(month), scope })}
          </p>
        )}
      </div>
      {children}
    </header>
  )
}
