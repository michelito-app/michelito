import type { ReactNode } from 'react'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { DismissedSection } from '@/components/recurring/DismissedSection'
import { GroupSection } from '@/components/recurring/GroupSection'
import { LoadError } from '@/components/LoadError'
import { PANEL } from '@/components/summary/styles'
import { Skeleton } from '@/components/ui/skeleton'
import type { Recurring } from '@/lib/api'
import { formatDop } from '@/lib/money'
import { longDay } from '@/lib/months'
import { useRecurring } from '@/lib/queries'
import { sections } from '@/lib/recurring'
import { useAccountSelection } from '@/lib/useAccountSelection'
import { cn } from '@/lib/utils'

/** Pantalla Recurrentes: cargos que se repiten cada mes o cada año, por grupo. Con las cuentas
 * elegidas (las mismas del Resumen: URL `cuentas` o las recordadas) solo los de esas cuentas. */
export function RecurringPage() {
  const { selection, accounts, ready, select } = useAccountSelection()
  const recurring = useRecurring(null, selection, ready)

  if (recurring.isError) {
    return (
      <LoadError
        what="los recurrentes"
        error={recurring.error}
        onRetry={() => recurring.refetch()}
      />
    )
  }
  if (!ready || recurring.isPending) return <PageSkeleton />

  const data = recurring.data
  const month = data.as_of?.slice(0, 7) ?? null
  return (
    <>
      <Header data={data}>
        {accounts.length > 1 && (
          <AccountPicker selection={selection} accounts={accounts} onChange={select} />
        )}
      </Header>
      {data.items.length === 0 && data.dismissed.length === 0 ? (
        <Empty />
      ) : (
        <div className="flex max-w-[960px] flex-col gap-6">
          {data.items.length === 0 && <Empty />}
          {sections(data).map((section) => (
            <GroupSection
              key={section.group}
              section={section}
              month={month}
              firstMonth={data.first_month}
              overview={data}
            />
          ))}
          {data.dismissed.length > 0 && <DismissedSection items={data.dismissed} />}
        </div>
      )}
    </>
  )
}

function Header({ data, children }: { data: Recurring; children?: ReactNode }) {
  const yearly = data.groups.reduce((sum, group) => sum + group.yearly_cents, 0)
  return (
    <header className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">Recurrentes</h1>
        {children}
      </div>
      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 tabular-nums">
        <span className="text-[17px] font-bold whitespace-nowrap">
          {formatDop(data.monthly_cents)} al mes
        </span>
        <span className="text-sm whitespace-nowrap text-muted-foreground">
          · {formatDop(yearly)} al año
        </span>
      </p>
      {data.as_of && (
        <p className="text-[13px] text-muted-foreground">
          Cargos activos, con los cobros hasta el {longDay(data.as_of)} de {data.as_of.slice(0, 4)}
        </p>
      )}
    </header>
  )
}

function Empty() {
  return (
    <div className={cn(PANEL, 'flex max-w-[960px] flex-col gap-1.5 px-6 py-10 text-center')}>
      <p className="text-[15px] font-semibold">Sin cargos recurrentes detectados</p>
      <p className="text-[13px] text-muted-foreground">
        Aparecen aquí cuando un comercio cobra lo mismo cada mes o cada año.
      </p>
    </div>
  )
}

function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Cargando los recurrentes" className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-9 w-56 rounded-[10px]" />
        <Skeleton className="h-5 w-72 max-w-full" />
      </div>
      <div className="flex max-w-[960px] flex-col gap-6">
        {[0, 1].map((i) => (
          <Skeleton key={i} className="h-48 rounded-2xl" />
        ))}
      </div>
    </div>
  )
}
