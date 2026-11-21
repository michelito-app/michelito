import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router'
import { t } from '@/i18n'
import type { Pending } from '@/lib/api'
import { formatDop, formatUsd } from '@/lib/money'
import type { Total } from '@/lib/sharedApi'
import { cn } from '@/lib/utils'
import { Card, FIGURE, ROW_LINK } from './Card'
import { CardError } from './CardError'

const NBSP = (text: string) => text.replace(/(RD|US)\$ /g, '$1$ ')

function amount(currency: string, cents: number): string {
  return currency === 'USD' ? formatUsd(cents) : formatDop(cents)
}

interface SharedCardProps {
  /** Shared's balances per currency (`/api/shared`). */
  totals: readonly Total[]
  href: string
  /** Who owes you and whom you owe across shared expenses and exchanges, with the chosen
   * accounts (`/api/pending`): the Pending screen's figures. */
  pending: Pending | undefined
  pendingHref: string
  failure?: { error: Error; retry: () => void }
}

/** «Shared»: what you are owed and what you owe, per currency (the card leads to Shared), and a
 * line with the Pending screen's figures (exchanges included) that leads there. */
export function SharedCard({ totals, href, pending, pendingHref, failure }: SharedCardProps) {
  const open = totals.filter((total) => total.owed_to_me_cents !== 0 || total.i_owe_cents !== 0)
  return (
    <Card id="shared" title={t('home.shared.title')} href={href}>
      {failure ? (
        <CardError what={t('home.what.shared')} error={failure.error} onRetry={failure.retry} />
      ) : open.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('home.shared.settled')} ✓</p>
      ) : (
        <dl className="grid grid-cols-2 gap-3">
          <Side
            label={t('home.shared.owedToMe')}
            testId="shared-owed"
            values={open.map((total) => amount(total.currency, total.owed_to_me_cents))}
            className="text-primary"
          />
          <Side
            label={t('home.shared.iOwe')}
            testId="shared-owe"
            values={open.map((total) => amount(total.currency, total.i_owe_cents))}
          />
        </dl>
      )}
      {pending && (pending.owed_to_me_dop_cents > 0 || pending.i_owe_dop_cents > 0) && (
        <Link to={pendingHref} data-testid="shared-pending" className={cn(ROW_LINK, 'text-[13px]')}>
          <span className="min-w-0 flex-1 text-ink-2">
            {NBSP(
              t('home.shared.pending', {
                owed: formatDop(pending.owed_to_me_dop_cents),
                owe: formatDop(pending.i_owe_dop_cents),
              }),
            )}
          </span>
          <ChevronRight size={14} aria-hidden="true" className="shrink-0 text-muted-foreground" />
        </Link>
      )}
    </Card>
  )
}

interface SideProps {
  label: string
  testId: string
  values: string[]
  className?: string
}

function Side({ label, testId, values, className }: SideProps) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-[12px] text-muted-foreground">{label}</dt>
      {values.map((value, index) => (
        <dd
          key={index}
          data-testid={testId}
          className={cn('truncate text-[18px]', FIGURE, className)}
        >
          {NBSP(value)}
        </dd>
      ))}
    </div>
  )
}
