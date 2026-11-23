import { useLocation, useSearchParams } from 'react-router'
import { AccountDetail } from '@/components/accounts/AccountDetail'
import { AccountGroups } from '@/components/accounts/AccountGroups'
import { DetailPage } from '@/components/accounts/DetailPage'
import { NetWorthHeader } from '@/components/accounts/NetWorthHeader'
import { NetWorthSummary } from '@/components/accounts/NetWorthSummary'
import { CashBoxCard } from '@/components/cashBox/CashBoxCard'
import { LoanCard } from '@/components/loans/LoanCard'
import { LoadError } from '@/components/LoadError'
import { PANEL } from '@/components/summary/styles'
import { t } from '@/i18n'
import { Skeleton } from '@/components/ui/skeleton'
import type { Loan } from '@/lib/api'
import { CASH_BOX_ID, CASH_BOX_KEY, CASH_KIND, localToday } from '@/lib/cashBox'
import { useLoans } from '@/lib/loanQueries'
import { loanIdOf } from '@/lib/loans'
import { useAccounts, useCashBox, useNetWorth } from '@/lib/queries'
import { cn } from '@/lib/utils'

/** Accounts screen. Without `?account=` it is the overview: net worth with its chart, every
 * account in grouped rows and, on a wide screen, the summary on the right. With
 * `?account=<key>` (a statement account, `loan-<id>` or the cash box) it is that account's page. */
export function AccountsPage() {
  const [params] = useSearchParams()
  const accounts = useAccounts()
  const cash = useCashBox()
  const loans = useLoans()
  const worth = useNetWorth()
  const location = useLocation()

  if (accounts.isError) {
    return (
      <LoadError what={t('accounts.loadWhat')} error={accounts.error} onRetry={() => accounts.refetch()} />
    )
  }
  if (accounts.isPending) return <PageSkeleton />

  const today = localToday()
  const requested = params.get('account')
  const withStatements = accounts.data.filter((a) => a.kind !== CASH_KIND)
  const cashChosen =
    requested === CASH_BOX_KEY || (requested === null && location.hash === `#${CASH_BOX_ID}`)
  const loanId = loanIdOf(requested)
  const chosen = withStatements.find((a) => a.key === requested)

  if (loanId !== null) {
    const loan = loans.data?.find((l) => l.id === loanId)
    return (
      <DetailPage>
        <LoanPanel loan={loan} pending={loans.isPending} today={today} />
      </DetailPage>
    )
  }
  if (cashChosen) {
    return (
      <DetailPage>
        <CashBoxCard today={today} titled />
      </DetailPage>
    )
  }
  if (chosen !== undefined) return <AccountDetail account={chosen} today={today} />
  if (
    withStatements.length === 0 &&
    !cash.isPending &&
    !loans.isPending &&
    cash.data == null &&
    (loans.data ?? []).length === 0
  ) {
    return <NoAccounts />
  }

  return (
    <>
      <Header />
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-5">
          {worth.isError ? (
            <LoadError what={t('accounts.netWorth.loadWhat')} error={worth.error} onRetry={() => worth.refetch()} />
          ) : worth.data === undefined ? (
            <Skeleton className="h-64 rounded-2xl" />
          ) : (
            <>
              <NetWorthHeader worth={worth.data} />
              <NetWorthSummary worth={worth.data} className="lg:hidden" />
            </>
          )}
          <AccountGroups
            accounts={withStatements}
            loans={loans.data ?? []}
            cash={cash.data ?? null}
            worth={worth.data}
            today={today}
          />
        </div>
        {worth.data !== undefined && (
          <NetWorthSummary worth={worth.data} className="sticky top-6 hidden lg:flex" />
        )}
      </div>
    </>
  )
}

function LoanPanel({ loan, pending, today }: { loan: Loan | undefined; pending: boolean; today: string }) {
  if (loan !== undefined) return <LoanCard loan={loan} today={today} />
  if (pending) return <Skeleton className="h-96 rounded-2xl" />
  return (
    <div className={cn(PANEL, 'px-6 py-10 text-center')}>
      <h1 className="text-base font-semibold">{t('loans.card.unknown')}</h1>
    </div>
  )
}

function Header() {
  return (
    <header className="flex flex-col gap-1.5">
      <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">{t('accounts.title')}</h1>
      <p className="text-sm text-muted-foreground">{t('accounts.subtitle')}</p>
    </header>
  )
}

function NoAccounts() {
  return (
    <div className={cn(PANEL, 'flex flex-col gap-2 px-6 py-10 text-center')}>
      <h1 className="text-xl font-bold tracking-tight">{t('accounts.title')}</h1>
      <p className="text-sm text-muted-foreground">
        {t('accounts.none.before')}{' '}
        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[13px] text-foreground">
          uv run michelito sync
        </code>
        .
      </p>
    </div>
  )
}

function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label={t('accounts.loading')} className="flex flex-col gap-5">
      <Skeleton className="h-9 w-48 rounded-[10px]" />
      <Skeleton className="h-64 rounded-2xl" />
      {[0, 1].map((i) => (
        <Skeleton key={i} className="h-40 rounded-2xl" />
      ))}
    </div>
  )
}
