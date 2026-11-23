import { useId } from 'react'
import { PANEL } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { NetWorth } from '@/lib/api'
import { formatDop } from '@/lib/money'
import { groupName, type Side, shares } from '@/lib/netWorth'
import { cn } from '@/lib/utils'

/** Assets and debts, each split by kind with a bar per kind (Monarch's right column). */
export function NetWorthSummary({ worth, className }: { worth: NetWorth; className?: string }) {
  const titleId = useId()
  return (
    <aside
      aria-labelledby={titleId}
            className={cn(PANEL, 'flex flex-col gap-5 px-5 py-5', className)}
    >
      <h2 id={titleId} className="text-[15px] font-semibold">
        {t('accounts.summary.title')}
      </h2>
      <SideBlock worth={worth} side="asset" />
      <SideBlock worth={worth} side="debt" />
    </aside>
  )
}

/** Each further kind a little lighter, never fainter than a third. */
function fade(index: number): number {
  return Math.max(0.35, 1 - index * 0.2)
}

const BAR: Record<Side, string> = { asset: 'bg-primary', debt: 'bg-up' }

function SideBlock({ worth, side }: { worth: NetWorth; side: Side }) {
  const parts = shares(worth, side)
  const total = side === 'asset' ? worth.assets_cents : worth.debts_cents
  return (
    <section className="flex flex-col gap-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-semibold text-muted-foreground">
          {side === 'asset' ? t('accounts.summary.assets') : t('accounts.summary.debts')}
        </h3>
        <span className="text-[15px] font-bold tabular-nums">{formatDop(total)}</span>
      </div>
      {parts.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t('accounts.summary.empty')}</p>
      ) : (
        <>
          <div aria-hidden="true" className="flex h-2 w-full gap-0.5 overflow-hidden rounded-full bg-muted">
            {parts.map((p, i) => (
              <span
                key={p.group}
                className={cn('h-full', BAR[side])}
                style={{ width: `${p.share * 100}%`, opacity: fade(i) }}
              />
            ))}
          </div>
          <ul className="flex flex-col gap-1.5">
            {parts.map((p, i) => (
              <li key={p.group} className="flex items-center justify-between gap-2 text-[13px]">
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={cn('size-2 flex-none rounded-full', BAR[side])}
                    style={{ opacity: fade(i) }}
                  />
                  <span className="truncate">{groupName(p.group)}</span>
                </span>
                <span
                  className="whitespace-nowrap text-muted-foreground tabular-nums"
                  title={`${Math.round(p.share * 100)} %`}
                >
                  {formatDop(p.total_cents)}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
