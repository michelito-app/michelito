import { useRef } from 'react'
import { useLocation, useSearchParams } from 'react-router'
import { AccountList } from '@/components/accounts/AccountList'
import { CashBoxCard } from '@/components/cashBox/CashBoxCard'
import { LoanCard } from '@/components/loans/LoanCard'
import { StatementsPanel } from '@/components/accounts/StatementsPanel'
import { LoadError } from '@/components/LoadError'
import { PANEL } from '@/components/summary/styles'
import { t } from '@/i18n'
import { Skeleton } from '@/components/ui/skeleton'
import { resolveAccount } from '@/lib/accounts'
import type { Loan } from '@/lib/api'
import { CASH_BOX_ID, CASH_BOX_KEY, CASH_KIND, localToday } from '@/lib/cashBox'
import { useLoans } from '@/lib/loanQueries'
import { loanIdOf } from '@/lib/loans'
import { useAccounts, useCashBox } from '@/lib/queries'
import { cn } from '@/lib/utils'

/** Accounts screen: the chosen account lives in the URL (`?account=<key>`); by default, the
 * first credit card. */
export function AccountsPage() {
  const [params, setParams] = useSearchParams()
  const accounts = useAccounts()
  const cash = useCashBox()
  const loans = useLoans()
  const location = useLocation()
  const panel = useRef<HTMLElement>(null)

  if (accounts.isError) {
    return (
      <LoadError what={t('accounts.loadWhat')} error={accounts.error} onRetry={() => accounts.refetch()} />
    )
  }
  if (accounts.isPending) return <PageSkeleton />

  // The cash account has no statements: picking it shows its own card in the panel's place
  // (also when a link arrives with #cash-box).
  const withStatements = accounts.data.filter((a) => a.kind !== CASH_KIND)
  const cashChosen =
    params.get('account') === CASH_BOX_KEY ||
    (params.get('account') === null && location.hash === `#${CASH_BOX_ID}`)
  const loanId = loanIdOf(params.get('account'))
  const loan = loanId === null ? undefined : loans.data?.find((l) => l.id === loanId)
  const selected = resolveAccount(withStatements, params.get('account'))
  if (selected === null && !cashChosen && loanId === null) return <NoAccounts />

  function select(key: string) {
    setParams({ account: key })
    // On a phone the panel sits below the list: scroll it into view.
    const top = panel.current?.getBoundingClientRect().top ?? 0
    if (top > window.innerHeight * 0.6) {
      const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      panel.current?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
    }
  }

  const today = localToday()
  return (
    <>
      <Header />
      <div className="flex flex-wrap items-start gap-6">
        <AccountList
          accounts={withStatements}
          selected={
            loanId !== null
              ? (params.get('account') ?? '')
              : cashChosen || selected === null
                ? CASH_BOX_KEY
                : selected.key
          }
          today={today}
          onSelect={select}
          cash={cash.data ?? null}
          loans={loans.data ?? []}
        />
        {loanId !== null ? (
          <LoanPanel loan={loan} pending={loans.isPending} />
        ) : cashChosen || selected === null ? (
          <div className="flex min-w-0 flex-[3_1_560px] flex-col">
            <CashBoxCard today={today} />
          </div>
        ) : (
          <StatementsPanel ref={panel} account={selected} today={today} />
        )}
      </div>
    </>
  )
}

function LoanPanel({ loan, pending }: { loan: Loan | undefined; pending: boolean }) {
  if (loan !== undefined) return <LoanCard loan={loan} />
  if (pending) return <Skeleton className="h-96 min-w-0 flex-[3_1_560px] rounded-2xl" />
  return (
    <div className={cn(PANEL, 'min-w-0 flex-[3_1_560px] px-6 py-10 text-center text-sm')}>
      {t('loans.card.unknown')}
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
    <div aria-busy="true" aria-label={t('accounts.loading')} className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-9 w-48 rounded-[10px]" />
        <Skeleton className="h-4 w-80 max-w-full" />
      </div>
      <div className="flex flex-wrap items-start gap-6">
        <div className="flex min-w-0 flex-[2_1_320px] flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-[104px] rounded-2xl" />
          ))}
        </div>
        <Skeleton className="h-96 min-w-0 flex-[3_1_560px] rounded-2xl" />
      </div>
    </div>
  )
}
