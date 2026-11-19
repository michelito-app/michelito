import { useRef } from 'react'
import { useSearchParams } from 'react-router'
import { AccountList } from '@/components/accounts/AccountList'
import { CashBoxCard } from '@/components/cashBox/CashBoxCard'
import { StatementsPanel } from '@/components/accounts/StatementsPanel'
import { LoadError } from '@/components/LoadError'
import { PANEL } from '@/components/summary/styles'
import { Skeleton } from '@/components/ui/skeleton'
import { resolveAccount } from '@/lib/accounts'
import { CASH_KIND, localToday } from '@/lib/cashBox'
import { useAccounts } from '@/lib/queries'
import { cn } from '@/lib/utils'

/** Pantalla Cuentas: la cuenta elegida vive en la URL (`?cuenta=<key>`); por defecto, la
 * primera tarjeta de crédito. */
export function AccountsPage() {
  const [params, setParams] = useSearchParams()
  const accounts = useAccounts()
  const panel = useRef<HTMLElement>(null)

  if (accounts.isError) {
    return (
      <LoadError what="las cuentas" error={accounts.error} onRetry={() => accounts.refetch()} />
    )
  }
  if (accounts.isPending) return <PageSkeleton />

  // La caja fuerte no tiene estados: va en su propia tarjeta, debajo.
  const withStatements = accounts.data.filter((a) => a.kind !== CASH_KIND)
  const selected = resolveAccount(withStatements, params.get('cuenta'))
  if (selected === null) return <NoAccounts />

  function select(key: string) {
    setParams({ cuenta: key })
    // En el teléfono el panel queda debajo de la lista: se lleva a la vista.
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
      <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">Cuentas</h1>
      <p className="text-sm text-muted-foreground">Saldos según el último estado de cada cuenta</p>
    </header>
  )
}

function NoAccounts() {
  return (
    <div className={cn(PANEL, 'flex flex-col gap-2 px-6 py-10 text-center')}>
      <h1 className="text-xl font-bold tracking-tight">Cuentas</h1>
      <p className="text-sm text-muted-foreground">
        Todavía no hay estados. Corre{' '}
        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[13px] text-foreground">
          uv run finanzas sync
        </code>
        .
      </p>
    </div>
  )
}

function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Cargando las cuentas" className="flex flex-col gap-6">
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
