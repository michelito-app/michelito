import { type ReactNode, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router'
import { AccountPicker } from '@/components/filters/AccountPicker'
import { InvestmentRow } from '@/components/investments/InvestmentRow'
import { LoadError } from '@/components/LoadError'
import { FOCUS, PANEL } from '@/components/summary/styles'
import { FIELD } from '@/components/transactions/linkParts'
import { Skeleton } from '@/components/ui/skeleton'
import type { InvestmentList } from '@/lib/api'
import {
  CHIPS,
  chipCounts,
  emptyText,
  filterInvestments,
  investmentFigures,
  investmentParams,
  noneText,
  OPEN_PARAM,
  parseChip,
  parseOpen,
  QUERY_PARAM,
  STATUS_PARAM,
  withPinned,
} from '@/lib/investments'
import { useInvestmentList } from '@/lib/queries'
import { useAccountSelection } from '@/lib/useAccountSelection'
import { cn } from '@/lib/utils'

/** Pantalla Inversiones: todas, de todos los meses, con las cuentas elegidas (las del
 * Resumen). El chip (`estado`), la búsqueda (`q`) y la desplegada (`inversion`) van en la URL:
 * «Volver» desde la pantalla de una inversión regresa igual. */
export function InvestmentsPage() {
  const { selection, accounts, ready, select } = useAccountSelection()
  const list = useInvestmentList(selection, ready)

  const picker = accounts.length > 1 && (
    <AccountPicker selection={selection} accounts={accounts} onChange={select} />
  )
  if (list.isError) {
    return (
      <>
        <Header>{picker}</Header>
        <LoadError what="las inversiones" error={list.error} onRetry={() => list.refetch()} />
      </>
    )
  }
  if (!ready || list.isPending) return <PageSkeleton />

  const data = list.data
  return (
    <>
      <Header>{picker}</Header>
      {data.investments.length === 0 ? (
        <Empty text={emptyText(selection !== null)} />
      ) : (
        <Content data={data} />
      )}
    </>
  )
}

function Header({ children }: { children?: ReactNode }) {
  return (
    <header className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[26px] font-bold tracking-[-0.02em] sm:text-[30px]">Inversiones</h1>
        {children}
      </div>
      <p className="text-[13px] text-muted-foreground">
        Lo que mandaste a invertir, lo que rinde y el capital que vuelve
      </p>
    </header>
  )
}

function Content({ data }: { data: InvestmentList }) {
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const chip = parseChip(params.get(STATUS_PARAM))
  const query = params.get(QUERY_PARAM) ?? ''
  const open = parseOpen(params.get(OPEN_PARAM))
  // Como Compartidos: la desplegada al volver se muestra y recibe el foco una vez, y sigue en
  // la lista aunque ya no coincida hasta que cambie el chip o la búsqueda.
  const [arrived, setArrived] = useState(open)
  const [pinned, setPinned] = useState(open)
  const all = data.investments
  const shown = withPinned(all, filterInvestments(all, chip, query), pinned)
  const counts = chipCounts(all)

  const update = (next: Parameters<typeof investmentParams>[1]) => {
    if (next.chip !== undefined || next.query !== undefined) setPinned(null)
    const current = new URLSearchParams(window.location.search)
    setParams(investmentParams(current, next), { replace: true })
  }
  const fromFor = (id: number) =>
    `${location.pathname}?${investmentParams(params, { open: id }).toString()}`

  return (
    <div className="flex max-w-[960px] min-w-0 flex-col gap-6">
      <Figures data={data} />
      <section
        aria-label="Inversiones"
        className={cn(PANEL, 'flex min-w-0 flex-col gap-3 px-5 pt-4 pb-2 sm:px-6')}
      >
        <input
          type="search"
          aria-label="Buscar inversiones"
          placeholder="Buscar por nombre, con quién, comercio o monto"
          value={query}
          onChange={(event) => update({ query: event.target.value })}
          className={FIELD}
        />
        <div role="group" aria-label="Estado" className="flex flex-wrap gap-2">
          {CHIPS.map((c) => (
            <ChipButton
              key={c.chip}
              label={c.label}
              count={counts[c.chip]}
              pressed={chip === c.chip}
              onClick={() => update({ chip: c.chip })}
            />
          ))}
        </div>
        {shown.length === 0 ? (
          <p className="py-3 text-sm text-muted-foreground">{noneText(chip, query)}</p>
        ) : (
          <ul aria-label="Lista de inversiones" className="flex flex-col">
            {shown.map((investment) => (
              <InvestmentRow
                key={investment.id}
                investment={investment}
                expanded={open === investment.id}
                reveal={arrived === investment.id}
                onRevealed={() => setArrived(null)}
                from={fromFor(investment.id)}
                onToggle={() => update({ open: open === investment.id ? null : investment.id })}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

interface ChipButtonProps {
  label: string
  count: number
  pressed: boolean
  onClick: () => void
}

function ChipButton({ label, count, pressed, onClick }: ChipButtonProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        'inline-flex min-h-11 items-center gap-1.5 rounded-full border px-4 text-sm font-semibold',
        pressed
          ? 'border-transparent bg-secondary text-secondary-foreground'
          : 'border-[#D6D6D0] bg-card text-ink-2 hover:bg-muted',
        FOCUS,
      )}
    >
      {label}
      <span className="font-medium text-muted-foreground tabular-nums">{count}</span>
    </button>
  )
}

function Figures({ data }: { data: InvestmentList }) {
  return (
    <section aria-label="Totales" className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {investmentFigures(data).map((figure) => (
        <div key={figure.key} className={cn(PANEL, 'flex flex-col gap-1 px-5 py-4')}>
          <span className="text-[13px] font-medium text-ink-2">{figure.label}</span>
          <strong
            data-testid={`investments-${figure.key}`}
            className="text-[24px] leading-tight font-bold tracking-[-0.01em] whitespace-nowrap tabular-nums"
          >
            {figure.value}
          </strong>
          {figure.extra && (
            <span className="text-[13px] text-muted-foreground">{figure.extra}</span>
          )}
        </div>
      ))}
    </section>
  )
}

function Empty({ text }: { text: string }) {
  return (
    <div
      className={cn(PANEL, 'flex max-w-[960px] flex-col items-center gap-2 px-6 py-10 text-center')}
    >
      <p className="text-[15px] font-semibold">{text}</p>
      <p className="text-[13px] text-muted-foreground">
        Abre en Transacciones el débito con que mandaste el dinero y toca «Es una inversión…».
        Aquí verás lo aportado, lo que rinde y el capital que vuelve.
      </p>
      <Link
        to="/transacciones"
        className={cn(
          'inline-flex min-h-11 items-center rounded-xl border border-[#D6D6D0] bg-card px-4 text-sm font-semibold text-ink-2 no-underline hover:bg-muted',
          FOCUS,
        )}
      >
        Ir a Transacciones
      </Link>
    </div>
  )
}

function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Cargando las inversiones" className="flex flex-col gap-6">
      <Skeleton className="h-9 w-56 rounded-[10px]" />
      <div className="grid max-w-[960px] grid-cols-1 gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-24 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-64 max-w-[960px] rounded-2xl" />
    </div>
  )
}
