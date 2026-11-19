import { useState } from 'react'
import { FOCUS, PANEL, PANEL_TITLE, ROW_DIVIDER } from '@/components/summary/styles'
import {
  asideNotes,
  type Budget,
  type BudgetLine,
  barShare,
  capInput,
  FILTERED_NOTE,
  missingText,
  parsePesos,
  spentText,
  warningText,
} from '@/lib/budget'
import { useActivateBudget, useResolveWarning, useSetCap } from '@/lib/budgetQueries'
import { formatDop } from '@/lib/money'
import { cn } from '@/lib/utils'

const BUTTON = cn(
  'inline-flex h-11 shrink-0 items-center justify-center rounded-xl px-4 text-sm font-semibold',
  FOCUS,
)
const PRIMARY = cn(
  BUTTON,
  'bg-primary text-primary-foreground hover:bg-primary/85 disabled:opacity-50',
)
const SECONDARY = cn(
  BUTTON,
  'border border-border bg-card text-ink-2 hover:bg-muted disabled:opacity-50',
)

/** «Categorías»: una barra por categoría (gastado / tope), la que más pasa primero, con el tope
 * editable en línea, los gastos únicos y lo cubierto aparte, y los avisos de «lo habitual
 * cambió». Sin activar, ofrece activarlo. */
