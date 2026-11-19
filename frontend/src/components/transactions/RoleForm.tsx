import { useId, useState } from 'react'
import type { CreditRole, RoleBody } from '@/lib/api'
import { roleBody } from '@/lib/investments'
import { formatMoney, ROLE_LABELS } from '@/lib/links'
import { Action, FIELD } from './linkParts'

const ROLES: CreditRole[] = ['return', 'capital', 'mixed']

interface RoleFormProps {
  amountCents: number // el crédito, positivo
  currency: string
  initial?: CreditRole
  initialCapital?: number | null
  saving: boolean
  submitLabel: string
  onSave: (body: RoleBody) => void
  onCancel?: () => void
}

/** El tipo de un crédito de una inversión: Rendimiento, Devolución de capital o Mixto (con la
 * parte de capital; el resto es rendimiento). */
export function RoleForm({
  amountCents,
  currency,
  initial = 'return',
  initialCapital = null,
  saving,
  submitLabel,
  onSave,
  onCancel,
}: RoleFormProps) {
  const ids = useId()
  const [role, setRole] = useState<CreditRole>(initial)
  const [capital, setCapital] = useState(
    initialCapital === null ? '' : (initialCapital / 100).toFixed(2),
  )
  const [error, setError] = useState<string | null>(null)

  function save() {
    const result = roleBody(role, capital, amountCents)
    if ('error' in result) {
      setError(result.error)
      return
    }
    setError(null)
    onSave(result.body)
  }

  return (
    <div className="flex flex-col gap-2">
      <fieldset className="flex flex-col gap-1">
        <legend className="pb-1 text-[13px] font-semibold text-ink-2">
          ¿Qué es este crédito de {formatMoney(amountCents, currency)}?
        </legend>
        {ROLES.map((value) => (
          <label
            key={value}
            className="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg px-1 text-sm hover:bg-[#FAFAF8]"
          >
            <input
              type="radio"
              name={`${ids}-role`}
              value={value}
              checked={role === value}
              onChange={() => setRole(value)}
              className="size-[18px] shrink-0 cursor-pointer accent-primary"
            />
            {ROLE_LABELS[value]}
            {value === 'mixed' && (
              <span className="text-[13px] text-muted-foreground">: capital y rendimiento</span>
            )}
          </label>
        ))}
      </fieldset>
      {role === 'mixed' && (
        <label className="flex flex-col gap-1 text-[13px] font-semibold text-ink-2">
          Parte de capital (el resto es rendimiento)
          <input
            inputMode="decimal"
            value={capital}
            placeholder="50,000"
            aria-invalid={error !== null}
            aria-describedby={error ? `${ids}-error` : undefined}
            onChange={(event) => setCapital(event.target.value)}
            className={FIELD}
          />
        </label>
      )}
      {error && (
        <p id={`${ids}-error`} role="alert" className="text-[13px] text-up-ink">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Action primary disabled={saving} onClick={save}>
          {submitLabel}
        </Action>
        {onCancel && <Action onClick={onCancel}>Cancelar</Action>}
      </div>
    </div>
  )
}
