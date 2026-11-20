import { Link } from 'react-router'
import { HostedEmpty } from '@/components/onboarding/HostedEmpty'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { t } from '@/i18n'
import { formatDop } from '@/lib/money'
import { useMonths, useReview } from '@/lib/queries'
import { cn } from '@/lib/utils'

const SHOWN = 3

/** Hosted Investments without investments: "is this an investment?" on up to three transfers
 * that look like they went to a brokerage or a certificate (the same deterministic hints as "To
 * review"), else the designed empty state. */
export function InvestmentHints() {
  const months = useMonths()
  const month = months.data?.[0]?.month ?? null
  if (months.isPending) return null
  if (month === null) return <HostedEmpty view="investments" />
  return <MonthHints month={month} />
}

function MonthHints({ month }: { month: string }) {
  const review = useReview(month)
  if (review.isPending) return null
  const hints = (review.data ?? [])
    .filter((item) => item.kind === 'possible_contribution')
    .slice(0, SHOWN)
  if (!hints.length) return <HostedEmpty view="investments" />
  return (
    <section data-suggestion="" className={cn(PANEL, 'flex max-w-[640px] flex-col gap-2 px-5 py-4')}>
      <h2 className="text-[17px] font-[650] tracking-tight">
        {t('onboarding.empty.investments.suggest')}
      </h2>
      <p className="text-sm text-ink-2">{t('onboarding.empty.investments.suggestText')}</p>
      <ul>
        {hints.map((item) => (
          <li
            key={item.fingerprint}
            className="flex items-center justify-between gap-3 border-b border-border py-2 last:border-b-0"
          >
            <span className="min-w-0 truncate text-sm">
              {item.merchant || item.description}
              {item.amount_dop_cents !== null && ` · ${formatDop(item.amount_dop_cents)}`}
            </span>
            <Link
              to={`/transactions/${encodeURIComponent(item.fingerprint)}`}
              className={cn(
                'inline-flex min-h-11 shrink-0 items-center rounded-lg px-3 text-[13px] font-semibold text-primary no-underline hover:bg-muted',
                FOCUS,
              )}
            >
              {t('onboarding.empty.investments.open')}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
