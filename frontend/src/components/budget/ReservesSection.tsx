import { useState } from 'react'
import { Link } from 'react-router'
import { FOCUS, PANEL, PANEL_TITLE, ROW_DIVIDER } from '@/components/summary/styles'
import { type Selection, transactionsHref } from '@/lib/accountFilter'
import type { Category } from '@/lib/api'
import {
  bodyFromSuggestion,
  dueText,
  type Reserve,
  type ReserveBody,
  type Reserves,
  type ReserveSuggestion,
  scheduleText,
  suggestionText,
  yearText,
} from '@/lib/budget'
import { useChangeReserve } from '@/lib/budgetQueries'
import { formatDop, formatUsd } from '@/lib/money'
import { shortDay } from '@/lib/months'
import { cn } from '@/lib/utils'
import { ReserveForm } from './ReserveForm'

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

interface ReservesSectionProps {
  data: Reserves
  categories: readonly Category[]
  today: string
  selection: Selection
}

/** «Reservas»: lo que hay que apartar cada mes para los gastos que no son de cada mes (sin mover
 * dinero), con su próximo vencimiento, el aporte, este año y los gastos vinculados; crear, editar
 * y borrar, y las sugerencias pendientes. */
export function ReservesSection({ data, categories, today, selection }: ReservesSectionProps) {
  const [creating, setCreating] = useState(false)
  const change = useChangeReserve()
  const save = (body: ReserveBody) =>
    change.mutate({ action: 'create', body }, { onSuccess: () => setCreating(false) })
  return (
    <section
      aria-labelledby="budget-reserves"
      className={cn(PANEL, 'flex flex-col gap-3 px-5 py-4')}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="budget-reserves" className={PANEL_TITLE}>
          Reservas
        </h2>
        {data.items.length > 0 && (
          <p className="text-[13px] text-ink-2">
            Apartar {formatDop(data.monthly_cents)} al mes
          </p>
        )}
      </div>
      <p className="text-[13px] text-muted-foreground">
        Un plan para los gastos que no son de cada mes: no mueve dinero. Los gastos vinculados a una
        reserva no cuentan contra el tope de su categoría.
      </p>
      {data.suggestions.length > 0 && <Suggestions items={data.suggestions} />}
      {data.items.length > 0 ? (
        <ul className="flex flex-col">
          {data.items.map((reserve) => (
            <ReserveRow
              key={reserve.id}
              reserve={reserve}
              categories={categories}
              today={today}
              selection={selection}
            />
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-ink-2">Todavía no hay reservas.</p>
      )}
      {creating ? (
        <ReserveForm
          categories={categories}
          today={today}
          busy={change.isPending}
          error={change.isError ? change.error.message : null}
          onSave={save}
          onCancel={() => setCreating(false)}
        />
      ) : (
        <div>
          <button type="button" className={SECONDARY} onClick={() => setCreating(true)}>
            Nueva reserva…
          </button>
        </div>
      )}
    </section>
  )
}

function Suggestions({ items }: { items: ReserveSuggestion[] }) {
  const change = useChangeReserve()
  return (
    <div role="group" aria-label="Sugerencias de reservas" className="flex flex-col gap-2">
      <h3 className="text-[13px] font-semibold text-ink-2">Sugerencias</h3>
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li
            key={item.key}
            aria-label={item.name}
            className="flex flex-col gap-2 rounded-xl border border-primary/30 bg-[#F6FAF8] px-3 py-2"
          >
            <p className="text-sm text-foreground">
              {suggestionText(item).replace(/RD\$ /g, 'RD$\u00a0')}
            </p>
            <p className="text-[13px] text-muted-foreground">{item.reason}</p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={PRIMARY}
                aria-label={`Crear reserva: ${item.name}`}
                disabled={change.isPending}
                onClick={() => change.mutate({ action: 'create', body: bodyFromSuggestion(item) })}
              >
                Crear reserva
              </button>
              <button
                type="button"
                className={SECONDARY}
                aria-label={`Descartar sugerencia: ${item.name}`}
                disabled={change.isPending}
                onClick={() =>
                  change.mutate({ action: 'dismiss', key: item.key, name: item.name })
                }
              >
                Descartar
              </button>
            </div>
          </li>
        ))}
      </ul>
      {change.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          No se pudo guardar: {change.error.message}
        </p>
      )}
    </div>
  )
}

