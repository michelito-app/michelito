import { Check } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import type { RecurringGroupKey, Tx, TxRecurringBody } from '@/lib/api'
import { useMarkTxRecurring, useTxRecurring } from '@/lib/queries'
import { GROUP_OPTIONS, MAX_INSTALLMENTS, parseInstallments, txRecurringBody } from '@/lib/recurring'
import { cn } from '@/lib/utils'
import { Action, FIELD, SECTION, SECTION_TITLE } from './linkParts'

const LINK = 'inline-flex min-h-11 items-center font-semibold text-primary'

/** En el detalle de un débito: «Es recurrente…» (cadencia, grupo y, en un préstamo, cuotas) o,
 * si ya lo es, dónde está en Recurrentes. Marca el comercio o su proveedor. */
export function RecurringSection({ tx }: { tx: Tx }) {
  const debit = tx.kind === 'gasto' && tx.amount_cents > 0
  const state = useTxRecurring(tx.fingerprint, debit)
  const [open, setOpen] = useState(false)
  if (!debit || !state.data) return null
  const data = state.data
  if (data.recurring) {
    return (
      <section aria-label="Recurrente" className={SECTION}>
        <h3 className={SECTION_TITLE}>Recurrente</h3>
        <p data-testid="recurring-state" className="text-[13px] text-ink-2">
          Es recurrente: <span className="font-semibold">{data.name}</span>
          {data.group && ` · ${data.group}`}
        </p>
        <Link to="/recurrentes" className={LINK}>
          Ver en Recurrentes
        </Link>
      </section>
    )
  }
  if (!data.eligible) return null
  return (
    <section aria-label="Recurrente" className={SECTION}>
      <h3 className={SECTION_TITLE}>Recurrente</h3>
      {!open ? (
        <div>
          <Action onClick={() => setOpen(true)}>Es recurrente…</Action>
        </div>
      ) : (
        <RecurringForm tx={tx} name={data.name} loan={data.loan} onCancel={() => setOpen(false)} />
      )}
    </section>
  )
}

interface RecurringFormProps {
  tx: Tx
  name: string
  loan: boolean
  onCancel: () => void
}

function RecurringForm({ tx, name, loan, onCancel }: RecurringFormProps) {
  const ids = useId()
  const save = useMarkTxRecurring()
  const [cadence, setCadence] = useState<TxRecurringBody['cadence']>('mensual')
  const [group, setGroup] = useState<RecurringGroupKey | ''>(loan ? 'prestamos' : '')
  const [left, setLeft] = useState('')
  const [invalid, setInvalid] = useState(false)
  const isLoan = loan || group === 'prestamos'

  function submit() {
    const installments = isLoan && left.trim() !== '' ? parseInstallments(left) : null
    if (isLoan && left.trim() !== '' && installments === null) {
      setInvalid(true)
      return
    }
    save.mutate({
      fingerprint: tx.fingerprint,
      body: txRecurringBody(cadence, group, installments),
    })
  }

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <p className="text-[13px] text-ink-2">
        Marca <span className="font-semibold">{name}</span> como recurrente: aparece en
        Recurrentes con sus cobros.
      </p>
      <fieldset className="flex flex-wrap gap-2">
        <legend className="pb-2 text-[13px] font-semibold text-ink-2">Cada cuánto</legend>
        {(['mensual', 'anual'] as const).map((value) => (
          <label
            key={value}
            className={cn(
              'flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border px-3 text-sm',
              cadence === value ? 'border-primary bg-[#F6FAF8]' : 'border-border',
            )}
          >
            <input
              type="radio"
              name={`${ids}-cadence`}
              value={value}
              checked={cadence === value}
              onChange={() => setCadence(value)}
              className="size-[18px] cursor-pointer accent-primary"
            />
            {value === 'mensual' ? 'Cada mes' : 'Cada año'}
          </label>
        ))}
      </fieldset>
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
        Grupo
        <select
          aria-label="Grupo"
          value={group}
          onChange={(event) => setGroup(event.target.value as RecurringGroupKey | '')}
          className={cn(FIELD, 'cursor-pointer font-medium')}
        >
          <option value="">Según su categoría</option>
          {GROUP_OPTIONS.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {isLoan && (
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-ink-2">
          Cuotas que quedan (opcional)
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_INSTALLMENTS}
            step={1}
            value={left}
            aria-invalid={invalid}
            aria-describedby={invalid ? `${ids}-hint` : undefined}
            onChange={(event) => {
              setLeft(event.target.value)
              setInvalid(false)
            }}
            className={cn(FIELD, 'w-32 tabular-nums aria-invalid:border-up')}
          />
          {invalid && (
            <span id={`${ids}-hint`} className="font-normal text-up-ink">
              Escribe un número entero de 0 a {MAX_INSTALLMENTS}.
            </span>
          )}
        </label>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={save.isPending}
          className="inline-flex h-11 cursor-pointer items-center rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-60"
        >
          {save.isPending ? 'Guardando…' : 'Marcar como recurrente'}
        </button>
        <Action onClick={onCancel} disabled={save.isPending}>
          Cancelar
        </Action>
      </div>
      {save.isError && (
        <p role="alert" className="text-[13px] text-up-ink">
          No se pudo guardar: {save.error.message}
        </p>
      )}
      {save.isSuccess && (
        <p role="status" className="inline-flex items-center gap-1.5 text-[13px] text-primary">
          <Check size={14} aria-hidden="true" />
          Guardado
        </p>
      )}
    </form>
  )
}
