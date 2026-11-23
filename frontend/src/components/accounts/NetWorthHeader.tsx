import { useState } from 'react'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { NetWorth } from '@/lib/api'
import { formatDop, formatSignedDop } from '@/lib/money'
import {
  changeOf,
  isGood,
  PERIODS,
  type Period,
  periodName,
  periodPhrase,
  pointsFor,
} from '@/lib/netWorth'
import { cn } from '@/lib/utils'
import { BalanceChart } from './BalanceChart'

/** Net worth in large type, its change over the period and its chart with the period picker. */
export function NetWorthHeader({ worth }: { worth: NetWorth }) {
  const [period, setPeriod] = useState<Period>('3M')
  const points = pointsFor(worth.history, period)
  const change = changeOf(points)
  const hasOwed = worth.holdings.some((h) => h.group === 'owed' || h.group === 'owing')
  return (
    <section
      aria-labelledby="net-worth-title"
      data-testid="net-worth"
      className={cn(PANEL, 'flex flex-col gap-4 px-5 pt-5 pb-4 sm:px-6')}
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 id="net-worth-title" className="text-[13px] font-semibold text-muted-foreground">
            {t('accounts.netWorth.title')}
          </h2>
          <span
            data-testid="net-worth-total"
            className="text-[34px] leading-none font-bold tracking-[-0.02em] tabular-nums sm:text-[40px]"
          >
            {formatDop(worth.net_cents)}
          </span>
          {change !== null && (
            <span
              className={cn(
                'text-sm font-semibold tabular-nums',
                change === 0 ? 'text-muted-foreground' : isGood(change, 'asset') ? 'text-down' : 'text-up',
              )}
            >
              {t('accounts.netWorth.change', {
                amount: formatSignedDop(change),
                period: periodPhrase(period),
              })}
            </span>
          )}
        </div>
        <PeriodPicker period={period} onChange={setPeriod} />
      </div>
      {points.length >= 2 ? (
        <BalanceChart points={points.map((p) => ({ day: p.day, value: p.net_cents }))} format={formatDop} />
      ) : (
        <p className="text-[13px] text-muted-foreground">{t('accounts.netWorth.noHistory')}</p>
      )}
      {(worth.unconverted || hasOwed) && (
        <p className="text-xs text-muted-foreground">
          {[
            worth.unconverted ? t('accounts.netWorth.unconverted') : null,
            hasOwed ? t('accounts.netWorth.owedToday') : null,
          ]
            .filter(Boolean)
            .join(' ')}
        </p>
      )}
    </section>
  )
}

function PeriodPicker({ period, onChange }: { period: Period; onChange: (p: Period) => void }) {
  return (
    <div
      role="group"
      aria-label={t('accounts.netWorth.periods')}
      className="inline-flex rounded-full bg-muted p-1"
    >
      {PERIODS.map((p) => (
        <button
          key={p}
          type="button"
          aria-pressed={p === period}
          onClick={() => onChange(p)}
          className={cn(
            'min-h-9 min-w-11 cursor-pointer rounded-full px-3 text-[13px] font-semibold transition-colors',
            p === period
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground',
            FOCUS,
          )}
        >
          {periodName(p)}
        </button>
      ))}
    </div>
  )
}