interface ReserveRowProps {
  reserve: Reserve
  categories: readonly Category[]
  today: string
  selection: Selection
}

function ReserveRow({ reserve, categories, today, selection }: ReserveRowProps) {
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const change = useChangeReserve()
  const update = (body: ReserveBody) =>
    change.mutate(
      { action: 'update', id: reserve.id, body: { ...body, once: body.every_months === null } },
      { onSuccess: () => setEditing(false) },
    )
  return (
    <li aria-label={reserve.name} className={cn(ROW_DIVIDER, 'flex flex-col gap-2 py-3')}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="min-w-0 text-sm font-semibold">{reserve.name}</span>
        <span className="text-sm font-semibold tabular-nums">
          {formatDop(reserve.monthly_cents)}/mes
        </span>
      </div>
      <p className="text-[13px] text-ink-2">
        {formatDop(reserve.amount_cents)} · {scheduleText(reserve)} · {reserve.category}
        {reserve.multiple && ' · varios gastos'}
      </p>
      <p className="text-[13px] text-ink-2">
        {dueText(reserve)}
        {reserve.paid && ' (ya tiene su gasto)'} · {yearText(reserve)}
        {reserve.year_without_rate > 0 && ` (+${reserve.year_without_rate} en US$ sin tasa)`}
      </p>
      {reserve.members.length > 0 && (
        <ul aria-label={`Gastos de ${reserve.name}`} className="flex flex-col gap-1 pl-3">
          {reserve.members.map((member) => (
            <li key={member.fingerprint} className="flex flex-wrap items-center gap-x-2 text-[13px]">
              <Link
                to={transactionsHref({ mes: member.month, tx: member.fingerprint }, selection)}
                className="font-semibold text-primary"
              >
                {member.merchant}
              </Link>
              <span className="text-muted-foreground">
                {shortDay(member.day)} ·{' '}
                {member.currency === 'USD'
                  ? formatUsd(member.amount_cents)
                  : formatDop(member.amount_cents)}{' '}
                · cubierto por la reserva
              </span>
              <button
                type="button"
                className={cn('min-h-11 rounded-md px-2 font-semibold text-ink-2 hover:bg-muted', FOCUS)}
                aria-label={`Quitar de la reserva: ${member.merchant}`}
                disabled={change.isPending}
                onClick={() =>
                  change.mutate({
                    action: 'unlink',
                    id: reserve.id,
                    fingerprint: member.fingerprint,
                  })
                }
              >
                Quitar
              </button>
            </li>
          ))}
        </ul>
      )}
      {editing ? (
        <ReserveForm
          categories={categories}
          current={reserve}
          today={today}
          busy={change.isPending}
          error={change.isError ? change.error.message : null}
          onSave={update}
          onCancel={() => setEditing(false)}
        />
      ) : confirming ? (
        <div
          role="alertdialog"
          aria-label={`Borrar ${reserve.name}`}
          className="flex flex-wrap items-center gap-2"
        >
          <span className="text-[13px] text-ink-2">
            ¿Borrar la reserva? Sus gastos vuelven al tope de su categoría.
          </span>
          <button
            type="button"
            className={PRIMARY}
            disabled={change.isPending}
            onClick={() => change.mutate({ action: 'delete', id: reserve.id })}
          >
            Sí, borrar
          </button>
          <button type="button" className={SECONDARY} onClick={() => setConfirming(false)}>
            Cancelar
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={SECONDARY}
            aria-label={`Editar ${reserve.name}`}
            onClick={() => setEditing(true)}
          >
            Editar
          </button>
          <button
            type="button"
            className={SECONDARY}
            aria-label={`Borrar ${reserve.name}`}
            onClick={() => setConfirming(true)}
          >
            Borrar
          </button>
        </div>
      )}
      {change.isError && !editing && (
        <p role="alert" className="text-[13px] text-up-ink">
          No se pudo guardar: {change.error.message}
        </p>
      )}
    </li>
  )
}
