import { useState } from 'react'
import { FOCUS } from '@/components/summary/styles'
import type { Category } from '@/lib/api'
import {
  type Reserve,
  type ReserveBody,
  type Schedule,
  SCHEDULES,
  parsePesos,
  scheduleMonths,
  scheduleOf,
} from '@/lib/budget'
import { choosable } from '@/lib/categories'
import { cn } from '@/lib/utils'

const FIELD = cn(
  'h-11 w-full min-w-0 rounded-xl border border-[#D6D6D0] bg-card px-3 text-sm text-foreground',
  FOCUS,
)
const LABEL = 'flex min-w-0 flex-col gap-1.5 text-[13px] font-semibold text-ink-2'
const BUTTON = cn(
  'inline-flex h-11 items-center justify-center rounded-xl px-4 text-sm font-semibold',
  FOCUS,
)

interface ReserveFormProps {
  categories: readonly Category[]
  /** Para editar: la reserva de ahora (si no, una nueva). */
  current?: Reserve
  /** El mes de hoy (AAAA-MM), para el vencimiento por omisión. */
  today: string
  busy: boolean
  error: string | null
  onSave: (body: ReserveBody) => void
  onCancel: () => void
}

/** Nombre, monto estimado (RD$), categoría, cada cuánto (cada año, cada 6 meses o una vez), el
 * vencimiento (AAAA-MM) y si junta varios gastos. */
export function ReserveForm({
  categories,
  current,
  today,
  busy,
  error,
  onSave,
  onCancel,
}: ReserveFormProps) {
  const usable = choosable(categories.filter((c) => c.kind === 'gasto' && !c.hidden))
  const [name, setName] = useState(current?.name ?? '')
  const [amount, setAmount] = useState(current ? String(current.amount_cents / 100) : '')
  const [categoryId, setCategoryId] = useState(String(current?.category_id ?? usable[0]?.id ?? ''))
  const [schedule, setSchedule] = useState<Schedule>(scheduleOf(current?.every_months ?? 12))
  const [due, setDue] = useState(current?.due_month ?? today)
  const [multiple, setMultiple] = useState(current?.multiple ?? false)
  const [problem, setProblem] = useState<string | null>(null)

  function submit() {
    const cents = parsePesos(amount)
    if (!name.trim()) return setProblem('Ponle un nombre.')
    if (cents === null || cents <= 0) {
      return setProblem('Escribe el monto en pesos, por ejemplo 3500.')
    }
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(due)) return setProblem('Elige el mes del vencimiento.')
    setProblem(null)
    onSave({
      name: name.trim(),
      amount_cents: cents,
      category_id: Number(categoryId),
      due_month: due,
      every_months: scheduleMonths(schedule),
      multiple,
    })
  }

  return (
    <form
      aria-label={current ? `Editar ${current.name}` : 'Nueva reserva'}
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <label className={LABEL}>
        Nombre
        <input
          aria-label="Nombre de la reserva"
          value={name}
          maxLength={80}
          onChange={(event) => setName(event.target.value)}
          className={FIELD}
        />
      </label>
      <label className={LABEL}>
        Monto estimado (RD$)
        <input
          aria-label="Monto estimado (RD$)"
          inputMode="decimal"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          className={FIELD}
        />
      </label>
      <label className={LABEL}>
        Categoría
        <select
          aria-label="Categoría de la reserva"
          value={categoryId}
          onChange={(event) => setCategoryId(event.target.value)}
          className={cn(FIELD, 'cursor-pointer')}
        >
          {usable.map((c) => (
            <option key={c.id} value={String(c.id)}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label className={LABEL}>
        {schedule === 'una' ? 'Vence en' : 'Primer vencimiento'}
        <input
          type="month"
          aria-label="Mes del vencimiento"
          value={due}
          onChange={(event) => setDue(event.target.value)}
          className={FIELD}
        />
      </label>
      <fieldset className="flex flex-wrap gap-2 sm:col-span-2">
        <legend className="pb-2 text-[13px] font-semibold text-ink-2">Cada cuánto</legend>
        {SCHEDULES.map((option) => (
          <label
            key={option.value}
            className={cn(
              'flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border px-3 text-sm',
              schedule === option.value ? 'border-primary bg-[#F6FAF8]' : 'border-border',
            )}
          >
            <input
              type="radio"
              name="reserve-schedule"
              checked={schedule === option.value}
              onChange={() => setSchedule(option.value)}
              className="size-[18px] cursor-pointer accent-primary"
            />
            {option.label}
          </label>
        ))}
      </fieldset>
      <label className="flex min-h-11 cursor-pointer items-center gap-2 text-sm sm:col-span-2">
        <input
          type="checkbox"
          checked={multiple}
          onChange={(event) => setMultiple(event.target.checked)}
          className="size-[18px] cursor-pointer accent-primary"
        />
        Junta varios gastos (como Navidad)
      </label>
      {(problem || error) && (
        <p role="alert" className="text-[13px] text-up-ink sm:col-span-2">
          {problem ?? `No se pudo guardar: ${error}`}
        </p>
      )}
      <div className="flex flex-wrap gap-2 sm:col-span-2">
        <button
          type="submit"
          disabled={busy}
          className={cn(BUTTON, 'bg-primary text-primary-foreground hover:bg-primary/85 disabled:opacity-50')}
        >
          {current ? 'Guardar cambios' : 'Crear reserva'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className={cn(BUTTON, 'border border-border bg-card text-ink-2 hover:bg-muted')}
        >
          Cancelar
        </button>
      </div>
    </form>
  )
}
