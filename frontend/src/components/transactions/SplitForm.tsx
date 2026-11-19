import { useId, useState, type ReactNode } from 'react'
import { t } from '@/i18n'
import type { Split, SplitBody } from '@/lib/api'
import { sharedBody, type SplitDraft, splitDraftOf, type SplitMode } from '@/lib/links'
import { cn } from '@/lib/utils'
import { Action, FIELD } from './linkParts'

interface SplitFormProps {
  currency: string
  /** The expense amount (your share cannot exceed it). */
  amountCents: number
  /** The proposed split: the expense's own or the one of the last expense added to the group. */
  initial: Split | null
  saving: boolean
  submitLabel: string
  onSave: (body: SplitBody) => void
  onCancel?: () => void
  /** Extra fields before the button (e.g. who it was with, when creating a group). */
  children?: ReactNode
}

const MODES: readonly { mode: SplitMode; label: string }[] = [
  { mode: 'people', label: t('transactions.split.people') },
  { mode: 'share', label: t('transactions.split.share') },
  { mode: 'other', label: t('transactions.split.other') },
]

/** How an expense is split: N people, my share X, or paid for someone else. */
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
        <legend className="sr-only">{t('transactions.split.legend')}</legend>
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
                  aria-label={t('transactions.split.peopleCount')}
                  value={draft.people}
                  onChange={(event) => change({ people: event.target.value })}
                  className={cn(FIELD, 'w-20 flex-none')}
                />
                <span className="text-muted-foreground">{t('transactions.split.peopleSuffix')}</span>
              </div>
            )}
            {draft.mode === mode && mode === 'share' && (
              <div className="mb-2 flex items-center gap-1.5 pl-7">
                <span className="text-muted-foreground">{prefix}</span>
                <input
                  inputMode="decimal"
                  aria-label={t('transactions.split.yourShare')}
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
        {onCancel && <Action onClick={onCancel}>{t('transactions.cancel')}</Action>}
      </div>
    </div>
  )
}
