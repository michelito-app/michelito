import { useRef } from 'react'
import { useSearchParams } from 'react-router'
import { AccountList } from '@/components/accounts/AccountList'
import { CashBoxCard } from '@/components/cashBox/CashBoxCard'
import { StatementsPanel } from '@/components/accounts/StatementsPanel'
import { LoadError } from '@/components/LoadError'
import { PANEL } from '@/components/summary/styles'
import { t } from '@/i18n'
import { Skeleton } from '@/components/ui/skeleton'
import { resolveAccount } from '@/lib/accounts'
import { CASH_KIND, localToday } from '@/lib/cashBox'
import { useAccounts } from '@/lib/queries'
import { cn } from '@/lib/utils'

/** Accounts screen: the chosen account lives in the URL (`?account=<key>`); by default, the
 * first credit card. */
export function AccountsPage() {
  const [params, setParams] = useSearchParams()
  const accounts = useAccounts()
  const panel = useRef<HTMLElement>(null)

  if (accounts.isError) {
    return (
      <LoadError what={t('accounts.loadWhat')} error={accounts.error} onRetry={() => accounts.refetch()} />
    )
  }
  if (accounts.isPending) return <PageSkeleton />

  // The cash box has no statements: it gets its own card, below.
  const withStatements = accounts.data.filter((a) => a.kind !== CASH_KIND)
  const selected = resolveAccount(withStatements, params.get('account'))
  if (selected === null) return <NoAccounts />

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
          selected={selected.key}
          today={today}
          onSelect={select}
        />
        <StatementsPanel ref={panel} account={selected} today={today} />
      </div>
      <CashBoxCard today={today} />
    </>
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