export function CategoryBudget({ budget }: { budget: Budget }) {
  if (!budget.active) return <Activate />
  const missing = missingText(budget.missing)
  const shown = budget.lines.filter((line) => line.active)
  const rest = budget.lines.filter((line) => !line.active)
  return (
    <section
      aria-labelledby="budget-categories"
      className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="budget-categories" className={PANEL_TITLE}>
          Categorías
        </h2>
        <p className="text-[13px] text-ink-2">
          {formatDop(budget.spent_cents)} de {formatDop(budget.cap_cents)} en las que tienen tope
          {budget.over_count > 0 &&
            ` · ${budget.over_count} pasadas (+${formatDop(budget.over_cents)})`}
        </p>
      </div>
      <p className="text-[13px] text-muted-foreground">
        Cada mes empieza de cero. Los gastos únicos y lo cubierto por reservas no cuentan contra el
        tope (sí en el total del mes). Una categoría cuenta como pasada si excede su tope en más de
        5 % (y de RD$ 500).
      </p>
      {budget.filtered && (
        <p data-testid="budget-filtered" className="text-[13px] font-semibold text-ink-2">
          {FILTERED_NOTE}
        </p>
      )}
      {missing && (
        <p role="status" data-testid="budget-partial" className="text-[13px] font-semibold text-up-ink">
          {missing}
        </p>
      )}
      <ul className="flex flex-col">
        {shown.map((line) => (
          <CategoryRow key={line.category_id} line={line} />
        ))}
      </ul>
      {rest.length > 0 && (
        <details className="group">
          <summary
            className={cn(
              'flex min-h-11 cursor-pointer items-center text-[13px] font-semibold text-primary',
              FOCUS,
            )}
          >
            Otras categorías ({rest.length}): sin tope ni gasto este mes
          </summary>
          <ul className="flex flex-col">
            {rest.map((line) => (
              <CategoryRow key={line.category_id} line={line} />
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}

function Activate() {
  const activate = useActivateBudget()
  return (
    <section
      aria-labelledby="budget-categories"
      className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}
    >
      <h2 id="budget-categories" className={PANEL_TITLE}>
        Categorías
      </h2>
      <p className="text-sm text-ink-2">
        Pon un tope mensual a cada categoría de gasto y compáralo con lo gastado. Cada una arranca
        con lo habitual (la mediana de los últimos 6 meses completos) redondeado a RD$ 500; lo
        cambias cuando quieras.
      </p>
      <div>
        <button
          type="button"
          className={PRIMARY}
          disabled={activate.isPending}
          onClick={() => activate.mutate()}
        >
          {activate.isPending ? 'Activando…' : 'Activar presupuesto'}
        </button>
      </div>
      {activate.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          No se pudo activar: {activate.error.message}
        </p>
      )}
    </section>
  )
}

function CategoryRow({ line }: { line: BudgetLine }) {
  const [editing, setEditing] = useState(false)
  const { share } = barShare(line)
  const over = line.passed
  const notes = asideNotes(line)
  return (
    <li
      aria-label={line.category}
      data-testid="budget-line"
      className={cn(ROW_DIVIDER, 'flex flex-col gap-2 py-3')}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="min-w-0 text-sm font-semibold">{line.category}</span>
        <span className={cn('text-sm tabular-nums', over ? 'font-semibold text-up' : 'text-ink-2')}>
          {spentText(line).replace(/RD\$ /g, 'RD$\u00a0')}
          {line.over_cents > 0 && ` · pasó por ${formatDop(line.over_cents)}`}
        </span>
      </div>
      {line.cap_cents !== null && (
        <div
          role="meter"
          aria-label={`Gastado en ${line.category}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={share}
          className="h-2 overflow-hidden rounded-full bg-muted"
        >
          <div
            className={cn('h-full rounded-full', over ? 'bg-up' : 'bg-primary')}
            style={{ width: `${share}%` }}
          />
        </div>
      )}
      {notes.length > 0 && <p className="text-[13px] text-ink-2">{notes.join(' · ')}</p>}
      {line.warning && <WarningBox line={line} />}
      {editing ? (
        <CapEditor line={line} onClose={() => setEditing(false)} />
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={SECONDARY}
            aria-label={`Editar el tope de ${line.category}`}
            onClick={() => setEditing(true)}
          >
            {line.cap_cents === null ? 'Poner tope' : 'Editar tope'}
          </button>
          {line.manual && <span className="text-[13px] text-muted-foreground">Tope a mano</span>}
        </div>
      )}
    </li>
  )
}

function CapEditor({ line, onClose }: { line: BudgetLine; onClose: () => void }) {
  const [text, setText] = useState(capInput(line.cap_cents))
  const [invalid, setInvalid] = useState(false)
  const save = useSetCap()
  const submit = (cents: number | null) =>
    save.mutate({ categoryId: line.category_id, cents }, { onSuccess: onClose })
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        const cents = parsePesos(text)
        if (cents === null) {
          setInvalid(true)
          return
        }
        submit(cents)
      }}
    >
      <input
        type="text"
        inputMode="decimal"
        aria-label={`Tope de ${line.category} (RD$)`}
        aria-invalid={invalid}
        value={text}
        onChange={(event) => {
          setText(event.target.value)
          setInvalid(false)
        }}
        className={cn(
          'h-11 w-32 min-w-0 rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm',
          FOCUS,
        )}
      />
      <button type="submit" className={PRIMARY} disabled={save.isPending}>
        Guardar tope
      </button>
      <button
        type="button"
        className={SECONDARY}
        disabled={save.isPending}
        onClick={() => submit(null)}
      >
        Sin presupuesto
      </button>
      <button type="button" className={SECONDARY} onClick={onClose}>
        Cancelar
      </button>
      {invalid && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          Escribe el tope en pesos, por ejemplo 16500.
        </p>
      )}
      {save.isError && (
        <p role="alert" className="basis-full text-[13px] text-up-ink">
          No se pudo guardar: {save.error.message}
        </p>
      )}
    </form>
  )
}

function WarningBox({ line }: { line: BudgetLine }) {
  const resolve = useResolveWarning()
  const decide = (accept: boolean) => resolve.mutate({ categoryId: line.category_id, accept })
  return (
    <div
      role="group"
      aria-label={`Aviso de ${line.category}`}
      className="flex flex-col gap-2 rounded-xl border border-up/30 bg-up-soft px-3 py-2"
    >
      <p className="text-[13px] text-up-ink">{warningText(line).replace(/RD\$ /g, 'RD$\u00a0')}</p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={PRIMARY}
          disabled={resolve.isPending}
          onClick={() => decide(true)}
        >
          Actualizar tope
        </button>
        <button
          type="button"
          className={SECONDARY}
          disabled={resolve.isPending}
          onClick={() => decide(false)}
        >
          Dejarlo así
        </button>
      </div>
      {resolve.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          No se pudo guardar: {resolve.error.message}
        </p>
      )}
    </div>
  )
}
