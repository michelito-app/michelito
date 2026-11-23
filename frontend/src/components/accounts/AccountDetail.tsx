import { Link } from 'react-router'
import { PANEL } from '@/components/summary/styles'
import { t } from '@/i18n'
import type { Account, Tx } from '@/lib/api'
import { amountText, isCreditCard, signedBalance, statusText } from '@/lib/accounts'
import { formatMoney } from '@/lib/links'
import { monthPhrase } from '@/lib/months'
import { useTransactions } from '@/lib/queries'
import { dayLabel, type ListFilters } from '@/lib/transactions'
import { cn } from '@/lib/utils'
import { BalanceChart } from './BalanceChart'
import { DetailPage } from './DetailPage'
import { StatementsPanel } from './StatementsPanel'

const RECENT = 8

/** A statement account's page: its balance and how it moved by statement, the month's
 * transactions, then the statements (with what to pay, for a card). */
export function AccountDetail({ account, today }: { account: Account; today: string }) {
  const [first, ...rest] = account.latest
  const status = statusText(account)
  return (
    <DetailPage>
      <section className={cn(PANEL, 'flex flex-col gap-4 px-5 py-5 sm:px-6')}>
        <header className="flex flex-col gap-1">
          <h1 className="text-[22px] font-bold tracking-tight break-words sm:text-[26px]">
            {account.label}
          </h1>
          <span className={cn('text-[13px]', status.missing ? 'text-up' : 'text-muted-foreground')}>
            {status.text}
          </span>
        </header>
        <div className="flex flex-col gap-0.5">
          <span className="text-[13px] font-semibold text-muted-foreground">
            {t('accounts.detail.balance')}
          </span>
          <span className="text-[32px] leading-none font-bold tabular-nums">
            {first ? amountText(signedBalance(account, first.balance_cents), first.currency) : '—'}
          </span>
          {rest.map((line) => (
            <span key={line.currency} className="text-sm text-muted-foreground tabular-nums">
              {amountText(signedBalance(account, line.balance_cents), line.currency)}
            </span>
          ))}
        </div>
        <StatementChart account={account} />
      </section>
      <Recent account={account} month={today.slice(0, 7)} />
      <StatementsPanel account={account} today={today} titled={false} />
    </DetailPage>
  )
}

/** The balance at each statement's close, in the account's main currency. */
function StatementChart({ account }: { account: Account }) {
  const currency = account.latest[0]?.currency
  const points = account.statements
    .filter((s) => s.currency === currency && s.balance_cents !== null && !s.printout)
    .map((s) => ({ day: s.period_end, value: signedBalance(account, s.balance_cents) ?? 0 }))
    .sort((a, b) => a.day.localeCompare(b.day))
  if (currency === undefined || points.length < 2) return null
  return (
    <BalanceChart
      points={points}
      format={(cents) => amountText(cents, currency)}
      tone={isCreditCard(account) ? 'var(--color-up)' : undefined}
    />
  )
}

function filtersOf(account: Account): ListFilters {
  return { accounts: [account.key], category: null, q: '', kind: null, shared: null, provisional: false }
}

/** The account's transactions this month, by day (the newest first). */
function Recent({ account, month }: { account: Account; month: string }) {
  const list = useTransactions(month, filtersOf(account))
  const items = (list.data?.items ?? []).slice(0, RECENT)
  const days = groupByDay(items)
  return (
    <section aria-labelledby="recent-title" className={cn(PANEL, 'flex flex-col gap-3 px-5 py-5 sm:px-6')}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="recent-title" className="text-[17px] font-[650] tracking-tight">
          {t('accounts.detail.recent', { month: monthPhrase(month) })}
        </h2>
        <Link
          to={`/transactions?${new URLSearchParams({ account: account.key })}`}
          className="text-[13px] font-semibold whitespace-nowrap text-primary no-underline hover:underline"
        >
          {t('accounts.panel.viewTransactions')}
        </Link>
      </div>
      {list.isSuccess && items.length === 0 && (
        <p className="text-[13px] text-muted-foreground">{t('accounts.detail.noRecent')}</p>
      )}
      {days.map(([day, rows]) => (
        <div key={day} className="flex flex-col">
          <h3 className="text-xs font-semibold text-muted-foreground">{dayLabel(day)}</h3>
          <ul className="flex flex-col">
            {rows.map((tx) => (
              <li key={tx.fingerprint} className="border-b border-[#F2F2EE] last:border-b-0">
                <Link
                  to={`/transactions/${encodeURIComponent(tx.fingerprint)}`}
                  className="flex min-h-12 items-center justify-between gap-3 py-2 text-foreground no-underline hover:bg-muted/50"
                >
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate text-sm font-medium">{tx.merchant || tx.description}</span>
                    <span className="truncate text-xs text-muted-foreground">{tx.category}</span>
                  </span>
                  <span className="text-sm font-semibold whitespace-nowrap tabular-nums">
                    {formatMoney(tx.amount_cents, tx.currency)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}

function groupByDay(items: readonly Tx[]): [string, Tx[]][] {
  const days = new Map<string, Tx[]>()
  for (const tx of items) days.set(tx.day, [...(days.get(tx.day) ?? []), tx])
  return [...days.entries()]
}
