import { useState } from 'react'
import { Link } from 'react-router'
import type { Tx } from '@/lib/api'
import { BUDGET_PATH } from '@/lib/budget'
import { useChangeReserve, useLinkToReserve, useTxReserve } from '@/lib/budgetQueries'
import { monthPhrase } from '@/lib/months'
import { cn } from '@/lib/utils'
import { Action, FIELD, SECTION, SECTION_TITLE } from './linkParts'

const LINK = 'inline-flex min-h-11 items-center font-semibold text-primary'

/** En el detalle de un gasto: «Cubierto por la reserva X» (con «Quitar de la reserva») o «Es de
 * una reserva…», que lo vincula a una (la que se sugiere, primero). */
export function ReserveSection({ tx }: { tx: Tx }) {
  const debit = tx.kind === 'gasto' && tx.amount_cents > 0
  const state = useTxReserve(tx.fingerprint, debit)
  const [open, setOpen] = useState(false)
  const unlink = useChangeReserve()
  if (!debit || !state.data) return null
  const data = state.data
  if (data.reserve) {
    const reserve = data.reserve
    return (
      <section aria-label="Reserva" className={SECTION}>
        <h3 className={SECTION_TITLE}>Reserva</h3>
        <p data-testid="reserve-state" className="text-[13px] text-ink-2">
          Cubierto por la reserva <span className="font-semibold">{reserve.name}</span>: no cuenta
          contra el tope de su categoría.
        </p>
        <p className="text-[13px] text-muted-foreground">
          Para compartirlo o mandarlo a otro vínculo, primero quítalo de la reserva.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Action
            onClick={() =>
              unlink.mutate({ action: 'unlink', id: reserve.id, fingerprint: tx.fingerprint })
            }
            disabled={unlink.isPending}
          >
            Quitar de la reserva
          </Action>
          <Link to={BUDGET_PATH} className={LINK}>
            Ver en Presupuesto
          </Link>
        </div>
        {unlink.isError && (
          <p role="alert" className="text-[13px] text-up-ink">
            No se pudo quitar: {unlink.error.message}
          </p>
        )}
      </section>
    )
  }
  if (!data.can_link) {
    if (!data.reason || data.options.length === 0) return null
    return (
      <section aria-label="Reserva" className={SECTION}>
        <h3 className={SECTION_TITLE}>Reserva</h3>
        <p data-testid="reserve-reason" className="text-[13px] text-muted-foreground">
          No se puede vincular a una reserva: {data.reason}.
        </p>
      </section>
    )
  }
  return (
    <section aria-label="Reserva" className={SECTION}>
      <h3 className={SECTION_TITLE}>Reserva</h3>
      {!open ? (
        <div>
          <Action onClick={() => setOpen(true)}>Es de una reserva…</Action>
        </div>
      ) : (
        <LinkForm tx={tx} options={data.options} onCancel={() => setOpen(false)} />
      )}
    </section>
  )
}

interface LinkFormProps {
  tx: Tx
  options: { id: number; name: string; category: string; next_due: string | null }[]
  onCancel: () => void
}

function LinkForm({ tx, options, onCancel }: LinkFormProps) {
  const [chosen, setChosen] = useState(String(options[0]?.id ?? ''))
  const link = useLinkToReserve()
  const submit = () => {
    if (chosen) link.mutate({ id: Number(chosen), fingerprints: [tx.fingerprint] })
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-ink-2">
        Un gasto de una reserva no cuenta contra el tope de su categoría: se muestra «cubierto por
        la reserva».
      </p>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
        Reserva
        <select
          aria-label="Reserva"
          value={chosen}
          onChange={(event) => setChosen(event.target.value)}
          className={cn(FIELD, 'cursor-pointer font-medium')}
        >
          {options.map((option) => (
            <option key={option.id} value={String(option.id)}>
              {option.name}
              {option.next_due ? ` · vence en ${monthPhrase(option.next_due)}` : ''}
            </option>
          ))}
        </select>
      </label>
      <div className="flex flex-wrap gap-2">
        <Action primary onClick={submit} disabled={link.isPending || !chosen}>
          Vincular
        </Action>
        <Action onClick={onCancel}>Cancelar</Action>
      </div>
      {link.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          No se pudo vincular: {link.error.message}
        </p>
      )}
    </div>
  )
}
