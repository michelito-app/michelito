import { useId, useState, type ReactNode } from 'react'
import type { Split, SplitBody } from '@/lib/api'
import { sharedBody, type SplitDraft, splitDraftOf, type SplitMode } from '@/lib/links'
import { cn } from '@/lib/utils'
import { Action, FIELD } from './linkParts'

interface SplitFormProps {
  currency: string
  /** El monto del gasto (tu parte no puede pasarlo). */
  amountCents: number
  /** El reparto que se propone: el del gasto o el del último agregado al grupo. */
  initial: Split | null
  saving: boolean
  submitLabel: string
  onSave: (body: SplitBody) => void
  onCancel?: () => void
  /** Campos extra antes del botón (p. ej. «Con quién» al crear un grupo). */
  children?: ReactNode
}

const MODES: readonly { mode: SplitMode; label: string }[] = [
  { mode: 'people', label: 'Éramos' },
  { mode: 'share', label: 'Mi parte' },
  { mode: 'other', label: 'Lo pagué por otra persona' },
]

/** Cómo se reparte un gasto: "Éramos N", "Mi parte: X" o "Lo pagué por otra persona". */
export function SplitForm({
  currency,
  amountCents,
  initial,
  saving,
  submitLabel,
  onSave,
  onCancel,
  children,
}: SplitFormProps) {
  const ids = useId()
  const [draft, setDraft] = useState<SplitDraft>(() => splitDraftOf(initial))
  const [error, setError] = useState<string | null>(null)
  const prefix = currency === 'USD' ? 'US$' : 'RD$'

  function change(patch: Partial<SplitDraft>) {
    setDraft((current) => ({ ...current, ...patch }))
    setError(null)
  }

  function save() {
    const result = sharedBody(draft, amountCents)
    if ('error' in result) setError(result.error)
    else onSave(result.body)
  }

  return (
    <div className="flex flex-col gap-2">
      <fieldset className="flex flex-col">
        <legend className="sr-only">Cómo se reparte</legend>
        {MODES.map(({ mode, label }) => (
          <div key={mode} className="flex flex-col text-sm">
            <label className="flex min-h-11 cursor-pointer items-center gap-2.5">
              <input
                type="radio"
                name={`${ids}-mode`}
                checked={draft.mode === mode}
                onChange={() => change({ mode })}
                className="size-[18px] shrink-0 cursor-pointer accent-primary"
              />
              {label}
            </label>
            {draft.mode === mode && mode === 'people' && (
              <div className="mb-2 flex items-center gap-1.5 pl-7">
                <input
                  type="number"
                  inputMode="numeric"
                  min={2}
                  max={100}
                  aria-label="Cuántos eran"
                  value={draft.people}
                  onChange={(event) => change({ people: event.target.value })}
                  className={cn(FIELD, 'w-20 flex-none')}
                />
                <span className="text-muted-foreground">personas, contándote</span>
              </div>
            )}
            {draft.mode === mode && mode === 'share' && (
              <div className="mb-2 flex items-center gap-1.5 pl-7">
                <span className="text-muted-foreground">{prefix}</span>
                <input
                  inputMode="decimal"
                  aria-label="Tu parte"
                  value={draft.share}
                  onChange={(event) => change({ share: event.target.value })}
                  className={`${FIELD} max-w-40`}
                />
              </div>
            )}
          </div>
        ))}
      </fieldset>
      {children}
      {error && (
        <p role="alert" className="text-[13px] text-up-ink">
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
