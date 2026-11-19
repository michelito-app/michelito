import { ChevronDown } from 'lucide-react'
import { useEffect, useId, useRef } from 'react'
import { Link } from 'react-router'
import { FOCUS, ROW_DIVIDER } from '@/components/summary/styles'
import { BottomSheet } from '@/components/ui/bottom-sheet'
import { t } from '@/i18n'
import type { Investment, InvestmentStatus } from '@/lib/api'
import {
  entryRole,
  excessWarning,
  investmentMeta,
  investmentStats,
  STATUS_LABELS,
  unconvertedWarning,
} from '@/lib/investments'
import { formatMoney, linkPagePath } from '@/lib/links'
import { shortDay } from '@/lib/months'
import { useIsMobile } from '@/lib/useMobile'
import { cn } from '@/lib/utils'

const STATUS_CLASS: Record<InvestmentStatus, string> = {
  active: 'text-foreground',
  closed: 'text-down',
  written_off: 'text-muted-foreground',
}

const MANAGE =
  'inline-flex min-h-11 items-center rounded-xl border border-[#D6D6D0] bg-card px-4 text-sm font-semibold text-ink-2 no-underline hover:bg-muted'
const LIST_TITLE = 'text-xs font-semibold tracking-[0.04em] text-muted-foreground uppercase'

interface InvestmentRowProps {
  investment: Investment
  expanded: boolean
  onToggle: () => void
  /** The URL "Back" returns to from the investment's screen (with this one expanded). */
  from: string
  /** When coming back with this one expanded: it is shown and its row gets focus only once. */
  reveal: boolean
  onRevealed: () => void
}

/** One investment: tapping it expands it with its contributions, returns and capital returned;
 * "Manage…" opens its screen. The list is read-only. */
export function InvestmentRow({
  investment,
  expanded,
  onToggle,
  from,
  reveal,
  onRevealed,
}: InvestmentRowProps) {
  const ids = useId()
  const row = useRef<HTMLLIElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const stats = investmentStats(investment)
  // On a phone the detail opens in a bottom sheet instead of under the row.
  const mobile = useIsMobile()

  useEffect(() => {
    if (!reveal) return
    button.current?.focus({ preventScroll: true })
    row.current?.scrollIntoView({ block: 'center' })
    onRevealed()
    // On a phone, coming back shows the row (focused) without opening its sheet again.
    if (mobile && expanded) onToggle()
  }, [reveal, onRevealed, mobile, expanded, onToggle])

  return (
    <li ref={row} className={ROW_DIVIDER}>
      <button
        ref={button}
        type="button"
        aria-expanded={expanded}
        aria-controls={expanded ? `${ids}-detail` : undefined}
        onClick={onToggle}
        className={cn(
          '-mx-2 flex w-[calc(100%+1rem)] min-w-0 items-center gap-3 rounded-md px-2 py-3 text-left transition-colors hover:bg-muted/60',
          FOCUS,
        )}
      >
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3">
            <span className="min-w-0 truncate text-sm font-semibold">{investment.title}</span>
            <span
              data-testid="investment-status"
              className={cn(
                'ml-auto text-sm font-semibold whitespace-nowrap',
                STATUS_CLASS[investment.status],
              )}
            >
              {STATUS_LABELS[investment.status]}
            </span>
          </span>
          <span className="text-[13px] break-words text-muted-foreground">
            {investmentMeta(investment)}
          </span>
          <dl
            data-testid="investment-stats"
            className="grid grid-cols-[repeat(auto-fit,minmax(112px,1fr))] gap-x-3 gap-y-1"
          >
            {stats.map((stat) => (
              <div key={stat.key} className="flex min-w-0 flex-col">
                <dt className="text-[11.5px] text-muted-foreground">{stat.label}</dt>
                <dd className="text-[13px] font-semibold break-words tabular-nums">
                  {stat.value}
                </dd>
              </div>
            ))}
          </dl>
        </span>
        <ChevronDown
          size={16}
          aria-hidden="true"
          className={cn(
            'shrink-0 text-muted-foreground transition-transform',
            expanded && 'rotate-180',
          )}
        />
      </button>
      {expanded && !mobile && (
        <div id={`${ids}-detail`} className="flex flex-col gap-3 pt-1 pb-4">
          <Details investment={investment} />
          <Manage investment={investment} from={from} />
        </div>
      )}
      {expanded && mobile && !reveal && (
        <BottomSheet title={investment.title} onClose={onToggle}>
          <div id={`${ids}-detail`} className="flex flex-col gap-3">
            <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
              {stats.map((stat) => (
                <div key={stat.key} className="flex min-w-0 flex-col">
                  <dt className="text-[11.5px] text-muted-foreground">{stat.label}</dt>
                  <dd className="text-[15px] font-semibold break-words tabular-nums">
                    {stat.value}
                  </dd>
                </div>
              ))}
            </dl>
            <Details investment={investment} />
            <Manage investment={investment} from={from} />
          </div>
        </BottomSheet>
      )}
    </li>
  )
}

function Manage({ investment, from }: { investment: Investment; from: string }) {
  return (
    <div>
      <Link
        to={linkPagePath(investment.first_fingerprint)}
        state={{ from }}
        aria-label={t('investments.row.manageLabel', { title: investment.title })}
        className={cn(MANAGE, FOCUS)}
      >
        {t('investments.row.manage')}
      </Link>
    </div>
  )
}

function Details({ investment }: { investment: Investment }) {
  const warning = unconvertedWarning(investment)
  const excess = excessWarning(investment)
  const contributions = investment.entries.filter((e) => e.role === 'contribution')
  const credits = investment.entries.filter((e) => e.role !== 'contribution')
  return (
    <>
      {[excess, warning].map(
        (text) =>
          text && (
            <p key={text} className="rounded-lg bg-up-soft px-3 py-2 text-[13px] text-up-ink">
              {text}
            </p>
          ),
      )}
      <section
        aria-label={t('investments.row.contributionsLabel', { title: investment.title })}
        className="flex flex-col gap-1.5"
      >
        <h3 className={LIST_TITLE}>{t('investments.row.contributions')}</h3>
        <EntryList entries={contributions} />
      </section>
      <section
        aria-label={t('investments.row.creditsLabel', { title: investment.title })}
        className="flex flex-col gap-1.5"
      >
        <h3 className={LIST_TITLE}>{t('investments.row.credits')}</h3>
        {credits.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">{t('investments.row.noCredits')}</p>
        ) : (
          <EntryList entries={credits} />
        )}
      </section>
    </>
  )
}

function EntryList({ entries }: { entries: Investment['entries'] }) {
  return (
    <ul className="flex flex-col gap-2">
      {entries.map((e) => (
        <li key={e.fingerprint} className="flex flex-col text-[13px]">
          <span className="flex flex-wrap items-baseline justify-between gap-x-3">
            <span className="min-w-0 font-semibold break-words">
              {e.merchant}{' '}
              <span className="font-normal text-muted-foreground">({shortDay(e.day)})</span>
            </span>
            <span className="ml-auto font-semibold whitespace-nowrap tabular-nums">
              {formatMoney(e.amount_cents, e.currency)}
            </span>
          </span>
          <span className="break-words text-muted-foreground">
            {entryRole(e)} · {e.account_label}
            {!e.counted && t('investments.row.notCounted')}
          </span>
        </li>
      ))}
    </ul>
  )
}
